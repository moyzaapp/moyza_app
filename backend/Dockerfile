# Etapa 1: compilar el CSS de Tailwind con el binario standalone oficial (sin Node).
# Solo se copia el .css resultante a la imagen final. Ver TAILWIND_BUILD.md.
FROM debian:bookworm-slim AS css

# Misma versión que TAILWIND_VERSION en scripts/build_css.sh: cambiar las dos a la vez
ARG TAILWIND_VERSION=3.4.17
# La rellena BuildKit (amd64, arm64…); con el builder clásico viene vacía y se asume amd64
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN case "${TARGETARCH:-amd64}" in \
      amd64) asset=tailwindcss-linux-x64 ;; \
      arm64) asset=tailwindcss-linux-arm64 ;; \
      *) echo "arquitectura no soportada: ${TARGETARCH}" && exit 1 ;; \
    esac \
    && curl -fsSL --retry 3 -o /usr/local/bin/tailwindcss \
       "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/${asset}" \
    && chmod +x /usr/local/bin/tailwindcss

WORKDIR /src
COPY tailwind.config.js ./
COPY app ./app
RUN tailwindcss -c tailwind.config.js -i app/static/css/tailwind.src.css \
    -o /out/tailwind.css --minify


# Etapa 2: imagen de la app
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# CSS compilado en la etapa 1 (después de `COPY . .` para que no lo pise una copia local)
COPY --from=css /out/tailwind.css app/static/css/tailwind.css

# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app", "--access-logfile", "-", "--error-logfile", "-"]
