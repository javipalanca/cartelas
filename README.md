# Generador de cartelas (480×670)

## Instalación (uv)
```bash
cd carteles
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
# edita .env y pon OPENAI_API_KEY
uv run uvicorn app.main:app --reload --port 8080