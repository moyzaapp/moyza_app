# Plan: abrir WhatsApp desde el teléfono del interesado en el detalle de la alerta

Fecha: 2026-10-16. Rama: `57-cambios-de-visitas-compradores-y-otros`.

## Objetivo

En `/alerts/{id}` (detalle de una alerta de comprador), junto al teléfono del
interesado, un botón que abra el chat de WhatsApp con ese número. En el móvil
abre la app; en escritorio, WhatsApp Web o la app de escritorio. Nada más por
ahora: ni mensaje prellenado, ni otros listados, ni teléfono del agente.

## Decisiones cerradas con el usuario (no cambiar)

- **Qué número**: solo el del interesado/comprador (`alert.lead_phone`). El
  agente asignado sigue mostrando solo su nombre.
- **Prefijo por defecto**: España (+34) para números guardados sin prefijo.
  Los que traen `+` o `00` se respetan.
- **Alcance**: solo `alerts/detail.html`. Pero el enlace se genera con un
  **filtro Jinja reutilizable** para poder extenderlo después a listados,
  compradores y visitas con una línea en cada plantilla.
- **Sin mensaje prellenado** (`?text=`): solo abrir el chat.
- **Llamada**: el enlace `tel:` que ya existe sobre el número **se mantiene**
  tal cual (no es parte de este cambio quitarlo ni destacarlo). El usuario
  decidirá más adelante si se ofrece llamar como acción visible.

## Archivos que toca este plan (y solo estos)

- `backend/app/core/phone.py` — **nuevo**: `whatsapp_url(phone) -> str | None`.
- `backend/app/web/template_env.py` — registrar el filtro `whatsapp_url`.
- `backend/app/web/templates/alerts/detail.html` — botón junto al teléfono.
- `backend/tests/test_phone_links.py` — **nuevo**.
- Este archivo (sección "Estado").

No tocar nada más (ni `constants.py`, ni `ui_macros.html`, ni otras plantillas).
Sin commits.

## Diseño

### `app/core/phone.py`

```python
from app.core.constants import PhoneCountryCodes

def whatsapp_url(phone) -> str | None:
    """Enlace https://wa.me/<prefijo><número> para abrir el chat, o None si
    el teléfono no es utilizable.

    Reglas:
    - Se quitan todos los caracteres que no sean dígitos.
    - Un prefijo internacional escrito como `00` se elimina (0034… → 34…).
    - Si el número empieza por un indicativo conocido (PhoneCountryCodes.split)
      se respeta; si no, se asume España (+34). Esa función ya hace exactamente
      esto y es la misma regla que usa el selector de país de visitas.
    - Si tras normalizar la parte local tiene menos de 6 dígitos, devolver None
      (número incompleto: no se muestra el botón).
    """
```

Casos que deben dar el resultado indicado (y ser tests):

| Entrada | Salida |
|---|---|
| `"600123456"` | `https://wa.me/34600123456` |
| `"+34 600 12 34 56"` | `https://wa.me/34600123456` |
| `"34600123456"` | `https://wa.me/34600123456` |
| `"0034 600123456"` | `https://wa.me/34600123456` |
| `"+57 300 123 4567"` | `https://wa.me/573001234567` |
| `"953 94 09 56"` (fijo español) | `https://wa.me/34953940956` |
| `"12345"` | `None` |
| `""`, `None`, `"sin teléfono"` | `None` |

Sin `?text=`. Sin dependencias nuevas.

### `template_env.py`

`templates.env.filters["whatsapp_url"] = whatsapp_url`, junto a `madrid_dt`.

### `alerts/detail.html`

Bloque actual (líneas ~41-49):

```html
{% if alert.lead_phone %}
<div>
    <label class="text-sm text-gray-600">Teléfono</label>
    <p class="text-gray-800 font-medium">
        <a href="tel:{{ alert.lead_phone }}" class="text-blue-600 hover:underline">{{ alert.lead_phone }}</a>
    </p>
</div>
{% endif %}
```

Cambiar a: el número como está (enlace `tel:`), y a su lado un botón
secundario "WhatsApp" que solo se pinta si `alert.lead_phone | whatsapp_url`
devuelve algo:

- `<a href="{{ url }}" target="_blank" rel="noopener noreferrer">`.
- Estilo del **botón secundario** del sistema de diseño (ver
  `components/ui_macros.html` → macro `button` con `variant="secondary"`; si
  el macro admite `href` y `caller` para el icono, usar el macro; si no encaja
  por el tamaño, usar las mismas clases a mano). Área táctil ≥ 40 px.
- Icono: el sistema de diseño usa Heroicons y no admite logos de marca ni
  emojis. Usar el icono `chat-bubble-left-ellipsis` (outline, 1.5) con el
  texto "WhatsApp". **No** usar el logotipo de WhatsApp ni colorear el botón
  de verde (el verde está reservado a estados "completado/bien").
- `aria-label="Abrir chat de WhatsApp con {{ alert.lead_name }}"`.
- En móvil el número y el botón pueden ir en columna (`flex flex-col sm:flex-row sm:items-center gap-2`).
- Si `whatsapp_url` es `None`, no mostrar el botón ni ningún aviso; el número
  queda como hoy.

Leer antes `.claude/skills/moyza-ui-ux-pro/SKILL.md`, `references/tokens.md`,
`references/components.md` y `references/ux-rules.md`. Al terminar:
`python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates`
desde la raíz; `alerts/detail.html` sin avisos nuevos (ejecutarlo también antes
de tocar nada para comparar).

### Tailwind compilado

La app ya sirve un CSS compilado en el build (`TAILWIND_BUILD.md`). Las clases
que uses deben estar escritas enteras en la plantilla (nada construido por
partes). Tras cambiar la plantilla, ejecutar `bash backend/scripts/build_css.sh`
y comprobar que las clases nuevas del botón aparecen en
`backend/app/static/css/tailwind.css` (ese archivo no se sube a git; en
producción lo genera el build de Docker).

## Verificación

1. `cd backend && python -c "import app.main"`.
2. Tests nuevos `tests/test_phone_links.py` con la tabla de casos de arriba
   (todos) y además: que el filtro está registrado en
   `app.web.template_env.templates.env.filters`.
3. Render de `alerts/detail.html` con un objeto alerta falso
   (`types.SimpleNamespace`) en tres variantes: `lead_phone="600123456"` (sale
   el botón con `https://wa.me/34600123456`, `target="_blank"` y `rel`),
   `lead_phone="12345"` (no sale el botón, sí el número) y `lead_phone=None`
   (no sale el bloque). Mirar cómo se renderizó `alerts/list.html` en
   `tests/test_alerts_pagination.py` para reutilizar el enfoque; si el detalle
   necesita demasiado contexto, probar al menos el fragmento del bloque con
   `env.from_string`.
4. Suite completa `python -m pytest -q tests`: no debe empeorar (fallos
   previos conocidos: `test_check_automatic_reports_con_propiedad_activa` y los
   tres de `test_company_isolation.py` que dependen de un servidor local).
5. `build_css.sh` + grep de las clases nuevas en el CSS.
6. `ui_lint.py` sin avisos nuevos.

## Entrega

Sin commits. Informe con archivos tocados, resultado de cada verificación con
números, decisiones donde el plan dejaba margen, y qué habría que tocar para
extenderlo a otras pantallas (una lista de archivo + línea, sin hacerlo).
Marcar "Estado".

## Estado

- [x] `app/core/phone.py` + filtro registrado
- [x] Botón en `alerts/detail.html`
- [x] Tests
- [x] CSS recompilado y lint
