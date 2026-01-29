from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import CardRecord, CardData
from .utils import now_iso, new_id, ensure_dir

class JsonStore:
    """
    Persistencia en un único fichero JSON:
    data/cards.json
    """
    def __init__(self, path: str):
        self.path = Path(path)
        ensure_dir(self.path.parent)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"version": 1, "cards": []})

    def _read(self) -> Dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, obj: Dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    def list_cards(self, q: Optional[str] = None, piece_type: Optional[str] = None, skip: int = 0, limit: int = 1000) -> tuple:
        with self._lock:
            db = self._read()
            cards = [CardRecord.model_validate(c) for c in db.get("cards", [])]

        if q:
            qq = q.lower().strip()
            def match(cr: CardRecord) -> bool:
                d = cr.data
                hay = " ".join([
                    d.piece_number or "",
                    d.cabinet_number or "",
                    d.name_query or "",
                    d.title or "",
                    d.subtitle or "",
                    d.year or "",
                    " ".join(d.bullets or [])
                ]).lower()
                return qq in hay
            cards = [c for c in cards if match(c)]

        if piece_type and piece_type != "all":
            cards = [c for c in cards if c.data.piece_type == piece_type]

        # orden por updated_at desc
        cards.sort(key=lambda c: c.updated_at, reverse=True)
        
        # Aplicar paginación
        total = len(cards)
        paginated = cards[skip:skip + limit]
        return paginated, total

    def get(self, card_id: str) -> Optional[CardRecord]:
        with self._lock:
            db = self._read()
            for c in db.get("cards", []):
                if c.get("id") == card_id:
                    return CardRecord.model_validate(c)
        return None

    def create(self, data: CardData) -> CardRecord:
        rec = CardRecord(
            id=new_id(),
            created_at=now_iso(),
            updated_at=now_iso(),
            data=data
        )
        with self._lock:
            db = self._read()
            db.setdefault("cards", []).append(rec.model_dump())
            self._write(db)
        return rec

    def update(self, card_id: str, data: CardData) -> Optional[CardRecord]:
        with self._lock:
            db = self._read()
            cards = db.get("cards", [])
            for i, c in enumerate(cards):
                if c.get("id") == card_id:
                    c["updated_at"] = now_iso()
                    c["data"] = data.model_dump()
                    cards[i] = c
                    db["cards"] = cards
                    self._write(db)
                    return CardRecord.model_validate(c)
        return None

    def duplicate(self, card_id: str) -> Optional[CardRecord]:
        src = self.get(card_id)
        if not src:
            return None
        # copia data pero vacía piece_number para evitar confusiones
        d = src.data.model_copy(deep=True)
        d.piece_number = ""
        d.render_path = None
        # si duplicas, lo normal es mantener la imagen; tú decides:
        # aquí la mantenemos (si existe) para comodidad
        rec = self.create(d)
        return rec

    def delete(self, card_id: str) -> bool:
        with self._lock:
            db = self._read()
            cards = db.get("cards", [])
            for i, c in enumerate(cards):
                if c.get("id") == card_id:
                    cards.pop(i)
                    db["cards"] = cards
                    self._write(db)
                    return True
        return False