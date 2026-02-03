
from __future__ import annotations
import numpy as np
from PIL import Image

import numpy as np
from PIL import Image

def remove_background_floodfill(
    img_pil: Image.Image,
    bg_luma_thresh: int = 30,   # 0..255, "qué tan oscuro consideras fondo"
    feather: int = 0,           # 0 = borde duro, 1..3 suaviza un poco el borde
    make_transparent: bool = False
) -> Image.Image:
    """
    Quita fondo oscuro conectado al borde (flood-fill).
    Devuelve imagen con fondo blanco o con alpha=0 si make_transparent=True.
    """

    rgb = np.array(img_pil.convert("RGB"), dtype=np.uint8)
    h, w = rgb.shape[:2]

    # Luma rápida en sRGB (suficiente para segmentar fondo oscuro)
    luma = (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]).astype(np.float32)

    # Candidatos a fondo: muy oscuros
    bg_candidate = luma <= bg_luma_thresh

    # Flood-fill (4-conectividad) desde bordes SOLO a través de bg_candidate
    bg = np.zeros((h, w), dtype=bool)

    stack = []
    # Añadir borde
    for x in range(w):
        if bg_candidate[0, x]: stack.append((0, x))
        if bg_candidate[h-1, x]: stack.append((h-1, x))
    for y in range(h):
        if bg_candidate[y, 0]: stack.append((y, 0))
        if bg_candidate[y, w-1]: stack.append((y, w-1))

    while stack:
        y, x = stack.pop()
        if bg[y, x]:
            continue
        if not bg_candidate[y, x]:
            continue
        bg[y, x] = True

        if y > 0: stack.append((y-1, x))
        if y+1 < h: stack.append((y+1, x))
        if x > 0: stack.append((y, x-1))
        if x+1 < w: stack.append((y, x+1))

    # (Opcional) Feather simple para suavizar borde: dilatación ligera del bg
    if feather > 0:
        bg2 = bg.copy()
        for _ in range(feather):
            b = bg2
            bg2 = b | np.roll(b,1,0) | np.roll(b,-1,0) | np.roll(b,1,1) | np.roll(b,-1,1)
        bg = bg2

    if make_transparent:
        rgba = np.dstack([rgb, (~bg).astype(np.uint8)*255])
        return Image.fromarray(rgba, mode="RGBA")
    else:
        out = rgb.copy()
        out[bg] = 255  # fondo a blanco puro
        return Image.fromarray(out, mode="RGB")



# ---------- Color / tone helpers ----------

def srgb_to_linear(u: np.ndarray) -> np.ndarray:
    """u in [0,1] sRGB -> linear [0,1]"""
    a = 0.055
    return np.where(u <= 0.04045, u / 12.92, ((u + a) / (1 + a)) ** 2.4)

def linear_to_srgb(u: np.ndarray) -> np.ndarray:
    """u in [0,1] linear -> sRGB [0,1]"""
    a = 0.055
    return np.where(u <= 0.0031308, 12.92 * u, (1 + a) * (u ** (1/2.4)) - a)

def rgb_to_luma_linear(img: np.ndarray) -> np.ndarray:
    """
    img uint8 RGB -> luma in linear space [0,1]
    Using Rec.709 coefficients on linear RGB.
    """
    u = img.astype(np.float32) / 255.0
    lin = srgb_to_linear(u)
    # Rec.709 / sRGB primaries luma
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]

def apply_contrast_curve(x: np.ndarray, contrast: float = 1.0, mid: float = 0.5) -> np.ndarray:
    """
    Simple contrast around mid in linear space.
    contrast=1 no change. >1 increases contrast, <1 reduces.
    """
    return np.clip((x - mid) * contrast + mid, 0.0, 1.0)

# ---------- Ordered dither (Bayer) ----------

_BAYER_8 = (1/64.0) * np.array([
    [0, 48, 12, 60,  3, 51, 15, 63],
    [32, 16, 44, 28, 35, 19, 47, 31],
    [8, 56,  4, 52, 11, 59,  7, 55],
    [40, 24, 36, 20, 43, 27, 39, 23],
    [2, 50, 14, 62,  1, 49, 13, 61],
    [34, 18, 46, 30, 33, 17, 45, 29],
    [10, 58,  6, 54,  9, 57,  5, 53],
    [42, 26, 38, 22, 41, 25, 37, 21],
], dtype=np.float32)

def dither_bayer(lin: np.ndarray, threshold_0_255: int) -> np.ndarray:
    """
    lin: [H,W] linear luma [0,1]
    threshold acts like global offset: 0..255 maps to 0..1.
    """
    h, w = lin.shape
    t = np.clip(threshold_0_255 / 255.0, 0.0, 1.0)
    # Tile Bayer matrix
    b = np.tile(_BAYER_8, (h // 8 + 1, w // 8 + 1))[:h, :w]
    # Compare with shifted threshold: effectively controls overall density
    out = (lin > (b * 0.85 + (t - 0.5) + 0.5)).astype(np.uint8) * 255
    return out

# ---------- Error diffusion kernels ----------

def dither_floyd_steinberg(lin: np.ndarray, threshold_0_255: int, serpentine: bool = True) -> np.ndarray:
    """
    Floyd–Steinberg on linear luma.
    """
    t = np.clip(threshold_0_255 / 255.0, 0.0, 1.0)
    a = lin.astype(np.float32).copy()
    h, w = a.shape
    out = np.zeros((h, w), dtype=np.uint8)

    for y in range(h):
        if serpentine and (y % 2 == 1):
            xs = range(w-1, -1, -1)
            dir = -1
        else:
            xs = range(w)
            dir = 1

        for x in xs:
            old = a[y, x]
            new = 1.0 if old >= t else 0.0
            out[y, x] = 255 if new > 0 else 0
            err = old - new

            # Distribute error
            x1 = x + dir
            if 0 <= x1 < w:
                a[y, x1] += err * (7/16)

            y1 = y + 1
            if y1 < h:
                # below-left, below, below-right depend on direction
                if dir == 1:
                    if x - 1 >= 0:
                        a[y1, x-1] += err * (3/16)
                    a[y1, x] += err * (5/16)
                    if x + 1 < w:
                        a[y1, x+1] += err * (1/16)
                else:
                    if x + 1 < w:
                        a[y1, x+1] += err * (3/16)
                    a[y1, x] += err * (5/16)
                    if x - 1 >= 0:
                        a[y1, x-1] += err * (1/16)

    return out

def dither_atkinson(lin: np.ndarray, threshold_0_255: int, serpentine: bool = True) -> np.ndarray:
    """
    Atkinson diffusion on linear luma.
    Kernel (normalized by 1/8):
      x  1  1
      1  1  1
         1
    """
    t = np.clip(threshold_0_255 / 255.0, 0.0, 1.0)
    a = lin.astype(np.float32).copy()
    h, w = a.shape
    out = np.zeros((h, w), dtype=np.uint8)

    for y in range(h):
        if serpentine and (y % 2 == 1):
            xs = range(w-1, -1, -1)
            dir = -1
        else:
            xs = range(w)
            dir = 1

        for x in xs:
            old = a[y, x]
            new = 1.0 if old >= t else 0.0
            out[y, x] = 255 if new > 0 else 0
            err = (old - new) / 8.0

            # positions relative to scan direction
            def add(xx, yy):
                if 0 <= xx < w and 0 <= yy < h:
                    a[yy, xx] += err

            add(x + dir, y)
            add(x + 2*dir, y)
            add(x - dir, y + 1)
            add(x,       y + 1)
            add(x + dir, y + 1)
            add(x,       y + 2)

    return out

# ---------- Main API ----------

def dither_image_pil(
    img_pil: Image.Image,
    method: str = "floydsteinberg",
    threshold: int = 128,
    contrast: float = 1.0,
    serpentine: bool = True,
    out_mode_1bit: bool = False,
) -> Image.Image:
    """
    method: 'atkinson' | 'floydsteinberg' | 'bayer' | 'none'
    threshold: 0..255 (like your JS mapping)
    contrast: applied in linear space before dithering (1.0 = none)
    """
    method = method.lower()
    threshold = int(np.clip(threshold, 0, 255))

    # Convert input to linear luma [0,1]
    if img_pil.mode in ("RGB", "RGBA"):
        rgb = np.array(img_pil.convert("RGB"), dtype=np.uint8)
        lin = rgb_to_luma_linear(rgb)
    else:
        # Treat as grayscale in sRGB; convert to linear
        g = np.array(img_pil.convert("L"), dtype=np.uint8).astype(np.float32) / 255.0
        lin = srgb_to_linear(g)

    lin = apply_contrast_curve(lin, contrast=contrast, mid=0.5)

    if method == "none":
        t = threshold / 255.0
        out = (lin >= t).astype(np.uint8) * 255
    elif method == "bayer":
        out = dither_bayer(lin, threshold)
    elif method == "atkinson":
        out = dither_atkinson(lin, threshold, serpentine=serpentine)
    elif method in ("floyd", "floydsteinberg", "fs"):
        out = dither_floyd_steinberg(lin, threshold, serpentine=serpentine)
    else:
        raise ValueError(f"Unknown method: {method}")

    out_img = Image.fromarray(out, mode="L")
    if out_mode_1bit:
        # True 1-bit (good for e-ink pipelines)
        out_img = out_img.convert("1")
    return out_img

def ditherea(im, method="atkinson", threshold=140, contrast=1.10, serpentine=True, out_mode_1bit=False):
    im_nobg = remove_background_floodfill(
    im,
    bg_luma_thresh=40,   # prueba 30..70
    feather=1,
    make_transparent=False
    )

    out = dither_image_pil(im_nobg, method=method, threshold=threshold, contrast=contrast, serpentine=serpentine, out_mode_1bit=out_mode_1bit)

    return out

# ---------- Example usage ----------
if __name__ == "__main__":
    im = Image.open("img.png")

    im_nobg = remove_background_floodfill(
    im,
    bg_luma_thresh=40,   # prueba 30..70
    feather=1,
    make_transparent=False
    )

    out = dither_image_pil(im_nobg, method="atkinson", threshold=140, contrast=1.10, serpentine=True, out_mode_1bit=False)
    out.save("output2.png")
