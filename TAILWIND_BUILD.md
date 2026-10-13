# Tailwind compilado (CSS en el build)

La app ya no necesita compilar Tailwind en el navegador: el CSS se genera **una vez**
con el binario standalone oficial de Tailwind **3.4.17** (sin Node) y `base.html` lo
carga con un `<link>`.

| Pieza | Qué hace |
|---|---|
| `backend/tailwind.config.js` | Qué archivos se escanean (`content`): plantillas, JS de `app/static/js` (menos `tailwind.js` y `chart.umd.js`) y todo `app/**/*.py`. |
| `backend/app/static/css/tailwind.src.css` | Entrada (`@tailwind base/components/utilities`). |
| `backend/app/static/css/tailwind.css` | Salida compilada y minificada (~43 KB). **No se sube a git.** |
| `backend/scripts/build_css.sh` | Compila en local (descarga el binario a `backend/.cache/`). |
| `backend/Dockerfile` | Etapa `css` que compila y copia el resultado a la imagen. |
| `app/web/template_env.py` | Global `tailwind_css_version` (mtime del CSS, o `None` si no existe). |

## Respaldo automático

Si `app/static/css/tailwind.css` **no existe** al arrancar la app:

- `base.html` carga el `/static/js/tailwind.js` de siempre (compilador en navegador, más lento);
- se registra un aviso al arrancar:
  `tailwind.css no encontrado (...): se usa el compilador en navegador (lento). Ejecuta scripts/build_css.sh`.

La comprobación se hace **una vez por proceso al arrancar**. Si se crea o se borra el
CSS con la app en marcha, hay que reiniciarla.

## Desplegar en el servidor

Requisito: el servidor necesita **acceso a GitHub** (`github.com` y
`objects.githubusercontent.com`) durante el build para descargar el binario.

```bash
docker compose build backend && docker compose up -d backend
```

No hay ningún paso extra: el build compila el CSS solo.

Comprobaciones:

```bash
# 1. El CSS está en la imagen y se sirve
docker exec moyza_backend ls -la app/static/css/tailwind.css
curl -sI http://localhost:8000/static/css/tailwind.css | head -3      # 200, text/css

# 2. No sale el aviso de respaldo en los logs
docker logs moyza_backend 2>&1 | grep "tailwind.css no encontrado" || echo "OK: sin aviso"

# 3. Una página interna trae el <link> y no el <script>
#    (/ y /login son la pantalla de login, que es una plantilla aparte; ver "Pendiente")
python .claude/skills/moyza-ui-ux-pro/scripts/fetch_page.py /dashboard --grep "tailwind"
#    Sin el script anterior, lo mismo a mano (admin@moyza.com o cualquier usuario existente):
docker exec moyza_backend python -c "
import urllib.request, app.db.base
from app.core.security import create_access_token
tok = create_access_token({'sub': 'admin@moyza.com'})
req = urllib.request.Request('http://localhost:8000/dashboard', headers={'Cookie': 'access_token=' + tok})
print([l.strip() for l in urllib.request.urlopen(req).read().decode().splitlines() if 'tailwind' in l])
"
```

Resultado esperado: `<link rel="stylesheet" href="/static/css/tailwind.css?v=…">` y
ninguna línea con `tailwind.js`. En el navegador (DevTools > Red) ya no se descarga
`tailwind.js` (407 KB) en las páginas internas.

Si el build falla en la etapa `css` (sin red hacia GitHub), el despliegue **no** sigue
adelante con una imagen rota: falla el build y la imagen anterior sigue corriendo.

## Desarrollo en local

`docker-compose.local.yml` monta `./backend:/app`, así que el CSS de la imagen queda
tapado por la carpeta del host. Hay dos formas de trabajar:

1. **Sin compilar** (lo de siempre): si no existe `backend/app/static/css/tailwind.css`,
   la app usa `tailwind.js` y cualquier clase nueva funciona al momento. Más lento.
2. **Compilando** (igual que producción):

   ```bash
   bash backend/scripts/build_css.sh           # build minificado
   bash backend/scripts/build_css.sh --watch   # recompila al guardar (sin minificar)
   docker restart moyza_backend                # la versión del CSS se lee al arrancar
   ```

   Ojo: **mientras exista `tailwind.css`, una clase que no se haya usado antes en el
   proyecto no tendrá estilo hasta recompilar**. Deja `--watch` abierto mientras tocas
   plantillas, o borra `tailwind.css` (y reinicia) para volver al modo sin compilar.

El aviso `Browserslist: caniuse-lite is outdated` que imprime el binario es inofensivo.

## Reglas para no perder clases

Tailwind solo genera las clases que encuentra **escritas enteras** en los archivos de
`content`:

- Escribe la clase completa: `'bg-green-100' if x else 'bg-gray-100'`, nunca
  `bg-{{ color }}-100` ni `'bg-' + color + '-100'`.
- Las clases devueltas desde Python (p. ej. `FollowUpActionType.stage_badge_color` en
  `app/core/constants.py`) o escritas en JS (`app/static/js/*.js`) funcionan porque esos
  archivos están en `content`. Si pones clases en otro sitio (otra carpeta, datos de la
  BD, un JSON), añádelo a `content` en `tailwind.config.js`.
- Caso conocido hoy: `buyers/detail.html` arma
  `bg-{% if … %}green{% else %}gray{% endif %}-100` (y `text-…-700`). Funciona solo
  porque esas cuatro clases se usan enteras en otras plantillas.

## Cambiar de versión

La versión está en dos sitios y deben coincidir: `ARG TAILWIND_VERSION` en
`backend/Dockerfile` y `TAILWIND_VERSION` en `backend/scripts/build_css.sh`. Quedarse en
3.x: Tailwind 4 cambia la configuración y el nombre de varias clases.

## Pendiente

- `auth/login.html` es una plantilla independiente (no extiende `base.html`) y sigue
  cargando `tailwind.js` siempre. Para que el login también use el CSS compilado hay que
  sustituir su `<script src="/static/js/tailwind.js">` por el mismo bloque
  `{% if tailwind_css_version %}…{% else %}…{% endif %}` de `base.html`.
