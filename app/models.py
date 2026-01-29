from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Literal, Optional

PieceType = Literal["computer", "console", "peripheral", "software", "other"]

class TechLine(BaseModel):
    label: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=96)

class CardData(BaseModel):
    piece_number: str = Field(default="", max_length=48)
    piece_type: PieceType = "other"
    name_query: str = Field(default="", max_length=160)
    cabinet_number: str = Field(default="", max_length=20)  # Número de vitrina (interno del museo)

    title: str = Field(default="", max_length=80)
    subtitle: str = Field(default="", max_length=110)
    year: str = Field(default="", max_length=20)  # Año de la pieza (prominente)

    bullets: List[str] = Field(default_factory=list, max_length=6)
    tech: List[TechLine] = Field(default_factory=list)

    # notas internas (no se imprimen)
    notes: str = Field(default="", max_length=600)

    # rutas
    image_path: Optional[str] = None
    render_path: Optional[str] = None

class CardRecord(BaseModel):
    id: str
    created_at: str
    updated_at: str
    data: CardData