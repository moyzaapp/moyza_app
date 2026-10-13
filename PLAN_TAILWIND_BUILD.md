# Plan: compilar Tailwind a un .css (dejar de usar el Play CDN en el navegador)

Fecha: 2026-10-14. Rama: `57-cambios-de-visitas-compradores-y-otros`.

## Contexto y objetivo

`base.html` carga `/static/js/tailwind.js` (407 KB): es el **Play CDN** de
Tailwind 3 servido en local. Compila el CSS **en el navegador** en cada carga,
recorriendo todo el HTML. En páginas grandes tarda segundos antes de pintar con
estilos, y Tailwind lo desaconseja para producción.

Objetivo: generar **una vez**, al construir la imagen Docker, un
`app/static/css/tailwind.css` minificado con solo las clases que usa la app, y
cargarlo con `<link>`. Todas las páginas cargan más rápido. Sin Node en la
imagen final.

## Decisiones cerradas con el usuario (no cambiar)

- **Build en Docker multi-etapa** con el **binario standalone oficial** de
  Tailwind (no se añade Node a la imagen final). `docker compose build` lo hace
  solo; no hay nada que recordar al desplegar.
- **Respaldo automático**: si `app/static/css/tailwind.css` no existe,
  `base.html` carga el `tailwind.js` de siempre y la app registra un `WARNING`
  al arrancar. Motivo: `docker-compose.local.yml` monta `./backend:/app`, así
  que en local el CSS compilado de la imagen queda tapado por la carpeta del
  host. Con el respaldo, desarrollar sin compilar sigue funcionando (más lento)
  y producción nunca se queda sin estilos.
- **Script local** `backend/scripts/build_css.sh` (con `--watch`) para generar el
  CSS en la máquina de desarrollo con el mismo binario y la misma versión.
- El CSS compilado **no se sube a git** (`.gitignore`). `tailwind.js` se queda
  en el repo para el respaldo.
- **Versión**: Tailwind **3.4.x** (la última 3.x; no 4.x, que cambia la
  configuración y rompería clases). Fijar la versión exacta en un solo sitio
  (`ARG TAILWIND_VERSION` en el Dockerfile y la misma constante en el script).

## Archivos que toca este plan (y solo estos)

- `backend/Dockerfile` — etapa `css` + copia del resultado.
- `backend/.dockerignore` — nuevo.
- `backend/tailwind.config.js` — nuevo.
- `backend/app/static/css/tailwind.src.css` — nuevo (entrada: `@tailwind base; components; utilities;`).
- `backend/scripts/build_css.sh` — nuevo (ejecutable).
- `backend/.gitignore` (o el de la raíz, el que exista) — ignorar
  `app/static/css/tailwind.css` y `.cache/`.
- `backend/app/web/template_env.py` — global de plantilla con disponibilidad y
  versión del CSS (ver abajo).
- `backend/app/web/templates/base.html` — `<link>` con respaldo.
- `backend/app/main.py` — solo si hace falta el aviso de arranque (puede ir en
  `template_env.py` al importar).
- `TAILWIND_BUILD.md` en la raíz — guía corta de uso y despliegue.
- `.claude/skills/moyza-ui-ux-pro/SKILL.md` — actualizar la frase del stack
  ("Tailwind 3 cargado en local como Play CDN… No hay build de CSS") y añadir
  en "Cómo trabajar" que las clases nuevas escritas desde Python o JS deben
  estar en archivos cubiertos por `content` del `tailwind.config.js`.
- Este archivo (marcar estado al terminar).

**Prohibido tocar**: `app/web/routes/alerts.py`, `app/web/templates/alerts/*`,
`components/ui_macros.html`, `tests/`. Otro agente trabaja en paralelo sobre
esos archivos (paginación). No hacer commits.

## Diseño

### `tailwind.config.js`

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/web/templates/**/*.html",
    "./app/static/js/**/*.js",   // clases en strings de JS (alert-duplicates.js, ui.js…)
    "./app/**/*.py",             // clases devueltas desde Python (constants.py stage_badge_color…)
  ],
  theme: { extend: {} },
  plugins: [],
};
```

Excluir `tailwind.js` del escaneo no hace falta (no contiene clases útiles,
pero sí muchas cadenas: comprobar que no infla el CSS; si lo hace, afinar el
glob a `./app/static/js/{ui,alert-*}.js` o excluirlo con un patrón negativo).

Hoy no hay `tailwind.config` inline en `base.html` ni `@apply`, ni bloques
`type="text/tailwindcss"`, ni `theme()` en plantillas (verificado por grep).
Si al buscar aparece alguno, portarlo al config/CSS fuente.

### Dockerfile

```dockerfile
# Etapa 1: compilar el CSS con el binario standalone (sin Node)
FROM debian:bookworm-slim AS css
ARG TAILWIND_VERSION=3.4.17
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in \
      amd64) asset=tailwindcss-linux-x64 ;; \
      arm64) asset=tailwindcss-linux-arm64 ;; \
      *) echo "arquitectura no soportada: $TARGETARCH" && exit 1 ;; \
    esac \
    && curl -fsSL -o /usr/local/bin/tailwindcss \
       "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/${asset}" \
    && chmod +x /usr/local/bin/tailwindcss
WORKDIR /src
COPY tailwind.config.js ./
COPY app ./app
RUN tailwindcss -c tailwind.config.js -i app/static/css/tailwind.src.css \
    -o /out/tailwind.css --minify

# Etapa 2: la imagen actual, sin cambios salvo la copia del CSS
FROM python:3.12-slim
… (igual que hoy) …
COPY . .
COPY --from=css /out/tailwind.css app/static/css/tailwind.css
```

Si `TARGETARCH` viene vacío (builder clásico sin BuildKit), tomar `amd64` por
defecto con `${TARGETARCH:-amd64}`. Requiere acceso a GitHub en el servidor al
construir; dejarlo escrito en `TAILWIND_BUILD.md`.

`.dockerignore` mínimo: `.git`, `**/__pycache__`, `*.pyc`, `.cache`,
`.pytest_cache`, `tests`. **No** excluir `.env` (hoy va dentro de la imagen; no
cambiar ese comportamiento en este plan).

### `scripts/build_css.sh`

- `TAILWIND_VERSION` igual que en el Dockerfile.
- Detecta SO/arquitectura (`linux-x64`, `linux-arm64`, `macos-arm64`,
  `macos-x64`) y descarga el binario a `backend/.cache/tailwindcss-<version>`
  si no existe.
- Ejecuta la compilación con los mismos argumentos que el Dockerfile.
  `--watch` pasa el flag al binario. Sin `--minify` en modo watch (más legible
  al depurar), con `--minify` en build normal.
- Se puede lanzar desde cualquier directorio (hacer `cd` al directorio del
  script). Mensaje claro si falla la descarga.

### `base.html` y `template_env.py`

En `template_env.py`, al importar:

```python
_TAILWIND_CSS = Path("app/static/css/tailwind.css")
tailwind_css_version = int(_TAILWIND_CSS.stat().st_mtime) if _TAILWIND_CSS.exists() else None
if tailwind_css_version is None:
    logger.warning("tailwind.css no encontrado: se usa el compilador en navegador (lento). Ejecuta scripts/build_css.sh")
templates.env.globals["tailwind_css_version"] = tailwind_css_version
```

En `base.html`:

```html
{% if tailwind_css_version %}
<link rel="stylesheet" href="/static/css/tailwind.css?v={{ tailwind_css_version }}">
{% else %}
<script src="/static/js/tailwind.js"></script>
{% endif %}
```

El `?v=` evita que el navegador use un CSS viejo tras un despliegue. Con
gunicorn y 4 workers el valor se calcula por proceso al arrancar: es el mismo
para todos porque leen el mismo archivo.

Ojo: el `<link>` debe ir **antes** del `<style>` inline de `base.html` para que
las reglas propias sigan ganando a las de Tailwind, como hoy.

## Verificación

1. Build local: `bash backend/scripts/build_css.sh` genera
   `backend/app/static/css/tailwind.css`. Anotar tamaño (esperable 60–150 KB
   minificado).
2. Comprobar que el CSS contiene clases representativas de cada fuente:
   - de plantillas: `sm:col-span-2`, `rounded-2xl`, `h-dvh` o la variante
     `dvh` que use el modal, `max-h-\[92vh\]`;
   - de Python: cada clase devuelta por `FollowUpActionType.stage_badge_color`
     y por `app/web/utils` si devuelve clases;
   - de JS: `bg-amber-600`, `hover:bg-amber-700` (`alert-duplicates.js`),
     y las que use `ui.js`.
   Hacerlo con un script pequeño que extraiga todas las clases de los
   archivos cubiertos por `content` y compruebe que aparecen en el CSS
   (escapadas como las escribe Tailwind). Reportar las que falten y por qué.
3. Renderizar `base.html` con y sin `tailwind_css_version` y comprobar el
   `<link>` / `<script>` según el caso.
4. `python -c "import app.main"` arranca (con y sin el CSS presente: en el
   segundo caso debe salir el WARNING).
5. `docker build` **no** se puede ejecutar aquí (no hay Docker en este WSL).
   Validar el Dockerfile por lectura: etapa `css` autocontenida, rutas
   relativas correctas respecto a `context: ./backend`, `COPY --from` después
   de `COPY . .`. Dejar en `TAILWIND_BUILD.md` el comando exacto para probarlo
   en el servidor: `docker compose build backend && docker compose up -d backend`
   y cómo comprobar que la respuesta de `/` trae el `<link>` y no el `<script>`.
6. `python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates`
   sin avisos nuevos.

## Entrega

Sin commits. Informe final con: archivos tocados, tamaño del CSS, resultado de la
comprobación de clases (número de clases encontradas / faltantes y cuáles),
cómo probarlo en el servidor, y cualquier duda o deuda. Actualizar "Estado".

## Estado

- [x] `tailwind.config.js` + CSS fuente
- [x] `scripts/build_css.sh` y build local verificado (Tailwind 3.4.17, CSS minificado ~42,7 KB)
- [x] Dockerfile multi-etapa + `.dockerignore` + `.gitignore` (Dockerfile validado por lectura; sin Docker aquí)
- [x] `template_env.py` + `base.html` con respaldo
- [x] Comprobación de clases (602 clases Tailwind usadas, 0 faltantes)
- [x] Documentación (`TAILWIND_BUILD.md`, SKILL.md)

Notas de la ejecución (2026-10-13):

- `content` excluye `tailwind.js` y `chart.umd.js` con patrones negativos: con ellos el
  CSS pasaba de ~43 KB a ~61 KB por clases que la app no usa.
- `--watch` usa `--watch=always`: con `--watch` a secas Tailwind 3 sale sin compilar
  cuando stdin está cerrado.
- Pendiente fuera del alcance de este plan: `auth/login.html` (plantilla independiente,
  `/` y `/login`) sigue cargando `tailwind.js`; `references/tokens.md` y
  `references/audit-2026-10.md` del skill aún mencionan el Play CDN.
