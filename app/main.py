from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .models import CardData
from .storage import JsonStore
from .openai_client import suggest_card
from .renderer import render_card
from .utils import ensure_dir, safe_filename

# Cargar variables de entorno desde .env
BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")
DATA_DIR = BASE / "data"
UPLOADS = DATA_DIR / "uploads"
RENDERS = DATA_DIR / "renders"
DB_PATH = DATA_DIR / "cards.json"
WEB_DIR = BASE / "web"

ensure_dir(UPLOADS)
ensure_dir(RENDERS)

store = JsonStore(str(DB_PATH))

app = FastAPI(title="Carteles 480x670")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")

@app.get("/api/cards")
def list_cards(q: Optional[str] = None, piece_type: Optional[str] = None):
    cards = store.list_cards(q=q, piece_type=piece_type)
    # respuesta ligera
    return [{
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
    } for c in cards]

@app.get("/api/cards/{card_id}")
def get_card(card_id: str):
    c = store.get(card_id)
    if not c:
        raise HTTPException(404, "Card not found")
    return c.model_dump()

@app.post("/api/cards")
def create_card(payload: dict):
    # payload puede venir vacío
    data = CardData.model_validate(payload.get("data", payload) if payload else {})
    rec = store.create(data)
    return rec.model_dump()

@app.put("/api/cards/{card_id}")
def update_card(card_id: str, payload: dict):
    data = CardData.model_validate(payload.get("data", payload))
    rec = store.update(card_id, data)
    if not rec:
        raise HTTPException(404, "Card not found")
    return rec.model_dump()

@app.post("/api/cards/{card_id}/duplicate")
def duplicate_card(card_id: str):
    rec = store.duplicate(card_id)
    if not rec:
        raise HTTPException(404, "Card not found")
    return rec.model_dump()

@app.post("/api/suggest")
def api_suggest(payload: dict):
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
def api_preview(payload: dict):
    """Renderiza una cartela en tiempo real sin guardarla"""
    try:
        data_obj = payload.get("data", {})
        dither = payload.get("dither", 0)  # 0=sin dithering, 1=suave, 2=fuerte
        if isinstance(dither, bool):
            dither = 2 if dither else 0  # Compatibilidad con valores anteriores
        image_path = data_obj.get("image_path")
        
        # Render
        img = render_card(data_obj, image_path=image_path, dither=dither)
        
        # Devolver como respuesta directa sin guardar
        from io import BytesIO
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        
        return Response(content=buf.getvalue(), media_type="image/png")
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {e}")

@app.post("/api/cards/{card_id}/upload-image")
async def upload_image(card_id: str, image: UploadFile = File(...)):
    c = store.get(card_id)
    if not c:
        raise HTTPException(404, "Card not found")

    ext = Path(image.filename or "").suffix.lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"]:
        raise HTTPException(400, "Unsupported image format")

    fn = safe_filename(f"{card_id}{ext}")
    out = UPLOADS / fn
    content = await image.read()
    out.write_bytes(content)

    c.data.image_path = str(out)
    c.data.render_path = None
    updated = store.update(card_id, c.data)
    return {"ok": True, "image_path": updated.data.image_path}

@app.post("/api/cards/{card_id}/render")
async def api_render(
    card_id: str,
    data: str = Form(...),
    dither: int = Form(0),
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
    img = render_card(data_obj, image_path=image_path, dither=int(dither))

    out_png = RENDERS / f"{card_id}.png"
    img.save(out_png, format="PNG")

    # Persistimos data + rutas
    new_data = CardData.model_validate(data_obj)
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
def render_tri(card_id: str, payload: dict):
    c = store.get(card_id)
    if not c:
        raise HTTPException(404, "Card not found")

    try:
        dither = int(payload.get("dither", 0))
        image_path = c.data.image_path
        
        # Renderizar imagen PNG
        img = render_card(c.data.model_dump(), image_path=image_path, dither=dither)
        
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