from __future__ import annotations
import json
import os
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer

from .models import CardData
from .storage import JsonStore
from .openai_client import suggest_card
from .renderer import render_card
from .utils import ensure_dir, safe_filename, slugify
from .auth import authenticate_user, create_access_token, verify_token
from .logging_config import setup_logging
import requests
from io import BytesIO

# Configurar logging
logger = setup_logging()
logger.info("=== Iniciando aplicación Cartelas ===")

# Cargar variables de entorno desde .env
BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")
DATA_DIR = BASE / "data"
UPLOADS = DATA_DIR / "uploads"
RENDERS = DATA_DIR / "renders"
IMAGES = DATA_DIR / "images"  # Cache de imágenes
DB_PATH = DATA_DIR / "cards.json"
WEB_DIR = BASE / "web"

ensure_dir(UPLOADS)
ensure_dir(RENDERS)
ensure_dir(IMAGES)
ensure_dir(DATA_DIR / "logs")

store = JsonStore(str(DB_PATH))
logger.info(f"Base de datos cargada desde: {DB_PATH}")

app = FastAPI(title="Carteles 480x670")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

# Esquema de seguridad
security = HTTPBearer()

def get_current_user(credentials = Depends(security)) -> str:
    """Verifica el token JWT en el header Authorization"""
    try:
        user = verify_token(credentials.credentials)
        return user["username"]
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

@app.get("/", response_class=HTMLResponse)
def home():
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return (WEB_DIR / "login.html").read_text(encoding="utf-8")

@app.post("/api/login")
def login(username: str = Form(...), password: str = Form(...)):
    """Endpoint de login - devuelve un token JWT"""
    if not authenticate_user(username, password):
        logger.warning(f"Failed login attempt for user: {username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    access_token = create_access_token(data={"sub": username})
    logger.info(f"User '{username}' logged in successfully")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": username
    }

@app.post("/api/logout")
def logout(username: str = Depends(get_current_user)):
    """Endpoint de logout (el token se elimina en el cliente)"""
    logger.info(f"User '{username}' logged out")
    return {"message": "Logged out successfully"}

@app.get("/api/me")
def get_me(username: str = Depends(get_current_user)):
    """Obtiene información del usuario autenticado"""
    return {"username": username}

@app.get("/api/cards")
def list_cards(q: Optional[str] = None, piece_type: Optional[str] = None, skip: int = 0, limit: int = 25):
    cards, total = store.list_cards(q=q, piece_type=piece_type, skip=skip, limit=limit)
    # respuesta ligera con total
    return {
        "cards": [{
            "id": c.id,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "piece_number": c.data.piece_number,
            "cabinet_number": c.data.cabinet_number,
            "piece_type": c.data.piece_type,
            "title": c.data.title,
            "subtitle": c.data.subtitle,
            "render_path": c.data.render_path,
            "image_path": c.data.image_path,
        } for c in cards],
        "total": total
    }

@app.get("/api/cards/{card_id}")
def get_card(card_id: str):
    c = store.get(card_id)
    if not c:
        raise HTTPException(404, "Card not found")
    return c.model_dump()

@app.post("/api/cards")
def create_card(payload: dict, username: str = Depends(get_current_user)):
    logger.info(f"User '{username}' creating new card")
    # payload puede venir vacío
    data = CardData.model_validate(payload.get("data", payload) if payload else {})
    rec = store.create(data)
    logger.info(f"Card created: {rec.id}")
    return rec.model_dump()

@app.put("/api/cards/{card_id}")
def update_card(card_id: str, payload: dict, username: str = Depends(get_current_user)):
    logger.info(f"User '{username}' updating card {card_id}")
    data = CardData.model_validate(payload.get("data", payload))
    rec = store.update(card_id, data)
    if not rec:
        logger.error(f"Card not found: {card_id}")
        raise HTTPException(404, "Card not found")
    logger.info(f"Card updated: {card_id}")
    return rec.model_dump()

@app.delete("/api/cards/{card_id}")
def delete_card(card_id: str, username: str = Depends(get_current_user)):
    logger.info(f"User '{username}' deleting card {card_id}")
    success = store.delete(card_id)
    if not success:
        logger.error(f"Card not found: {card_id}")
        raise HTTPException(404, "Card not found")
    logger.info(f"Card deleted: {card_id}")
    return {"status": "deleted"}

@app.post("/api/cards/{card_id}/duplicate")
def duplicate_card(card_id: str, username: str = Depends(get_current_user)):
    logger.info(f"User '{username}' duplicating card {card_id}")
    rec = store.duplicate(card_id)
    if not rec:
        logger.error(f"Card not found: {card_id}")
        raise HTTPException(404, "Card not found")
    logger.info(f"Card duplicated: {card_id} -> {rec.id}")
    return rec.model_dump()

@app.post("/api/suggest")
def api_suggest(payload: dict, username: str = Depends(get_current_user)):
    name_query = (payload.get("name_query") or "").strip()
    piece_type = (payload.get("piece_type") or "other").strip()
    piece_number = (payload.get("piece_number") or "").strip()

    if not name_query:
        raise HTTPException(400, "name_query is required")

    try:
        suggestion = suggest_card(name_query=name_query, piece_type=piece_type, piece_number=piece_number)
    except Exception as e:
        raise HTTPException(500, f"Suggest failed: {e}")

    return suggestion

@app.post("/api/preview")
def api_preview(payload: dict, username: str = Depends(get_current_user)):
    """Renderiza una cartela en tiempo real sin guardarla"""
    try:
        data_obj = payload.get("data", {})
        dither = payload.get("dither", 0)  # 0=sin dithering, 1=suave, 2=fuerte
        if isinstance(dither, bool):
            dither = 2 if dither else 0  # Compatibilidad con valores anteriores
        image_path = data_obj.get("image_path")
        
        # Render
        img, cached_path = render_card(data_obj, image_path=image_path, dither=dither)
        
        # Devolver como respuesta directa sin guardar
        from io import BytesIO
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        
        return Response(content=buf.getvalue(), media_type="image/png")
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {e}")

@app.post("/api/cards/{card_id}/upload-image")
async def upload_image(card_id: str, image: UploadFile = File(...), username: str = Depends(get_current_user)):
    c = store.get(card_id)
    if not c:
        raise HTTPException(404, "Card not found")

    ext = Path(image.filename or "").suffix.lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"]:
        raise HTTPException(400, "Unsupported image format")

    # Usar slug del título para el nombre del archivo
    title = c.data.title or card_id
    slug = slugify(title)
    fn = f"{slug}{ext}"
    out = IMAGES / fn
    
    content = await image.read()
    out.write_bytes(content)
    logger.info(f"Image uploaded and cached: {out}")

    c.data.image_path = str(out)
    c.data.render_path = None
    updated = store.update(card_id, c.data)
    return {"ok": True, "image_path": updated.data.image_path}

@app.post("/api/cards/{card_id}/render")
async def api_render(
    card_id: str,
    data: str = Form(...),
    dither: int = Form(0),
    username: str = Depends(get_current_user),
):
    c = store.get(card_id)
    if not c:
        raise HTTPException(404, "Card not found")

    # parse JSON del editor
    try:
        data_obj = json.loads(data)
    except Exception:
        raise HTTPException(400, "Invalid JSON in form field 'data'")

    # La imagen ahora viene en el JSON como URL
    image_path = data_obj.get("image_path")

    # Render
    img, cached_path = render_card(data_obj, image_path=image_path, dither=int(dither))

    out_png = RENDERS / f"{card_id}.png"
    img.save(out_png, format="PNG")

    # Persistimos data + rutas (actualizar image_path si se cacheó)
    new_data = CardData.model_validate(data_obj)
    if cached_path:
        new_data.image_path = cached_path
    new_data.render_path = str(out_png)
    store.update(card_id, new_data)

    return FileResponse(str(out_png), media_type="image/png", filename=f"{card_id}.png")

@app.get("/api/cards/{card_id}/render.png")
def get_render_png(card_id: str):
    c = store.get(card_id)
    if not c or not c.data.render_path:
        raise HTTPException(404, "Render not found")
    p = Path(c.data.render_path)
    if not p.exists():
        raise HTTPException(404, "Render file missing")
    return FileResponse(str(p), media_type="image/png")

@app.post("/api/cards/{card_id}/render.tri")
def render_tri(card_id: str, payload: dict, username: str = Depends(get_current_user)):
    c = store.get(card_id)
    if not c:
        raise HTTPException(404, "Card not found")

    try:
        dither = int(payload.get("dither", 0))
        image_path = c.data.image_path
        
        # Renderizar imagen PNG
        img, cached_path = render_card(c.data.model_dump(), image_path=image_path, dither=dither)
        
        # Actualizar image_path si se cacheó
        if cached_path and cached_path != c.data.image_path:
            c.data.image_path = cached_path
            store.update(card_id, c.data)
        
        # Convertir a TRI
        from .renderer import convert_to_tri
        tri_bytes = convert_to_tri(img)
        
        # Guardar render si es necesario
        out_png = RENDERS / f"{card_id}.png"
        img.save(str(out_png), "PNG")
        new_data = CardData.model_validate(c.data.model_dump())
        new_data.render_path = str(out_png)
        store.update(card_id, new_data)
        
        return Response(content=tri_bytes, media_type="application/octet-stream", headers={
            "Content-Disposition": f"attachment; filename=\"{card_id}.tri\""
        })
    except Exception as e:
        raise HTTPException(500, f"TRI render failed: {e}")