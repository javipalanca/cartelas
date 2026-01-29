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

def ensure_dir(p: str | Path) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)