FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema para Pillow y fuentes
RUN apt-get update && apt-get install -y \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos de dependencias
COPY pyproject.toml .

# Instalar uv y dependencias
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache-dir -e .

# Copiar el código de la aplicación
COPY app ./app
COPY web ./web
COPY data ./data

# Crear directorios necesarios
RUN mkdir -p /tmp/cartelas_fonts

# Exponer puerto
EXPOSE 8000

# Variables de entorno por defecto
ENV OPENAI_API_KEY=""
ENV OPENAI_MODEL="gpt-4o-mini"
ENV BASE_URL=""

# Comando para iniciar la aplicación
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
