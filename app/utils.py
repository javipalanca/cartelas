from __future__ import annotations
import os
import re
import time
import uuid
from pathlib import Path

def now_iso() -> str:
    # ISO simple y estable
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

def new_id() -> str:
    return uuid.uuid4().hex[:12]

def safe_filename(s: str) -> str:
    s = s.strip()
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:120] or "file"

def slugify(text: str) -> str:
    """Convierte texto a slug para nombres de archivo"""
    text = text.lower().strip()
    # Convertir caracteres especiales
    text = re.sub(r'[áàäâ]', 'a', text)
    text = re.sub(r'[éèëê]', 'e', text)
    text = re.sub(r'[íìïî]', 'i', text)
    text = re.sub(r'[óòöô]', 'o', text)
    text = re.sub(r'[úùüû]', 'u', text)
    text = re.sub(r'[ñ]', 'n', text)
    # Eliminar caracteres no alfanuméricos excepto espacios y guiones
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    # Reemplazar espacios con guiones
    text = re.sub(r'[\s]+', '-', text)
    # Eliminar guiones múltiples
    text = re.sub(r'-+', '-', text)
    # Reemplazar guiones por _
    text = text.replace('-', '_')
    # Limitar longitud
    return text[:80] or "unnamed"

def ensure_dir(p: str | Path) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)