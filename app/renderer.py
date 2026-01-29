from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont, ImageOps
from typing import Tuple
import os
import requests
from io import BytesIO
import urllib.request
import tempfile
import hashlib
import struct
import numpy as np
from pathlib import Path

# Cache de fuentes en /tmp
FONT_CACHE_DIR = "/tmp/cartelas_fonts"
os.makedirs(FONT_CACHE_DIR, exist_ok=True)

# Cache de imágenes descargadas
BASE = Path(__file__).resolve().parent.parent
IMAGE_CACHE_DIR = BASE / "data" / "images"
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _get_cached_font(url: str, size: int, bold: bool) -> ImageFont.FreeTypeFont:
    """Descarga y cachea fuentes desde GitHub"""
    # Crear nombre único basado en URL
    font_hash = hashlib.md5(url.encode()).hexdigest()
    
    # Detectar extensión del archivo
    if url.endswith(".woff2"):
        ext = ".woff2"
    elif url.endswith(".ttf"):
        ext = ".ttf"
    else:
        ext = ".ttf"
    
    cache_path = os.path.join(FONT_CACHE_DIR, f"{font_hash}{ext}")
    
    # Si no está cacheado, descargar
    if not os.path.exists(cache_path):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            with open(cache_path, 'wb') as f:
                f.write(response.content)
            print(f"✓ Descargada fuente: {url}")
        except Exception as e:
            print(f"✗ Error descargando fuente: {e}")
            return None
    
    try:
        return ImageFont.truetype(cache_path, size=size)
    except Exception as e:
        print(f"✗ Error cargando fuente {cache_path}: {e}")
        return None

W, H = 480, 670

MARGIN = 28
TOP_BOX_SIZE = 50  # Cuadrado

IMAGE_BOX_H = 200

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Carga fuentes de GitHub (openmaptiles/fonts - confiable en Docker)"""
    # URLs raw de GitHub - totalmente confiables incluso en Docker
    base_url = "https://raw.githubusercontent.com/openmaptiles/fonts/master/roboto/"
    
    if bold:
        url = base_url + "Roboto-Bold.ttf"
    else:
        url = base_url + "Roboto-Regular.ttf"
    
    # Intentar cargar desde cache
    font = _get_cached_font(url, size, bold)
    if font:
        return font
    
    # Fallback: usar PIL default si falla la descarga
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()

def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def _paste_into_box(base: Image.Image, img: Image.Image, box: Tuple[int,int,int,int], mode: str = "contain", scale_factor: float = 1.0) -> int:
    """
    Pega una imagen en un box.
    Returns: altura real utilizada por la imagen
    """
    x1, y1, x2, y2 = box
    bw, bh = (x2 - x1), (y2 - y1)

    img = img.convert("RGB")
    iw, ih = img.size

    if mode == "cover":
        # escala para cubrir y recorta
        scale = max(bw / iw, bh / ih) * scale_factor
        nw, nh = int(iw * scale), int(ih * scale)
        resized = img.resize((nw, nh), Image.Resampling.NEAREST)
        cx, cy = nw // 2, nh // 2
        left = cx - bw // 2
        top = cy - bh // 2
        cropped = resized.crop((left, top, left + bw, top + bh))
        base.paste(cropped, (x1, y1))
        return bh  # Siempre usa toda la altura del box
    else:
        # contain - alinear arriba
        scale = min(bw / iw, bh / ih) * scale_factor
        nw, nh = int(iw * scale), int(ih * scale)
        resized = img.resize((nw, nh), Image.Resampling.NEAREST)
        px = x1 + (bw - nw)//2
        py = y1  # Alinear arriba en lugar de centrar
        base.paste(resized, (px, py))
        return nh  # Retornar altura real usada

def _load_image(image_path: str, title: str = "") -> tuple[Image.Image, str]:
    """
    Carga imagen desde URL o ruta local.
    Si es URL, la cachea en data/images con el slug del título.
    
    Args:
        image_path: URL o ruta local de la imagen
        title: Título para generar el slug del nombre de archivo
        
    Returns:
        (imagen, ruta_final) donde ruta_final es la ruta cacheada si es URL, o la original si es local
    """
    if image_path.startswith(("http://", "https://")):
        # Generar nombre de archivo desde título o hash de URL
        if title:
            # Usar título para el nombre
            from .utils import slugify
            slug = slugify(title)
        else:
            # Usar hash de la URL
            url_hash = hashlib.md5(image_path.encode()).hexdigest()[:12]
            slug = f"cached-{url_hash}"
        
        # Detectar extensión de la URL
        url_lower = image_path.lower()
        if url_lower.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.gif')):
            ext = Path(image_path).suffix
        else:
            ext = '.jpg'  # Default
        
        cache_path = IMAGE_CACHE_DIR / f"{slug}{ext}"
        
        # Si ya está cacheada, usarla
        if cache_path.exists():
            print(f"✓ Usando imagen cacheada: {cache_path.name}")
            return Image.open(cache_path), str(cache_path)
        
        # Descargar y cachear
        try:
            response = requests.get(image_path, timeout=10)
            response.raise_for_status()
            img_data = response.content
            
            # Guardar en cache
            cache_path.write_bytes(img_data)
            print(f"✓ Imagen descargada y cacheada: {cache_path.name}")
            
            return Image.open(BytesIO(img_data)), str(cache_path)
        except Exception as e:
            print(f"✗ Error descargando imagen: {e}")
            raise
    else:
        return Image.open(image_path), image_path

def _remove_white_background(img: Image.Image) -> Image.Image:
    """Elimina el fondo blanco de una imagen haciendo transparente"""
    # Asegurar RGBA para transparencia
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    
    # Obtener datos de píxeles
    data = list(img.getdata())
    new_data = []
    
    for pixel in data:
        r, g, b = pixel[0], pixel[1], pixel[2]
        alpha = pixel[3] if len(pixel) >= 4 else 255
        
        # Si el píxel es blanco o muy cercano (R>235, G>235, B>235)
        # hacerlo transparente
        if r > 235 and g > 235 and b > 235:
            new_data.append((255, 255, 255, 0))  # Transparente
        else:
            # Mantener píxel original con su alpha
            new_data.append((r, g, b, alpha))
    
    img.putdata(new_data)
    return img

def render_card(data: dict, image_path: str | None = None, dither: int = 0) -> tuple[Image.Image, str | None]:
    """
    Renderiza una cartela.
    dither: 0=sin dithering (gris), 1=suave, 2=fuerte
    
    Returns:
        (imagen_renderizada, ruta_imagen_cacheada)
    """
    img = Image.new("RGB", (W, H), (255, 255, 255))  # Blanco puro
    draw = ImageDraw.Draw(img)

    title_font_size = data.get("title_font_size", 52)
    f_title = _load_font(title_font_size, bold=True)  # Título grande y en negrita
    f_sub   = _load_font(28, bold=True)   # Subtítulo más grande (AÑO IMPORTANTE)
    f_sub_sm = _load_font(18, bold=False) # Subtítulo pequeño a la derecha
    f_bul   = _load_font(16, bold=False)
    f_piece = _load_font(50, bold=True)   # Número de pieza muy grande
    f_cap   = _load_font(13, bold=True)
    f_small = _load_font(12, bold=False)

    # Nº pieza (arriba derecha) - cuadrado
    pn = (data.get("piece_number") or "").strip()
    if pn:
        box_w = TOP_BOX_SIZE + (10 if len(pn) == 2 else 0)
        bx2 = W - MARGIN
        bx1 = bx2 - box_w
        by1 = MARGIN - 8  # Subir el número
        by2 = by1 + TOP_BOX_SIZE
        draw.rectangle([bx1, by1, bx2, by2], outline=(255,100,100), width=2, fill=(255,255,255))
        # Solo el número, sin "Nº"
        txt = pn
        tw = draw.textlength(txt, font=f_piece)
        tx = bx1 + (box_w - tw)//2
        ty = by1 + (TOP_BOX_SIZE - 55)//2  # Centrado vertical
        draw.text((tx, ty), txt, font=f_piece, fill=(20,20,20))

    x = MARGIN
    y = 10 #MARGIN + 8  # Más abajo para tener espacio arriba

    # Título (deja sitio si el nº pieza existe)
    title = (data.get("title") or "").strip().upper()
    if pn:
        max_title_w = W - 2*MARGIN - TOP_BOX_SIZE - 12
    else:
        max_title_w = W - 2*MARGIN

    # título puede ser largo: corta en 1-2 líneas
    t_lines = _wrap(draw, title, f_title, max_title_w)
    t_lines = t_lines[:2] if t_lines else [""]
    line_height = int(title_font_size * 0.92)  # altura de línea proporcional al tamaño
    for i, tl in enumerate(t_lines):
        draw.text((x, y), tl, font=f_title, fill=(20,20,20))
        y += line_height if i == 0 else int(line_height * 0.85)

    # AÑO prominente con fabricante pequeño alineado a la derecha
    year = (data.get("year") or " ")#.strip()
    manufacturer = (data.get("subtitle") or "").strip()  # subtitle ahora es fabricante
    if year:
        if year:
            draw.text((x, y), year, font=f_sub, fill=(20,20,20))  # Color muy oscuro
        if manufacturer:
            sw = draw.textlength(manufacturer, font=f_sub_sm)
            right_limit = W - MARGIN - (TOP_BOX_SIZE + 12 if pn else 0)
            sx = right_limit - sw
            draw.text((sx, y + 8), manufacturer, font=f_sub_sm, fill=(60,60,60))
        y += 40

    # regla separadora
    draw.rectangle([x, y, W - x, y + 2], fill=(255,100,100))  # Línea más oscura
    y += 18

    # caja imagen
    img_box = (x, y, W - x, y + IMAGE_BOX_H)
    cached_image_path = None

    if image_path:
        try:
            # Obtener título para cachear con slug
            title = (data.get("title") or "").strip()
            src, cached_image_path = _load_image(image_path, title)
            
            # Si tiene transparencia (RGBA), poner fondo blanco
            if src.mode in ('RGBA', 'LA') or (src.mode == 'P' and 'transparency' in src.info):
                # Crear fondo blanco
                background = Image.new('RGB', src.size, (255, 255, 255))
                # Convertir a RGBA si no lo es
                if src.mode != 'RGBA':
                    src = src.convert('RGBA')
                # Pegar imagen sobre fondo blanco usando alpha como máscara
                background.paste(src, mask=src.split()[3])  # Canal alpha
                src = background
            
            # look B/N tipo museo
            src = ImageOps.grayscale(src).convert("RGB")
            # Aplicar dithering según nivel
            if dither == 1:  # Dithering suave
                g = ImageOps.grayscale(src)
                # Posterize a 16 niveles (4 bits) antes de dithering
                g = ImageOps.posterize(g, 4)
                bw = g.convert("1")
                src = bw.convert("RGB")
            elif dither == 2:  # Dithering fuerte
                g = ImageOps.grayscale(src)
                bw = g.convert("1")  # Floyd–Steinberg por defecto
                src = bw.convert("RGB")
            
            # Obtener escala de imagen del data
            image_scale = float(data.get("image_scale", 1.0))
            actual_height = _paste_into_box(img, src, img_box, mode="contain", scale_factor=image_scale)
            # Ajustar y basado en la altura real de la imagen
            y += actual_height + 16
        except Exception as e:
            draw.text((x + 12, y + 10), f"ERROR: {str(e)[:30]}", font=f_sub, fill=(200,50,50))
            y += IMAGE_BOX_H + 16
    else:
        draw.text((x + 12, y + 10), "IMATGE", font=f_sub, fill=(140,140,140))
        y += IMAGE_BOX_H + 16

    # bullets
    bullets = data.get("bullets") or []
    bullets = [b.strip() for b in bullets if b.strip()]
    bullets = bullets[:6]

    max_text_w = W - 2*MARGIN - 18
    for b in bullets[:4]:
        draw.text((x, y), "•", font=f_bul, fill=(34,34,34))
        lines = _wrap(draw, b, f_bul, max_text_w)
        if not lines:
            y += 24
            continue
        draw.text((x + 18, y), lines[0], font=f_bul, fill=(34,34,34))
        y += 24
        for extra in lines[1:]:
            draw.text((x + 18, y), extra, font=f_bul, fill=(34,34,34))
            y += 24
        y += 6

    # ficha técnica
    tech = data.get("tech") or []
    tech = [t for t in tech if (t.get("label","").strip() and t.get("value","").strip())][:6]

    if tech:
        y += 6
        draw.text((x, y), "DATOS TÉCNICOS", font=f_cap, fill=(34,34,34))
        y += 18
        draw.rectangle([x, y, W - x, y + 2], fill=(255,175,175))
        y += 10

        label_w = 105
        for t in tech:
            lab = t["label"].strip()[:18]
            val = t["value"].strip()
            draw.text((x, y), f"{lab}:", font=f_small, fill=(90,90,90))
            val_lines = _wrap(draw, val, f_small, (W - 2*MARGIN - label_w))
            if not val_lines:
                y += 16
                continue
            draw.text((x + label_w, y), val_lines[0], font=f_small, fill=(34,34,34))
            y += 16
            for extra in val_lines[1:2]:
                draw.text((x + label_w, y), extra, font=f_small, fill=(34,34,34))
                y += 16
            y += 4

    return img, cached_image_path

def convert_to_tri(img: Image.Image) -> bytes:
    """Convierte imagen PNG a formato TRI (e-ink de 3 colores)"""
    TARGET_W, TARGET_H = W, H
    
    # Asegurar tamaño exacto y RGB
    if img.size != (TARGET_W, TARGET_H):
        img = img.resize((TARGET_W, TARGET_H), resample=Image.NEAREST)
    if img.mode != "RGB":
        img = img.convert("RGB")
    
    arr = np.array(img)
    
    r = arr[:, :, 0].astype(float)
    g = arr[:, :, 1].astype(float)
    b = arr[:, :, 2].astype(float)
    
    # Clasificación: blanco / negro / rojo
    red_mask = (r > 160) & (g < 120) & (b < 120)
    lum = (0.2126*r + 0.7152*g + 0.0722*b)
    black_mask = (lum < 128) & (~red_mask)
    white_mask = ~(red_mask | black_mask)
    
    # Empaquetado bit a bit (MSB first)
    w, h = TARGET_W, TARGET_H
    bytes_per_row = (w + 7) // 8
    
    black_plane = bytearray(bytes_per_row * h)
    red_plane = bytearray(bytes_per_row * h)
    
    for y in range(h):
        row_off = y * bytes_per_row
        for x in range(w):
            bit = 7 - (x % 8)
            idx = row_off + (x // 8)
            
            if black_mask[y, x]:
                black_plane[idx] |= (1 << bit)
            elif red_mask[y, x]:
                red_plane[idx] |= (1 << bit)
    
    # Construir archivo TRI
    output = BytesIO()
    output.write(b"TRI1")
    output.write(struct.pack("<H", w))
    output.write(struct.pack("<H", h))
    output.write(black_plane)
    output.write(red_plane)
    
    return output.getvalue()