# Generador de cartelas (480×670)

## Instalación (uv)
```bash
cd cartelas
uv sync
cp .env.example .env
# edita .env y pon OPENAI_API_KEY
uv run uvicorn app.main:app --reload --port 8080