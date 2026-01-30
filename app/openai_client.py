from __future__ import annotations
import os
import json
from typing import Any, Dict, List

import requests
from urllib.parse import quote
from openai import OpenAI

PIECE_TYPE_GUIDE: Dict[str, List[str]] = {
    "computer": ["CPU", "RAM", "Almacenamiento", "Gráficos", "Bus"],
    "console": ["CPU", "RAM/VRAM", "Soporte (cartucho/disco)", "Año (aprox.)"],
    "peripheral": ["Interfaz", "Característica clave", "Compatibilidad", "Consumo/otros"],
    "software": ["Plataforma", "Año (aprox.)", "Uso/Género", "Requisitos"],
    "other": ["Dato 1", "Dato 2", "Dato 3", "Dato 4"],
}

def _fetch_wikipedia_context(query: str) -> str:
    """Busca contexto en Wikipedia (EN) y devuelve un extracto útil."""
    if not query:
        return ""

    session = requests.Session()
    session.headers.update({
        "User-Agent": "cartelas/0.1 (https://github.com/javipalanca/cartelas)"
    })

    try:
        search_resp = session.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 5,
                "srenablerewrites": 1,
                "srprop": "",
                "format": "json",
            },
            timeout=10,
        )
        search_resp.raise_for_status()
        data = search_resp.json()
        results = data.get("query", {}).get("search", [])
        if not results:
            return ""

        for result in results:
            title = result.get("title")
            if not title:
                continue

            # Obtener artículo completo con más contenido
            article_resp = session.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "titles": title,
                    "prop": "extracts",
                    "explaintext": 1,
                    "exsectionformat": "plain",
                    "format": "json",
                },
                timeout=10,
            )
            if not article_resp.ok:
                continue

            article_data = article_resp.json()
            pages = article_data.get("query", {}).get("pages", {})
            if not pages:
                continue

            page = next(iter(pages.values()), {})
            if "missing" in page:
                continue

            extract = page.get("extract", "")
            if not extract:
                continue

            # Limitar 5000 caracteres aprox (2-3 párrafos)
            max_len = 5000
            if len(extract) > max_len:
                # Cortar en el último punto dentro del límite
                truncated = extract[:max_len]
                last_period = truncated.rfind(".")
                if last_period > max_len * 0.7:  # Si el punto está en los últimos 30%
                    extract = truncated[:last_period + 1]
                else:
                    extract = truncated.rstrip() + "..."
            
            # Remover líneas que parecen referencias o markup
            lines = extract.split("\n")
            cleaned_lines = [l for l in lines if l.strip() and not l.startswith("==")]
            extract = "\n".join(cleaned_lines)

            return f"{title}\n{extract}"

        return ""
    except Exception:
        return ""

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

    wiki_context = _fetch_wikipedia_context(name_query)
    wiki_block = f"\nContexto (Wikipedia EN):\n{wiki_context}\n" if wiki_context else "\nContexto (Wikipedia EN): (no encontrado)\n"
    print("Bloque de contexto Wikipedia:", wiki_block)

    prompt = f"""
Eres curador técnico de un museo de informática. Tu tarea es generar una cartela divulgativa **completa, detallada y confiable** para la siguiente pieza.

PIEZA A DOCUMENTAR:
- Consulta del usuario: "{name_query}"
- Tipo de pieza: "{piece_type}"

{wiki_block}

INSTRUCCIONES DETALLADAS:

1. **title** (Título de la pieza):
   - Nombre completo y modelo específico (ej: "Apple II", "IBM PC 5150", "Commodore 64")
   - Máx 100 caracteres

2. **year** (Año de lanzamiento):
   - OBLIGATORIO. Siempre incluye un año o rango (ej: "1977", "1980-1982", "finales 1990s")
   - Si es aproximado, usa "aprox. 1985" o rangos

3. **subtitle** (Fabricante/Origen):
   - El nombre del FABRICANTE reconocido (ej: "Apple Computer", "IBM", "Commodore International")
   - Usa nombres comerciales establecidos

4. **bullets** (Características destacadas - 3-6 líneas):
   - Una característica importante por línea
   - Cada una máx ~80 caracteres
   - Lenguaje divulgativo, no técnico
   - Ejemplos: 
     * "Primer ordenador de escritorio con interfaz gráfica"
     * "Ampliable con cartuchos de terceros"
     * "Revolucionó los videojuegos en arcades"

5. **tech** (Especificaciones técnicas - 3-6 etiquetas):
   - Estructura: {{"label": "CPU", "value": "Intel 8080"}}
   - Prioriza estas categorías según el tipo: {tech_labels}
   - Sé específico y verifiable

6. **notes** (Notas internas - NO se muestra):
   - Dudas, supuestos, fuentes consultadas
   - Ej: "Asumiendo modelo base", "Según Wikipedia EN"

RESTRICCIONES CRÍTICAS:
- **NO inventes datos**. Si no conoces algo concreto, usa rangos o "aprox."
- **Evita cifras exactas** si no estás seguro del modelo específico
- **Idioma**: responde SIEMPRE en castellano
- **Devuelve EXACTAMENTE el JSON** validando el schema proporcionado
- **NO resumas**. Proporciona contenido COMPLETO en cada campo

EJEMPLO DE RESPUESTA VÁLIDA:
{{
  "piece_number": "",
  "piece_type": "computer",
  "name_query": "Apple II",
  "title": "Apple II",
  "year": "1977",
  "subtitle": "Apple Computer, Inc.",
  "bullets": [
    "Primer ordenador personal completo vendido comercialmente",
    "Incluyó teclado integrado y fuente de alimentación interna",
    "Revolucionó los videojuegos domésticos con títulos como Breakout",
    "Expandible mediante slots de expansión"
  ],
  "tech": [
    {{"label": "CPU", "value": "MOS Technology 6502 @ 1 MHz"}},
    {{"label": "RAM", "value": "4 KB - 64 KB"}},
    {{"label": "Almacenamiento", "value": "Casete de audio o unidad de disco 5.25\\\""}},
    {{"label": "Gráficos", "value": "Resolución 280x192, 16 colores"}},
    {{"label": "Conexiones", "value": "Joystick, cassette, monitor"}}
  ],
  "notes": "Modelo original de 1977. Especificaciones de versión base."
}}

Procede a generar la cartela COMPLETA y DETALLADA.
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