# Plan: enviar una propiedad al comprador por WhatsApp desde la app

Fecha: 2026-11-12. Rama: `63-agregar-moes`. Ejecuta: Opus 5.5 (high).

## 1. Objetivo

Que el agente comparta con un comprador el enlace público (web de la inmobiliaria) de una
propiedad sin salir de la app ni copiar y pegar: un botón en la tarjeta de la propiedad
sugerida abre su WhatsApp con el chat del comprador y el mensaje ya escrito (saludo, datos
básicos y enlace). El agente solo pulsa enviar.

Tres piezas: (A) saber el enlace público de cada propiedad, (B) mostrarlo en Propiedades,
(C) enviarlo al comprador y dejar constancia.

## 2. Decisiones cerradas con el usuario (no cambiar)

- **Canal**: WhatsApp del propio agente con mensaje prellenado (`wa.me/<tel>?text=…`). Nada de
  Evolution API ni de correo.
- **Desde dónde se envía**: solo las **tarjetas de propiedades sugeridas** (`property_card`):
  paso "Propuesta" de la alerta y pestaña "Propiedades compatibles" de la ficha del comprador.
  No hay "enviar a comprador" desde el listado o el detalle de Propiedades.
- **Registro**: sí, **solo informativo**. Aparece en el historial de la alerta pero no cuenta
  como gestión: no desbloquea la cola, no permite cerrar, no marca actividad ni saca al
  comprador de "sin gestionar". Mismo trato que `REASIGNADA` (`SYSTEM_ACTIONS`).
- **Enlace de MOYZA**: se calcula con la referencia. **MOES**: aún no se conoce el patrón; sus
  propiedades solo tendrán enlace si alguien lo pega a mano.

## 3. Lo que se comprobó contra la web real (2026-11-12)

- `https://www.inmobiliariamoyza.com/recursos/nficham06.php?cod_inmueble=9834998349193300`
  carga la ficha y muestra "Ref. 1933". El código es `98349` (cod_cliente) + `98349`
  (cod_captacion) + referencia + `00`.
- El mismo código **sin** el `00` final (`…1933`) devuelve una ficha vacía ("en , . Precio a
  consultar", imagen `nodisponble.jpg`). Ojo: la web responde **HTTP 200 también cuando el
  inmueble no existe**, así que el código de estado no sirve para validar.
- Solo se pudo verificar un inmueble. El usuario ha visto casos en los que el sufijo no es
  `00`; por eso hay un campo manual que manda sobre el patrón (§4.1).
- La base local es de prueba (1 propiedad con referencia), no sirve para contrastar el patrón.

## 4. Diseño

### 4.1 Enlace público de la propiedad (A)

Dos columnas nuevas, una migración Alembic (`down_revision` = la última, `z9a0b1c2d3e4`):

- `companies.property_url_template` (String, nullable): plantilla con el marcador
  `{referencia}`. La migración la rellena para MOYZA con
  `https://www.inmobiliariamoyza.com/recursos/nficham06.php?cod_inmueble=9834998349{referencia}00`
  y la deja a NULL en MOES. Añadirla también a `seeds/initial_data.py`. No hay pantalla de
  edición de empresas; cuando se conozca la de MOES se pone con otra migración o un UPDATE.
- `properties.public_url` (String, nullable): enlace pegado a mano. **Tiene prioridad** sobre
  la plantilla (cubre las excepciones del sufijo y a MOES).

Un solo punto de verdad, `app/services/property_link.py`:

```python
def property_public_url(prop) -> str | None:
    """Enlace público de la propiedad o None si no se puede saber.
    1. prop.public_url si está relleno.
    2. Plantilla de su empresa (prop.company.property_url_template) con la
       referencia recortada, si hay plantilla y referencia.
    3. None."""

def clean_public_url(value) -> str | None:
    """Normaliza lo que llega del formulario: recorta; vacío → None; exige
    http:// o https:// y un máximo de 500 caracteres (ValueError si no)."""
```

- La referencia se inserta con `urllib.parse.quote` (hoy son numéricas, pero es texto libre).
- Se usa siempre la empresa **de la propiedad**, no la activa (las sugerencias mezclan las dos).
- Registrar el filtro Jinja `public_url` en `web/template_env.py`
  (`{{ prop | public_url }}`), junto a `whatsapp_url`.
- No se comprueba en vivo contra la web (lento y frágil); el agente puede abrir el enlace
  antes de enviarlo (§4.2 y §4.3).

### 4.2 Dónde se ve en Propiedades (B)

- **Formulario** (`properties/form.html` y el modal de edición que se rellena con `data-*` en
  `properties/table.html`): campo opcional "Enlace en la web" (`public_url`, `type="url"`) en
  el bloque de identificadores, junto a Referencia/Código. Texto de ayuda: "Déjalo vacío para
  usar el enlace automático de la referencia. Rellénalo solo si el automático no abre la
  ficha." Guardarlo en `create_property` y `update_property` con `clean_public_url`; incluirlo
  en `_build_change_logs` para que el cambio quede en el historial de la propiedad.
- **Detalle** (`properties/detail.html`): en la cabecera, junto a los datos de referencia, fila
  "Enlace en la web" con dos acciones: "Abrir" (`target="_blank" rel="noopener noreferrer"`)
  y "Copiar enlace" (`navigator.clipboard`, con aviso "Copiado"). Si el enlace sale de la
  plantilla, nota discreta "Automático por referencia"; si es manual, "Manual". Sin enlace:
  "Sin enlace — añádelo al editar la propiedad".
- **Listado** (`properties/table.html` y `table_others.html`): en Acciones, un botón icono
  "Abrir en la web" (Heroicon `arrow-top-right-on-square`, área 40 px, `aria-label`) solo
  cuando hay enlace. Sin columna nueva (la tabla ya es ancha en móvil).

### 4.3 Envío al comprador (C)

**Tarjeta** (`components/property_card.html`): parámetro nuevo opcional `send_action` (URL del
POST) y `sent_at` (fecha del último envío, o None). Cuando hay `send_action`:

- Botón secundario "Enviar por WhatsApp" (icono `chat-bubble-left-ellipsis`, sin logo ni verde,
  como en PLAN_WHATSAPP_ALERTA.md) dentro de un
  `<form method="POST" action="{{ send_action }}" target="_blank">` con `property_id` oculto.
  Sin `data-once`: se puede reenviar.
- Enlace de texto "Ver en la web" (`target="_blank"`) para que el agente compruebe la ficha.
- Si `sent_at`: línea "Enviada el dd/mm" (filtro `madrid_dt`). Tras pulsar, un JS mínimo cambia
  la línea a "Enviada hoy" sin recargar (la pestaña original no se recarga).
- El botón no se pinta, y en su lugar sale un texto gris con el motivo, cuando: la propiedad no
  tiene enlace ("Sin enlace web") o el comprador no tiene un teléfono válido para WhatsApp
  ("Comprador sin teléfono válido"). Es independiente de "Asociar a esta alerta"/"Crear
  alerta", que siguen igual.

**Rutas** (devuelven `303` a la URL de `wa.me`; la pestaña nueva acaba en WhatsApp):

- `POST /alerts/{alert_id}/send-property` (`property_id`) en `routes/alerts.py`. Mismo permiso
  que `/alerts/{id}/link-property` (admin o el agente de la alerta) y mismas reglas de qué
  propiedad se puede proponer (las dos empresas, disponible). Teléfono: `alert.lead_phone`.
- `POST /buyers/{buyer_id}/send-property` (`property_id`) en la ruta de la ficha del comprador.
  Teléfono: `buyer.phone`. El registro va a la alerta **abierta más reciente** de ese
  comprador que el usuario pueda gestionar (admin: cualquiera; agente: las suyas); si no hay
  abierta, la más reciente cerrada; si el usuario no tiene ninguna alerta con ese comprador,
  la ficha no ofrece el botón.
- Errores (sin enlace, teléfono no válido, propiedad no permitida): `flash` de error y
  redirección a la pantalla de origen, nunca a WhatsApp.

**Mensaje** — `property_link.share_message(prop, buyer_name, agent_name)`; texto fijo en código:

```
Hola {nombre}, soy {agente} de {empresa}. Te envío este inmueble que puede encajar con lo que buscas:

{tipo} en {zona o ciudad} · {dormitorios} dorm. · {precio}
{enlace}
```

- `{nombre}`: primer nombre del comprador; sin nombre, "Hola,".
- `{empresa}`: `prop.company.name` (empresa de la propiedad).
- Se omiten los datos vacíos. **Nunca la dirección** (`address`), ni el propietario.
- `core/phone.py`: `whatsapp_url(phone, text=None)` añade `?text=` con `urllib.parse.quote`.
  Sin `text` se comporta como hoy (los tests existentes no cambian).

**Registro informativo**:

- `FollowUpActionType.PROPIEDAD_ENVIADA = "PROPIEDAD_ENVIADA"`, añadida a `SYSTEM_ACTIONS`
  (no entra en `STAGE_ORDER`, `is_valid` la rechaza desde el formulario). Etiqueta "Propiedad
  enviada", color neutro como `REASIGNADA`.
- Columna nueva `alert_follow_ups.property_id` (FK nullable a `properties.id`, misma
  migración) para saber qué propiedad se envió y pintar "Enviada el …" en la tarjeta.
  `notes`: `"Enviada por WhatsApp: {title} — {enlace}"`. `created_by` = usuario.
- Se registra al pulsar (no se puede saber si el agente llegó a enviar el mensaje); la
  etiqueta del historial lo dice: "Propiedad enviada (WhatsApp abierto)".
- **Revisar todos los sitios que leen seguimientos** y confirmar que usan `SYSTEM_ACTIONS` o
  añadir el filtro: `alert_view.py`, `dashboard_service.py`, `notification_service.py`,
  `alert_duplicate_service.py`, `buyer_attention_service.py`, `buyer_reminder_service.py`,
  `performance_report_service.py`, Resultados Comerciales y la ventana "sin gestionar"
  (`never_managed`). Un envío no debe mover ningún indicador. Buscar también usos directos de
  `"REASIGNADA"` que no pasen por `SYSTEM_ACTIONS`.
- Si `services/activity_log_view.py` etiqueta rutas, añadir las dos nuevas ("Envió propiedad
  al comprador").

## 5. Archivos

- `backend/alembic/versions/<nuevo>_property_public_link.py` — nuevo.
- `backend/app/models/company.py`, `property.py`, `alert_follow_up.py`.
- `backend/app/core/constants.py`, `core/phone.py`.
- `backend/app/services/property_link.py` — nuevo.
- `backend/app/web/template_env.py`.
- `backend/app/web/routes/properties.py`, `alerts.py`, ruta de la ficha del comprador.
- Plantillas: `components/property_card.html`, `alerts/_search_steps.html`,
  `alerts/detail.html` (historial), `buyers/detail.html`, `properties/form.html`,
  `properties/table.html`, `properties/table_others.html`, `properties/detail.html`.
- `backend/app/seeds/initial_data.py`.
- Tests nuevos: `backend/tests/test_property_link.py`, `backend/tests/test_send_property.py`.

Interfaz: leer antes `.claude/skills/moyza-ui-ux-pro/SKILL.md` y sus referencias; pasar
`ui_lint.py` antes y después. No usar el skill de Asimetrix.

## 6. Tests

`test_property_link.py`:
- MOYZA con referencia `1933` → la URL verificada del §3.
- `public_url` manual gana a la plantilla; referencia con espacios se recorta.
- Sin referencia y sin manual → None. MOES sin plantilla → None; MOES con manual → el manual.
- `clean_public_url`: vacío → None; `javascript:…`, `ftp://…` y texto suelto → `ValueError`.
- `whatsapp_url(phone, text)`: codifica saltos de línea, `&`, `€` y tildes; sin texto, igual que hoy.
- `share_message`: sin dirección ni propietario; omite datos vacíos; "Hola," sin nombre.

`test_send_property.py` (patrón de `test_alert_search.py`):
- El POST de la alerta responde 303 a `https://wa.me/34…?text=…` y crea un `PROPIEDAD_ENVIADA`
  con `property_id`.
- Agente ajeno a la alerta: rechazado, sin seguimiento.
- Propiedad sin enlace o teléfono no válido: sin redirección a WhatsApp, sin seguimiento.
- **Informativo**: tras el envío, la alerta sigue contando como sin gestionar
  (`never_managed`), no se puede cerrar por ese seguimiento y no cambia la etapa visible.
- Ficha del comprador: registra en la alerta abierta más reciente del agente; sin alerta
  propia, el botón no se pinta y el POST se rechaza.
- Render de `property_card` con y sin `send_action`, con `sent_at`, sin enlace y sin teléfono.

## 7. Verificación

1. `cd backend && python -c "import app.main"`.
2. `alembic upgrade head` y `alembic downgrade -1` sobre la base local; volver a `head`.
3. `python -m pytest -q tests`: no debe empeorar (fallos previos conocidos:
   `test_check_automatic_reports_con_propiedad_activa` y los tres de
   `test_company_isolation.py`).
4. `bash backend/scripts/build_css.sh` y grep de las clases nuevas en el CSS compilado.
5. `ui_lint.py` sin avisos nuevos.
6. Móvil a 375 px (Chromium headless por CDP): la tarjeta con los dos botones y la fila de
   acciones del listado no desbordan.
7. Prueba manual en local: poner referencia `1933` a una propiedad MOYZA, comprobar "Abrir"
   en el detalle, enviar desde una alerta y ver el mensaje en WhatsApp Web y la línea en el
   historial.

## 8. Fuera de alcance

- Envío automático desde el número de la empresa (Evolution API) y correo.
- "Enviar a comprador" desde el listado/detalle de Propiedades.
- Enviar varias propiedades en un solo mensaje.
- Plantilla de MOES y pantalla para editar la plantilla por empresa.
- Mensaje editable por agente o por empresa.

## 9. Confirmado por el usuario (2026-11-12)

1. **Sufijo**: el usuario no ha visto ninguno distinto de `00`. El patrón queda fijo con `00`
   y el campo manual cubre cualquier excepción que aparezca.
2. **Texto del mensaje** del §4.3: aprobado.
3. **Ficha del comprador**: el registro va a su alerta abierta más reciente: aprobado.

## 10. Entrega

Sin commits. Informe con archivos tocados, resultado numérico de cada verificación, decisiones
tomadas donde el plan dejaba margen y la sección "Estado" añadida al final de este archivo.

## Estado (2026-11-12)

Implementado entero, sin commits. Verificación:

1. `python -c "import app.main"` (en `moyza_backend`): OK.
2. Migración `e1n2v3p4r5o6_property_public_link.py`. La cabeza real no era `z9a0b1c2d3e4`
   sino `a6b7c8d9e0f1` y, mientras se trabajaba, otra tarea añadió `b7c8d9e0f1a2`
   (cierres compartidos): `down_revision = 'b7c8d9e0f1a2'`, una sola cabeza. `upgrade head`,
   `downgrade -1` y `upgrade head` sobre la base local: OK; MOYZA queda con la plantilla y
   MOES a NULL.
3. Suite: antes 3 fallos / 1150 OK / 3 omitidos; después 3 fallos / 1226 OK / 3 omitidos.
   Los mismos 3 fallos previos (`test_check_automatic_reports_con_propiedad_activa` y dos de
   `test_alert_assignment_routes.py`; los de `test_company_isolation.py` ya pasaban). 61 tests
   nuevos (25 en `test_property_link.py`, 36 en `test_send_property.py`); el resto de la
   diferencia son tests de la tarea de cierres. Comprobado que los 8 tests de "solo
   informativo" fallan si se saca `PROPIEDAD_ENVIADA` de `SYSTEM_ACTIONS`.
4. `build_css.sh` y clases nuevas presentes en el CSS compilado.
5. `ui_lint.py`: 176 avisos antes y después, idénticos salvo números de línea.
6. Móvil a 375 px (Chromium headless por CDP): sin desbordamiento en la Propuesta (tarjeta con
   "Asociar" + "Enviar por WhatsApp"), ficha del comprador (tarjetas), listado de
   Propiedades (fila de acciones sin salto ni desborde) y detalle de la propiedad. "Copiar
   enlace" se partía en dos líneas y se corrigió.
7. Prueba en local: referencia `1933` en la propiedad 1 (se deja puesta), "Abrir" en el
   detalle, envío desde la alerta 5985 y desde la ficha del comprador 4 → 303 a `wa.me`
   con el mensaje correcto, línea en el historial y "Enviada el" en la tarjeta. No se
   abrió WhatsApp Web.

Decisiones donde el plan dejaba margen: ver el informe de la tarea (agente ve sus envíos
desde su asignación; "Enviada el" por alerta en la Propuesta y por las alertas visibles en
la ficha; el botón también en la tarjeta de la propiedad asociada; `{zona o ciudad}` como
"zona, ciudad"; `table_others` sin columna Acciones lleva el icono junto al título;
`seeds/initial_data.py` no crea empresas y no se tocó).
