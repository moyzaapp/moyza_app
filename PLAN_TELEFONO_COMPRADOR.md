# Plan: indicativo de país en el teléfono del comprador

Fecha: 2026-10-16 · Rama `63-agregar-moes`

## 1. Cómo está hoy

| Punto | Estado | Archivo |
|---|---|---|
| Captura del teléfono del comprador | Campo de texto libre `tel` en **cuatro** formularios: modal "Nuevo comprador" (`/buyers/create`), modal "Agregar comprador con criterios" (`/buyers/create-with-criteria`), sección "comprador nuevo" del modal "Nueva alerta" (`/alerts/create`), y edición de contacto en la ficha del comprador (`/buyers/{id}/update-contact`). | `templates/alerts/list.html:561, 649, 1300`; `templates/buyers/detail.html:670`; `routes/alerts.py` (`create_buyer` ~622, `create_buyer_with_criteria` ~670, `create_alert` ~1053, `update_buyer_contact` ~1865) |
| Guardado | Tal cual se escribió (`strip()`), sin normalizar: conviven "600112233", "+34 600 11 22 33", "0034600112233", "34600112233". `alert.lead_phone` se copia de `buyer.phone` al crear la alerta. | `routes/alerts.py:647, 744, 1135, 1211, 1889` |
| WhatsApp | Filtro Jinja `whatsapp_url` (`app/core/phone.py`) que limpia dígitos, quita `00`, detecta el indicativo conocido y **asume +34 si no hay indicativo**. Devuelve `None` (sin botón) si la parte local tiene menos de 6 dígitos o el total supera 15. | `app/core/phone.py`, usado en `alerts/detail.html:42` |
| Duplicados | `find_matching_buyers` compara por los últimos dígitos significativos (`phone_suffix`), así que funciona con cualquier formato. | `services/alert_duplicate_service.py:58-80` |
| Selector de país ya existente | **Visitas** lo tiene desde hace tiempo: `<select name="phone_country_code">` + `<input name="phone_number">`, constante `PhoneCountryCodes` (15 países, `DEFAULT = "34"`, `choices()`, `split()`), JS que acorta el select a "+34" cuando no está abierto, y el backend guarda `código + dígitos` ("34600112233"). La lógica de componer el número está **duplicada** en `create_visit` y `update_visit`. | `core/constants.py:16-70`, `templates/properties/visit_form.html:79-95, 297-314`, `routes/visits.py` (create/update) |
| Visualización | El teléfono se muestra crudo (`{{ alert.lead_phone }}`, `{{ buyer.phone }}`). | `alerts/detail.html:46`, `alerts/list.html:285, 934, 1546`, `buyers/detail.html:33` |

Conclusión: todo lo necesario ya existe en Visitas; hay que llevarlo a los cuatro formularios de comprador,
centralizar la composición del número (hoy duplicada) y añadir la regla "no repetir el indicativo".

---

## 2. Diseño

### 2.1 Helper único en `app/core/phone.py`

```python
def compose_phone(country_code: str, raw_number: str) -> str:
    """Devuelve el teléfono canónico 'códigodígitos' (p. ej. '34600112233') o ''.

    - country_code: uno de PhoneCountryCodes; si no es válido se usa DEFAULT.
    - raw_number: lo que escribió el usuario; se queda solo con dígitos.
    - Si el usuario repitió el indicativo en el número ("+34 600…", "0034 600…",
      "34 600…"), se elimina UNA vez, solo si lo que queda tiene al menos
      MIN_LOCAL_DIGITS dígitos (así "34 1234" no se recorta a "1234").
    - Si no quedan dígitos devuelve ''.
    """

def split_phone(phone) -> tuple[str, str]:
    """(código, número local) para rellenar el selector; envuelve PhoneCountryCodes.split."""

def phone_display(phone) -> str:
    """'+34 600 112 233' para mostrar; si no se reconoce el indicativo, devuelve el texto tal cual."""
```

- Formato canónico guardado: **solo dígitos con el indicativo, sin `+`** ("34600112233"), el mismo que ya
  usan las visitas y que `whatsapp_url` entiende directamente.
- Reglas de "no repetir": se comprueba el prefijo `+`, `00` y el indicativo seleccionado al inicio de los
  dígitos. Solo se recorta cuando coincide con el **país seleccionado**: si el usuario elige +34 y escribe
  "+57 300…", no se toca (quedaría "3457300…"; se avisa en la interfaz, §2.3).
- Validación mínima: parte local entre 6 y 12 dígitos; si no, error de formulario con flash
  ("Revisa el teléfono: debe tener entre 6 y 12 dígitos sin el indicativo"). Teléfono vacío sigue siendo válido
  (hoy es opcional en todos los formularios).
- `whatsapp_url` y `PhoneCountryCodes.split` no cambian de comportamiento; `compose_phone` reutiliza
  `MIN_LOCAL_DIGITS`.
- `phone_display` se registra como filtro Jinja en `template_env.py`, al lado de `whatsapp_url`.

### 2.2 Macro de campo de teléfono

Macro `phone_field(name_prefix, country_code, local_number, label='Teléfono', required=False, id=None)` en
`components/ui_macros.html` (o en `components/phone_macros.html` si el skill prefiere separar), que pinta:
`<select name="{prefix}country_code" class="phone-country-select">` con `PhoneCountryCodes.choices()` y
`<input type="tel" name="{prefix}number" inputmode="tel" autocomplete="tel-national">`, con `label for`,
estilos del skill (`rounded-xl`, 40 px de alto) y el select acortado a "+34" cuando está cerrado. El JS del
acortado se mueve de `visit_form.html` a `static/js/phone-field.js` (un solo sitio) y se carga en las
plantillas que usan el macro. **Visitas no se toca en este plan** (otro agente está trabajando ahí); queda
anotado como deuda: cuando se cierre, `visit_form.html` y `edit_form.html` pasan a usar el macro y
`routes/visits.py` a `compose_phone`.

### 2.3 Formularios de comprador (los cuatro)

- Campo de teléfono sustituido por el macro, con `+34` por defecto y, en edición, el país y número local que
  devuelve `split_phone(buyer.phone)` (para teléfonos antiguos sin indicativo reconocible, `split` ya asume
  España y deja el número completo para que el agente lo revise).
- Nombres de campo: `buyer_phone_country_code` + `buyer_phone_number` donde hoy es `buyer_phone`, y
  `phone_country_code` + `phone_number` donde hoy es `phone`. Las rutas aceptan los nuevos campos y, por
  compatibilidad durante el despliegue, también el campo antiguo (`buyer_phone` / `phone`) si llega solo.
- **Aviso en la interfaz (JS, sin bloquear)** debajo del campo cuando el número empieza por `+`, `00` o por el
  indicativo seleccionado: "Parece que el número ya incluye el indicativo; se guardará como +34 600 112 233".
  Al guardar, el servidor aplica `compose_phone` de todas formas (el aviso es solo para que el agente vea qué
  va a quedar).
- Comprobación de duplicados en vivo (`/alerts/check-buyer`, JS de `buyerPhoneInput`): enviar el número
  compuesto (`código + dígitos`) para que el aviso de "ya existe un comprador con ese teléfono" siga
  funcionando; el backend compara por sufijo, así que no cambia.

### 2.4 Visualización

Donde hoy se muestra el teléfono crudo (`alerts/detail.html`, `alerts/list.html`, `buyers/detail.html` y
los `selectedMeta` de los autocompletados), usar `{{ phone | phone_display }}`. El enlace `tel:` usa
`+{{ phone }}` cuando el valor es canónico (`whatsapp_url` ya resuelve el caso del botón de WhatsApp).
Los resultados JSON de `/alerts/search-buyers` incluyen `phone_display` además de `phone`.

### 2.5 Datos existentes

Sin migración de esquema. **Sin backfill automático** de `buyers.phone` y `property_alerts.lead_phone`: los
valores antiguos se siguen leyendo con `split` y `whatsapp_url`, que ya los interpretan. Se añade un script
opcional `backend/scripts/normalize_buyer_phones.py --dry-run` que lista cuántos teléfonos cambiarían y a
qué, y solo con `--apply` los reescribe cuando el resultado es inequívoco (`whatsapp_url` no es `None`).
Ejecutarlo o no es decisión del usuario después de ver el `--dry-run`.

---

## 3. Fases

Un commit por fase: `feat(compradores): fase N - teléfono con indicativo …`. Skill `moyza-ui-ux-pro` en lo visual.

### Fase 1 · Helper y filtro
- [ ] `compose_phone`, `split_phone`, `phone_display` en `app/core/phone.py`; filtro `phone_display` en `template_env.py`.
- [ ] Tests unitarios sin BD en `tests/test_phone.py`: casos "600112233", "+34 600 11 22 33", "0034600112233",
      "34600112233", "+57 300…" con +34 seleccionado (no se recorta), "34 1234" (no se recorta), vacío, código
      inválido → DEFAULT, local demasiado corta/larga, `phone_display` con y sin indicativo reconocido.

### Fase 2 · Macro y formularios
- [ ] Macro `phone_field` + `static/js/phone-field.js` (acortado del select + aviso de indicativo repetido).
- [ ] Sustituir el campo en los cuatro formularios; rutas con los campos nuevos (y aceptando el antiguo).
- [ ] `check-buyer` en vivo con el número compuesto; `search-buyers` devuelve `phone_display`.
- [ ] Tests de ruta (patrón `_Client` de `test_buyer_business_type.py`): alta con "+34 600…" y +34 → guarda
      "34600…"; alta con +57 y "300…" → "57300…"; edición conserva país y número; campo antiguo `buyer_phone`
      sigue funcionando; la alerta creada copia el teléfono canónico en `lead_phone`; duplicado detectado
      aunque el existente esté guardado con espacios y `+`.

### Fase 3 · Visualización y script
- [ ] `phone_display` en los puntos de §2.4; `tel:` con `+`.
- [ ] `backend/scripts/normalize_buyer_phones.py` con `--dry-run` / `--apply` y salida resumida.
- [ ] `ui_lint.py` sobre plantillas tocadas; revisión en móvil con `fetch_page.py` (el select debe caber junto al input a 375 px).
- [ ] Nota en `MULTIEMPRESA_MOYZA_MOES.md` §10 (sin migración; script opcional) y deuda anotada para Visitas.

### Criterios de aceptación
1. En los cuatro formularios el agente elige el país (por defecto +34) y escribe solo el número; se guarda "34…".
2. Si escribe el indicativo repetido ("+34…", "0034…", "34…") con +34 seleccionado, se guarda una sola vez y la interfaz lo avisa antes de guardar.
3. El botón de WhatsApp de la alerta abre `wa.me/34600112233` para un comprador creado así.
4. Los compradores antiguos se siguen viendo, editando (con el país preseleccionado) y comparando por duplicado sin cambios.
5. Visitas no se modifica en este plan.

---

## 4. Supuestos (ejecutado sin preguntas, a petición del usuario)

- Formato guardado: dígitos con indicativo y sin `+`, igual que Visitas. Si se prefiere guardar con `+`, es un cambio de una línea en `compose_phone` y en `tel:`.
- El teléfono sigue siendo opcional en todos los formularios de comprador.
- Lista de países: la misma de Visitas (15). Añadir países es editar `PhoneCountryCodes.OPTIONS`.
- No se tocan los teléfonos ya guardados salvo que el usuario ejecute el script con `--apply`.

---

## 5. Brief para el agente ejecutor

> Implementa `PLAN_TELEFONO_COMPRADOR.md` por fases, un commit por fase, sin push, con el skill
> `moyza-ui-ux-pro` en lo visual. Lee primero `app/core/phone.py`, `app/core/constants.py` (`PhoneCountryCodes`),
> `web/template_env.py`, `routes/alerts.py` (`create_buyer`, `create_buyer_with_criteria`, `create_alert`,
> `update_buyer_contact`, `check_buyer`, `search_buyers`), `services/alert_duplicate_service.py`,
> `templates/alerts/list.html` (los tres formularios y el JS de `buyerPhoneInput`), `templates/buyers/detail.html`
> (formulario `update-contact` y cabecera), `templates/properties/visit_form.html` (referencia del select y su JS;
> NO lo modifiques), `components/ui_macros.html`. No toques `routes/visits.py` ni `templates/visits/*`: otro
> agente trabaja ahí. Reporta la salida real de pytest y ui_lint.
