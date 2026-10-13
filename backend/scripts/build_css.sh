#!/usr/bin/env bash
# Compila Tailwind a app/static/css/tailwind.css con el binario standalone
# oficial (sin Node). Es el mismo binario y la misma versión que usa la etapa
# `css` del Dockerfile.
#
# Uso (desde cualquier directorio):
#   bash backend/scripts/build_css.sh           # build minificado
#   bash backend/scripts/build_css.sh --watch   # recompila al guardar (sin minificar)
#
# El binario se descarga una vez a backend/.cache/ (ignorado en git).
# Más detalle en TAILWIND_BUILD.md (raíz del repo).

set -euo pipefail

# Misma versión que `ARG TAILWIND_VERSION` en backend/Dockerfile: cambiar las dos a la vez
TAILWIND_VERSION="3.4.17"

CONFIG="tailwind.config.js"
INPUT="app/static/css/tailwind.src.css"
OUTPUT="app/static/css/tailwind.css"

usage() {
    sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
}

WATCH=0
for arg in "$@"; do
    case "$arg" in
        --watch) WATCH=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Opción desconocida: $arg" >&2; usage >&2; exit 2 ;;
    esac
done

# Trabajar siempre desde backend/ (las rutas del config son relativas a él)
cd "$(dirname "$0")/.."

# Detectar SO y arquitectura -> nombre del asset en GitHub Releases
case "$(uname -s)" in
    Linux)  os="linux" ;;
    Darwin) os="macos" ;;
    *) echo "Sistema operativo no soportado: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
    x86_64|amd64)  arch="x64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) echo "Arquitectura no soportada: $(uname -m)" >&2; exit 1 ;;
esac
asset="tailwindcss-${os}-${arch}"

BIN=".cache/tailwindcss-${TAILWIND_VERSION}"
if [ ! -x "$BIN" ]; then
    url="https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/${asset}"
    echo "Descargando Tailwind ${TAILWIND_VERSION} (${asset})..."
    mkdir -p .cache
    # Se descarga a un .part y se renombra al final: una descarga cortada no deja un binario roto
    if ! curl -fSL --retry 3 -o "${BIN}.part" "$url"; then
        rm -f "${BIN}.part"
        echo "" >&2
        echo "ERROR: no se pudo descargar el binario de Tailwind desde:" >&2
        echo "  $url" >&2
        echo "Comprueba la conexión a GitHub (o un proxy) y vuelve a intentarlo." >&2
        echo "Mientras tanto la app sigue funcionando con el compilador en navegador (tailwind.js)." >&2
        exit 1
    fi
    chmod +x "${BIN}.part"
    mv "${BIN}.part" "$BIN"
fi

if [ "$WATCH" -eq 1 ]; then
    echo "Modo watch: recompila $OUTPUT al guardar (Ctrl+C para salir)."
    # --watch=always: con --watch a secas Tailwind 3 sale en cuanto se cierra stdin
    # (p. ej. lanzado en segundo plano o desde otro script) sin compilar nada
    exec "$BIN" -c "$CONFIG" -i "$INPUT" -o "$OUTPUT" --watch=always
fi

"$BIN" -c "$CONFIG" -i "$INPUT" -o "$OUTPUT" --minify
echo "Generado $OUTPUT ($(wc -c < "$OUTPUT" | tr -d ' ') bytes)."
echo "Reinicia la app para que lo use (la versión del CSS se lee al arrancar)."
