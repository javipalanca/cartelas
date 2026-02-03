import argparse
import os
import struct

import numpy as np
from PIL import Image, ImageOps, ImageEnhance
import matplotlib.pyplot as plt

MAGIC = b"TRI1"


# ----------------------------
# Bitpack / unpack
# ----------------------------
def pack_1bpp(mask: np.ndarray) -> bytes:
    """mask: HxW bool, True=1. Pack MSB-first."""
    h, w = mask.shape
    bpr = (w + 7) // 8
    out = np.zeros((h, bpr), dtype=np.uint8)
    for y in range(h):
        row = mask[y]
        for x in range(w):
            if row[x]:
                out[y, x // 8] |= (1 << (7 - (x % 8)))
    return out.tobytes()


def unpack_1bpp(data: bytes, w: int, h: int) -> np.ndarray:
    """Unpack MSB-first 1bpp bytes into HxW bool mask (True=1)."""
    bpr = (w + 7) // 8
    expected = bpr * h
    if len(data) < expected:
        raise ValueError("TRI plane data too short")
    arr = np.frombuffer(data[:expected], dtype=np.uint8).reshape((h, bpr))
    mask = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            byte = arr[y, x // 8]
            bit = (byte >> (7 - (x % 8))) & 1
            mask[y, x] = bool(bit)
    return mask


def write_tri(path: str, w: int, h: int, black_plane: bytes, red_plane: bytes):
    with open(path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<H", w))
        f.write(struct.pack("<H", h))
        f.write(black_plane)
        f.write(red_plane)


def read_tri(path: str):
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != MAGIC:
            raise ValueError("Bad TRI magic")
        w = struct.unpack("<H", f.read(2))[0]
        h = struct.unpack("<H", f.read(2))[0]
        bpr = (w + 7) // 8
        plane_size = bpr * h
        black = f.read(plane_size)
        red = f.read(plane_size)
    return w, h, black, red


# ----------------------------
# Dithering (foto)
# ----------------------------
def dither_atkinson(gray_u8: np.ndarray) -> np.ndarray:
    """Atkinson dithering. Returns bool mask (True=black)."""
    a = gray_u8.astype(np.float32).copy()
    h, w = a.shape
    for y in range(h):
        for x in range(w):
            old = a[y, x]
            new = 0.0 if old < 128 else 255.0
            err = (old - new) / 8.0
            a[y, x] = new
            for dx, dy in [(1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2)]:
                xx = x + dx
                yy = y + dy
                if 0 <= xx < w and 0 <= yy < h:
                    a[yy, xx] += err
    return a < 128


def dither_fs(gray_u8: np.ndarray) -> np.ndarray:
    """Floyd–Steinberg dithering. Returns bool mask (True=black)."""
    a = gray_u8.astype(np.float32).copy()
    h, w = a.shape
    for y in range(h):
        for x in range(w):
            old = a[y, x]
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


# ----------------------------
# Texto nítido (sin dither)
# ----------------------------
def text_threshold_clean(gray_u8: np.ndarray, thresh: int, clean_passes: int = 1) -> np.ndarray:
    """
    Umbral fijo + limpieza rápida:
    - primero binariza
    - luego elimina "píxeles aislados" (salt&pepper) con un filtro 3x3 simple
    """
    mask = gray_u8 < thresh

    # Limpieza: quita puntos aislados (muy útil para texto)
    # Regla: un pixel negro aislado (con pocos vecinos negros) se vuelve blanco
    for _ in range(clean_passes):
        m = mask
        # vecinos 8-conectados (sumamos True como 1)
        n = (
            m[:-2, :-2].astype(np.int16) + m[:-2, 1:-1].astype(np.int16) + m[:-2, 2:].astype(np.int16) +
            m[1:-1, :-2].astype(np.int16) +                         m[1:-1, 2:].astype(np.int16) +
            m[2:, :-2].astype(np.int16) +  m[2:, 1:-1].astype(np.int16) +  m[2:, 2:].astype(np.int16)
        )
        core = m[1:-1, 1:-1].copy()
        # si un pixel negro tiene <=1 vecino negro, lo quitamos
        core = np.where((core == 1) & (n <= 1), False, core)
        mask = m.copy()
        mask[1:-1, 1:-1] = core

    return mask


# ----------------------------
# Rojo (UI roja: líneas, logos, cajas)
# ----------------------------
def detect_red(rgb: np.ndarray, r_min: int, g_max: int, b_max: int) -> np.ndarray:
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    return (r >= r_min) & (g <= g_max) & (b <= b_max)


# ----------------------------
# Preview
# ----------------------------
def render_preview(black: np.ndarray, red: np.ndarray) -> np.ndarray:
    h, w = black.shape
    out = np.ones((h, w, 3), dtype=np.uint8) * 255
    out[black] = [0, 0, 0]
    out[red] = [220, 0, 0]
    return out


def show_preview(preview_rgb: np.ndarray, title: str, zoom: float = 2.0):
    h, w, _ = preview_rgb.shape
    plt.figure(figsize=(w / 120 * zoom, h / 120 * zoom))
    plt.imshow(preview_rgb)
    plt.axis("off")
    plt.title(title)
    plt.show()


# ----------------------------
# Conversión principal
# ----------------------------
def convert_to_tri(
    input_path: str,
    out_path: str,
    W: int,
    H: int,
    photo_y0: int,
    photo_y1: int,
    dither: str,
    contrast: float,
    sharpness: float,
    text_thresh: int,
    text_clean: int,
    red_mode: str,
    red_rmin: int,
    red_gmax: int,
    red_bmax: int,
):
    # Load & fit
    img = Image.open(input_path).convert("RGB")
    img = ImageOps.fit(img, (W, H), method=Image.Resampling.LANCZOS)
    rgb = np.array(img, dtype=np.uint8)

    # Red plane
    if red_mode == "auto":
        red = detect_red(rgb, red_rmin, red_gmax, red_bmax)
    else:
        red = np.zeros((H, W), dtype=bool)

    # Grayscale preprocess (para BW plane)
    g = ImageOps.grayscale(img)
    if contrast != 1.0:
        g = ImageEnhance.Contrast(g).enhance(contrast)
    if sharpness != 1.0:
        g = ImageEnhance.Sharpness(g).enhance(sharpness)
    gray = np.array(g, dtype=np.uint8)

    # Evitar “negro encima del rojo”
    gray_no_red = gray.copy()
    gray_no_red[red] = 255

    # Clamp photo region
    py0 = max(0, min(H, photo_y0))
    py1 = max(0, min(H, photo_y1))
    if py1 < py0:
        py0, py1 = py1, py0

    black = np.zeros((H, W), dtype=bool)

    # FOTO: dithering (como te funciona bien)
    photo = gray_no_red[py0:py1, :]
    if dither == "atkinson":
        blk_photo = dither_atkinson(photo)
    elif dither == "fs":
        blk_photo = dither_fs(photo)
    else:
        blk_photo = photo < 128
    black[py0:py1, :] = blk_photo

    # TEXTO: sin dithering, umbral fijo + limpieza
    top = gray_no_red[:py0, :]
    bot = gray_no_red[py1:, :]
    black[:py0, :] = text_threshold_clean(top, text_thresh, clean_passes=text_clean)
    black[py1:, :] = text_threshold_clean(bot, text_thresh, clean_passes=text_clean)

    # Export TRI
    black_plane = pack_1bpp(black)
    red_plane = pack_1bpp(red)
    write_tri(out_path, W, H, black_plane, red_plane)

    return black, red


def main():
    ap = argparse.ArgumentParser(description="Museum-quality TRI converter (crisp text + dithered photo)")
    ap.add_argument("input", help="Input image (png/bmp/jpg) or .tri when using --view-tri")
    ap.add_argument("--out", default=None, help="Output .tri (default: same name .tri)")

    ap.add_argument("--w", type=int, default=480)
    ap.add_argument("--h", type=int, default=670)

    ap.add_argument("--photo-y0", type=int, default=140, help="Photo region start Y (inclusive)")
    ap.add_argument("--photo-y1", type=int, default=380, help="Photo region end Y (exclusive)")

    ap.add_argument("--dither", 
                    choices=["none", "sierra_lite", "burkes", "floyd_steinberg", "sierra", "atkinson", "stucki", "jarvis_judice_ninke"],
                    default="atkinson",
                    help="Dithering algorithm")

    ap.add_argument("--contrast", type=float, default=1.30)
    ap.add_argument("--sharpness", type=float, default=1.40)

    ap.add_argument("--text-thresh", type=int, default=160, help="Text threshold (higher -> more black)")
    ap.add_argument("--text-clean", type=int, default=2, help="Text cleanup passes (0..3)")

    ap.add_argument("--red-mode", choices=["auto", "none"], default="auto")
    ap.add_argument("--red-rmin", type=int, default=160)
    ap.add_argument("--red-gmax", type=int, default=120)
    ap.add_argument("--red-bmax", type=int, default=120)

    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--view-tri", action="store_true", help="Open and preview an existing .tri file")

    args = ap.parse_args()

    if args.view_tri:
        w, h, black_plane, red_plane = read_tri(args.input)
        black = unpack_1bpp(black_plane, w, h)
        red = unpack_1bpp(red_plane, w, h)
        prev = render_preview(black, red)
        show_preview(prev, title=os.path.basename(args.input), zoom=args.zoom)
        return

    out = args.out
    if not out:
        base, _ = os.path.splitext(args.input)
        out = base + ".tri"

    black, red = convert_to_tri(
        input_path=args.input,
        out_path=out,
        W=args.w,
        H=args.h,
        photo_y0=args.photo_y0,
        photo_y1=args.photo_y1,
        dither=args.dither,
        contrast=args.contrast,
        sharpness=args.sharpness,
        text_thresh=args.text_thresh,
        text_clean=args.text_clean,
        red_mode=args.red_mode,
        red_rmin=args.red_rmin,
        red_gmax=args.red_gmax,
        red_bmax=args.red_bmax,
    )

    print(f"OK -> {out}")

    if args.preview:
        prev = render_preview(black, red)
        show_preview(prev, title=os.path.basename(out), zoom=args.zoom)


if __name__ == "__main__":
    main()