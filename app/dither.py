import argparse
import os
import struct
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps, ImageEnhance

import matplotlib.pyplot as plt


MAGIC = b"TRI1"


@dataclass
class Params:
    width: int
    height: int

    # Preprocess
    contrast: float
    sharpness: float
    gamma: float

    # Binarization
    method: str           # "fixed" | "adaptive"
    threshold: int        # 0..255 (for fixed)
    adaptive_window: int  # odd int, e.g., 31
    adaptive_k: float     # e.g., 0.20

    # Dithering
    dither: str           # "none" | "fs" | "atkinson"

    # Red handling
    red_mode: str         # "auto" | "none"
    red_r_min: int
    red_g_max: int
    red_b_max: int


def clamp_uint8(a: np.ndarray) -> np.ndarray:
    return np.clip(a, 0, 255).astype(np.uint8)


def apply_gamma(gray: np.ndarray, gamma: float) -> np.ndarray:
    if gamma == 1.0:
        return gray
    g = gray.astype(np.float32) / 255.0
    g = np.power(g, gamma)
    return clamp_uint8(g * 255.0)


def to_grayscale(img: Image.Image, p: Params) -> np.ndarray:
    g = ImageOps.grayscale(img)
    # Contrast / sharpness in PIL
    if p.contrast != 1.0:
        g = ImageEnhance.Contrast(g).enhance(p.contrast)
    if p.sharpness != 1.0:
        g = ImageEnhance.Sharpness(g).enhance(p.sharpness)
    arr = np.array(g, dtype=np.uint8)
    arr = apply_gamma(arr, p.gamma)
    return arr


def integral_image(a: np.ndarray) -> np.ndarray:
    # padded integral image for fast box sums
    ii = np.cumsum(np.cumsum(a, axis=0), axis=1)
    ii = np.pad(ii, ((1, 0), (1, 0)), mode="constant", constant_values=0)
    return ii


def box_sum(ii: np.ndarray, r0: int, c0: int, r1: int, c1: int) -> np.ndarray:
    # sum over [r0,r1) x [c0,c1)
    return ii[r1, c1] - ii[r0, c1] - ii[r1, c0] + ii[r0, c0]


def adaptive_sauvola(gray: np.ndarray, window: int, k: float) -> np.ndarray:
    """
    Sauvola thresholding:
      T = m * (1 + k*(s/R - 1)), R ~ 128
    """
    if window % 2 == 0:
        window += 1
    r = window // 2
    h, w = gray.shape

    g = gray.astype(np.float32)
    ii = integral_image(g)
    ii2 = integral_image(g * g)

    # build coordinate grids
    ys = np.arange(h)
    xs = np.arange(w)
    y0 = np.clip(ys - r, 0, h)
    y1 = np.clip(ys + r + 1, 0, h)
    x0 = np.clip(xs - r, 0, w)
    x1 = np.clip(xs + r + 1, 0, w)

    # compute mean and std with separable broadcasting
    # sums for each row/col window using ii slicing:
    # We'll compute using loops over one axis to keep it simple & reliable.
    mean = np.zeros((h, w), dtype=np.float32)
    var = np.zeros((h, w), dtype=np.float32)

    for y in range(h):
        r0, r1 = y0[y], y1[y]
        # sums over x windows for this row band
        # we compute per x using ii; still O(hw) but ok for 480x670
        for x in range(w):
            c0, c1 = x0[x], x1[x]
            area = (r1 - r0) * (c1 - c0)
            s = box_sum(ii, r0, c0, r1, c1)
            s2 = box_sum(ii2, r0, c0, r1, c1)
            m = s / area
            v = (s2 / area) - (m * m)
            if v < 0:
                v = 0.0
            mean[y, x] = m
            var[y, x] = v

    std = np.sqrt(var)
    R = 128.0
    T = mean * (1.0 + k * ((std / R) - 1.0))
    T = np.clip(T, 0, 255)

    # black if gray < T
    return (gray.astype(np.float32) < T)


def fixed_threshold(gray: np.ndarray, t: int) -> np.ndarray:
    return gray < t


def detect_text_regions(gray: np.ndarray) -> np.ndarray:
    """
    Detecta regiones de TEXTO renderizado (no fotografías).
    Usa detección de bordes para identificar texto con características nítidas.
    Retorna máscara booleana: True = es texto (no aplicar dithering)
    """
    from scipy import ndimage
    from scipy.ndimage import sobel
    
    # 1. Detectar píxeles muy oscuros o muy claros (candidatos a texto)
    is_very_dark = gray < 100
    is_very_light = gray > 200
    extreme_values = is_very_dark | is_very_light
    
    # 2. Calcular gradientes (bordes) usando Sobel
    sx = sobel(gray.astype(np.float32), axis=1)
    sy = sobel(gray.astype(np.float32), axis=0)
    edge_magnitude = np.sqrt(sx**2 + sy**2)
    
    # 3. Texto tiene bordes MUY definidos (gradiente alto)
    # Normalizar edge_magnitude
    if edge_magnitude.max() > 0:
        edge_magnitude = edge_magnitude / edge_magnitude.max()
    
    strong_edges = edge_magnitude > 0.3  # Bordes fuertes
    
    # 4. Texto = píxeles extremos + bordes fuertes
    # Esto excluye fotos con gradientes suaves
    text_candidates = extreme_values & strong_edges
    
    # 5. Expansión morfológica pequeña (1 iteración)
    # Solo para conectar caracteres, no para expandir mucho
    struct = ndimage.generate_binary_structure(2, 1)  # Conectividad 4
    text_expanded = ndimage.binary_dilation(text_candidates, structure=struct, iterations=1)
    
    return text_expanded


def dither_fs(gray: np.ndarray, text_mask: np.ndarray = None) -> np.ndarray:
    """
    Floyd–Steinberg dithering con protección de texto: returns bool mask (True=black)
    Si text_mask es proporcionado, no aplica dithering en esas regiones (usa umbral simple).
    """
    a = gray.astype(np.float32).copy()
    h, w = a.shape
    
    # Si no hay máscara de texto, crear una vacía
    if text_mask is None:
        text_mask = np.zeros((h, w), dtype=bool)
    
    for y in range(h):
        for x in range(w):
            old = a[y, x]
            
            # Si es texto, usar umbral binario directo (sin difusión de error)
            if text_mask[y, x]:
                new = 0.0 if old < 128 else 255.0
                a[y, x] = new
                # NO difundir error en regiones de texto
                continue
            
            # Para imágenes: aplicar dithering normal
            new = 0.0 if old < 128 else 255.0
            err = old - new
            a[y, x] = new
            if x + 1 < w:
                a[y, x + 1] += err * 7 / 16
            if y + 1 < h:
                if x > 0:
                    a[y + 1, x - 1] += err * 3 / 16
                a[y + 1, x] += err * 5 / 16
                if x + 1 < w:
                    a[y + 1, x + 1] += err * 1 / 16
    return a < 128


def dither_atkinson(gray: np.ndarray, text_mask: np.ndarray = None) -> np.ndarray:
    """
    Atkinson dithering con protección de texto: returns bool mask (True=black)
    Si text_mask es proporcionado, no aplica dithering en esas regiones (usa umbral simple).
    """
    a = gray.astype(np.float32).copy()
    h, w = a.shape
    
    # Si no hay máscara de texto, crear una vacía
    if text_mask is None:
        text_mask = np.zeros((h, w), dtype=bool)
    
    for y in range(h):
        for x in range(w):
            old = a[y, x]
            
            # Si es texto, usar umbral binario directo (sin difusión de error)
            if text_mask[y, x]:
                new = 0.0 if old < 128 else 255.0
                a[y, x] = new
                # NO difundir error en regiones de texto
                continue
            
            # Para imágenes: aplicar dithering normal
            new = 0.0 if old < 128 else 255.0
            err = (old - new) / 8.0
            a[y, x] = new
            # distribute to neighbors
            for dx, dy in [(1,0), (2,0), (-1,1), (0,1), (1,1), (0,2)]:
                xx = x + dx
                yy = y + dy
                if 0 <= xx < w and 0 <= yy < h:
                    a[yy, xx] += err
    return a < 128


def detect_red(rgb: np.ndarray, p: Params) -> np.ndarray:
    """
    Simple red detection (for tricolor panels):
      red if R high and G/B low enough.
    """
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    return (r >= p.red_r_min) & (g <= p.red_g_max) & (b <= p.red_b_max)


def pack_1bpp(mask: np.ndarray) -> bytes:
    """
    mask: HxW bool; True=1 (black/red pixel)
    pack MSB-first per byte.
    """
    h, w = mask.shape
    bpr = (w + 7) // 8
    out = np.zeros((h, bpr), dtype=np.uint8)
    for y in range(h):
        row = mask[y]
        for x in range(w):
            if row[x]:
                out[y, x // 8] |= (1 << (7 - (x % 8)))
    return out.tobytes()


def unpack_1bpp(buf: bytes, w: int, h: int) -> np.ndarray:
    bpr = (w + 7) // 8
    a = np.frombuffer(buf, dtype=np.uint8).reshape((h, bpr))
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            out[y, x] = (a[y, x // 8] >> (7 - (x % 8))) & 1
    return out


def convert_image(img_path: str, p: Params):
    img = Image.open(img_path).convert("RGB")
    
    # NO usar fit() que recorta - en su lugar, resize preservando aspect ratio
    # Esto evita pérdida de contenido y mantiene mejor calidad
    orig_w, orig_h = img.size
    target_w, target_h = p.width, p.height
    
    # Si la imagen ya es exactamente del tamaño correcto, no redimensionar
    if (orig_w, orig_h) != (target_w, target_h):
        # Calcular escala para que quepa sin crop
        scale = min(target_w / orig_w, target_h / orig_h)
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        
        # Resize con LANCZOS de alta calidad
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        # Pegar en canvas blanco centrado (sin crop)
        canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        paste_x = (target_w - new_w) // 2
        paste_y = (target_h - new_h) // 2
        canvas.paste(img, (paste_x, paste_y))
        img = canvas

    rgb = np.array(img, dtype=np.uint8)
    red_mask = detect_red(rgb, p) if p.red_mode == "auto" else np.zeros((p.height, p.width), dtype=bool)

    gray = to_grayscale(img, p)

    # If a pixel is red, we prefer not to also mark it black.
    # (You can change this if your panel wants black+red combined.)
    gray_no_red = gray.copy()
    gray_no_red[red_mask] = 255  # force white in BW plane where red is set

    # PROTECCIÓN DE TEXTO: detectar regiones de texto para evitar procesamiento agresivo
    text_mask = detect_text_regions(gray_no_red)

    if p.dither == "fs":
        black_mask = dither_fs(gray_no_red, text_mask=text_mask)
    elif p.dither == "atkinson":
        black_mask = dither_atkinson(gray_no_red, text_mask=text_mask)
    else:
        # Sin dithering: aplicar método base pero respetando texto
        if p.method == "adaptive":
            image_mask = adaptive_sauvola(gray_no_red, p.adaptive_window, p.adaptive_k)
        else:
            image_mask = fixed_threshold(gray_no_red, p.threshold)
        
        # Para regiones de texto: usar umbral binario simple (128)
        text_binary = gray_no_red < 128
        
        # Combinar: usar umbral simple en texto, método adaptativo en imágenes
        black_mask = np.where(text_mask, text_binary, image_mask)

    # Planes
    black_plane = pack_1bpp(black_mask)
    red_plane   = pack_1bpp(red_mask)

    return img, gray, black_mask, red_mask, black_plane, red_plane

def write_tri(out_path: str, w: int, h: int, black_plane: bytes, red_plane: bytes):
    with open(out_path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<H", w))
        f.write(struct.pack("<H", h))
        f.write(black_plane)
        f.write(red_plane)


def read_tri(tri_path: str):
    with open(tri_path, "rb") as f:
        magic = f.read(4)
        if magic != MAGIC:
            raise ValueError("Bad TRI magic")
        w = struct.unpack("<H", f.read(2))[0]
        h = struct.unpack("<H", f.read(2))[0]
        bpr = (w + 7)//8
        plane_size = bpr * h
        black = f.read(plane_size)
        red = f.read(plane_size)
    return w, h, black, red


def render_preview(w: int, h: int, black_mask: np.ndarray, red_mask: np.ndarray):
    """
    Returns RGB preview image (numpy) showing e-paper tricolor mapping:
      white background, black pixels, red pixels.
    """
    out = np.ones((h, w, 3), dtype=np.uint8) * 255
    out[black_mask] = np.array([0, 0, 0], dtype=np.uint8)
    out[red_mask]   = np.array([220, 0, 0], dtype=np.uint8)
    return out


def show_viewer(preview_rgb: np.ndarray, title: str = "TRI preview", zoom: int = 1):
    h, w, _ = preview_rgb.shape
    plt.figure(figsize=(w/100*zoom, h/100*zoom))
    plt.imshow(preview_rgb)
    plt.axis("off")
    plt.title(title)
    plt.show()


def main():
    ap = argparse.ArgumentParser(description="PNG/BMP -> TRI converter + preview viewer")
    ap.add_argument("input", help="Input image (png/bmp/jpg) OR .tri when using --view-tri")
    ap.add_argument("--out", help="Output .tri path (default: same name .tri)")
    ap.add_argument("--w", type=int, default=None, help="Width (default: use input image width)")
    ap.add_argument("--h", type=int, default=None, help="Height (default: use input image height)")

    # Preprocess knobs
    ap.add_argument("--contrast", type=float, default=1.35)
    ap.add_argument("--sharpness", type=float, default=1.5)
    ap.add_argument("--gamma", type=float, default=1.0)

    # Binarization knobs
    ap.add_argument("--method", choices=["fixed", "adaptive"], default="adaptive")
    ap.add_argument("--threshold", type=int, default=128)
    ap.add_argument("--adaptive-window", type=int, default=31)
    ap.add_argument("--adaptive-k", type=float, default=0.20)

    # Dither
    ap.add_argument("--dither", choices=["none", "fs", "atkinson"], default="fs")

    # Red
    ap.add_argument("--red-mode", choices=["auto", "none"], default="none")
    ap.add_argument("--red-r-min", type=int, default=160)
    ap.add_argument("--red-g-max", type=int, default=120)
    ap.add_argument("--red-b-max", type=int, default=120)

    # Viewer
    ap.add_argument("--preview", action="store_true", help="Show preview window after conversion")
    ap.add_argument("--zoom", type=int, default=2, help="Viewer zoom factor")
    ap.add_argument("--view-tri", action="store_true", help="Open and preview an existing .tri file")

    args = ap.parse_args()

    if args.view_tri:
        w, h, black_plane, red_plane = read_tri(args.input)
        black_mask = unpack_1bpp(black_plane, w, h)
        red_mask = unpack_1bpp(red_plane, w, h)
        preview = render_preview(w, h, black_mask, red_mask)
        show_viewer(preview, title=os.path.basename(args.input), zoom=args.zoom)
        return

    # Si no se especifican dimensiones, usar las de la imagen original
    if args.w is None or args.h is None:
        temp_img = Image.open(args.input)
        orig_w, orig_h = temp_img.size
        if args.w is None:
            args.w = orig_w
        if args.h is None:
            args.h = orig_h
        print(f"Usando resolución original: {args.w}x{args.h}")
    
    p = Params(
        width=args.w, height=args.h,
        contrast=args.contrast, sharpness=args.sharpness, gamma=args.gamma,
        method=args.method, threshold=args.threshold,
        adaptive_window=args.adaptive_window, adaptive_k=args.adaptive_k,
        dither=args.dither,
        red_mode=args.red_mode,
        red_r_min=args.red_r_min, red_g_max=args.red_g_max, red_b_max=args.red_b_max,
    )

    img, gray, black_mask, red_mask, black_plane, red_plane = convert_image(args.input, p)

    out = args.out
    if not out:
        base, _ = os.path.splitext(args.input)
        out = base + ".tri"

    write_tri(out, p.width, p.height, black_plane, red_plane)
    print(f"OK -> {out}  (planes: {len(black_plane)}B + {len(red_plane)}B)")

    if args.preview:
        preview = render_preview(p.width, p.height, black_mask, red_mask)
        show_viewer(preview, title=os.path.basename(out), zoom=args.zoom)


import numpy as np
from PIL import Image, ImageOps

def bayer_dithering(img):
    # 1. Cargar imagen y pasar a Escala de Grises
    img = img.convert("L")  # Convertir a escala de grises
    
    # Convertimos la imagen a un array de números (matriz de píxeles)
    img_array = np.array(img, dtype=float)
    
    # 2. Definir la Matriz de Bayer 4x4
    # Esta matriz define el "patrón" o la textura que verás.
    # Los números indican el umbral de brillo para encender el píxel.
    bayer_matrix = np.array([
        [ 0,  8,  2, 10],
        [12,  4, 14,  6],
        [ 3, 11,  1,  9],
        [15,  7, 13,  5]
    ])
    
    # Normalizamos la matriz:
    # La matriz original va de 0 a 15. La imagen va de 0 a 255.
    # Multiplicamos para escalar los valores.
    bayer_matrix = bayer_matrix * (255.0 / 16.0)
    
    # 3. "Enbaldosar" la matriz (Tiling)
    # Repetimos la matriz 4x4 hasta cubrir toda la imagen
    h, w = img_array.shape
    # Creamos una rejilla del tamaño de la imagen repitiendo la matriz pequeña
    rep_h = int(np.ceil(h / 4))
    rep_w = int(np.ceil(w / 4))
    
    # Creamos la máscara de umbral completa
    threshold_map = np.tile(bayer_matrix, (rep_h, rep_w))
    # Recortamos por si sobra un poco en los bordes
    threshold_map = threshold_map[:h, :w]
    
    # 4. Aplicar la comparación (El Dithering en sí)
    # Si el píxel de la imagen es más brillante que el valor de la matriz -> Blanco (255)
    # Si no -> Negro (0)
    result_array = np.where(img_array > threshold_map, 255, 0)
    
    # 5. Guardar imagen
    result_img = Image.fromarray(result_array.astype('uint8'))
    return result_img 


if __name__ == "__main__":
    main()