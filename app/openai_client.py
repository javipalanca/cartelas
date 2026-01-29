from __future__ import annotations
import os
import json
from typing import Any, Dict, List

from openai import OpenAI

PIECE_TYPE_GUIDE: Dict[str, List[str]] = {
    "computer": ["CPU", "RAM", "Almacenamiento", "Gráficos", "Bus"],
    "console": ["CPU", "RAM/VRAM", "Soporte (cartucho/disco)", "Año (aprox.)"],
    "peripheral": ["Interfaz", "Característica clave", "Compatibilidad", "Consumo/otros"],
    "software": ["Plataforma", "Año (aprox.)", "Uso/Género", "Requisitos"],
    "other": ["Dato 1", "Dato 2", "Dato 3", "Dato 4"],
}

def suggest_card(name_query: str, piece_type: str, piece_number: str = "") -> Dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no está configurada")

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    base_url = os.environ.get("BASE_URL", None)
    
    # Si hay BASE_URL, úsala; de lo contrario, usa el servidor por defecto de OpenAI
    if base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
    else:
        client = OpenAI(api_key=api_key)

    tech_labels = PIECE_TYPE_GUIDE.get(piece_type, PIECE_TYPE_GUIDE["other"])

    schema = {
        "type": "object",
        "properties": {
            "piece_number": {"type": "string"},
            "piece_type": {"type": "string"},
            "name_query": {"type": "string"},
            "title": {"type": "string"},
            "year": {"type": "string"},
            "subtitle": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6},
            "tech": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
                    "required": ["label", "value"]
                },
                "minItems": 3,
                "maxItems": 6
            },
            "notes": {"type": "string"}
        },
        "required": ["piece_number", "piece_type", "name_query", "title", "year", "subtitle", "bullets", "tech"]
    }

    prompt = f"""
Eres curador técnico de un museo de informática. Genera una cartela divulgativa breve y fiable.

Pieza (consulta del usuario): "{name_query}"
Tipo de pieza: "{piece_type}"

Reglas:
- No inventes datos. Si no estás seguro, usa rangos o expresiones tipo "segons model" / "aprox.".
- Evita cifras ultra-específicas si no se conoce el modelo exacto.
- year: año de lanzamiento o aproximación (ej: "1977", "1980s", "1995-1998"). SIEMPRE incluye el año.
- bullets: cortos, claros, máx ~80 caracteres cada uno.
- tech: 4–6 líneas, prioriza estas etiquetas si aplica: {tech_labels}.
- Idioma: castellano (si te falta dato, no rellenes con fantasía).
- "notes" es interno (no se imprime): pon ahí dudas o supuestos.

Devuelve SOLO el JSON validando el schema.
"""

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "cartela", "schema": schema}
        },
    )
    return json.loads(resp.choices[0].message.content)