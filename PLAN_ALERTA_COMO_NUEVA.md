# Plan: alerta reasignada "como nueva" para el agente y bloqueo real de la cola

Fecha: 2026-10-16. Rama: `57-cambios-de-visitas-compradores-y-otros`.

## Contexto

Hoy, al reasignar una alerta (`alert_assignment_service.assign`, `is_new=False`):
estado → PENDING, `read_at` → None, `assigned_at` → ahora, se guardan
`previous_agent`, `assigned_by`, `assignment_reason`, se añade un
`AlertAssignmentLog`, una nota de sistema `REASIGNADA` en los seguimientos y se
notifica al agente nuevo (`alert_assigned`, url `/alerts/{id}`, con el motivo
en el cuerpo).

Problemas que ve el usuario:

1. El agente ve en el detalle el bloque "Agente asignado" (quién la asignó,
   quién la tenía antes, motivo, historial de asignaciones), las notas
   "Reasignada de X a Y" en el historial y los seguimientos del agente
   anterior. También ve la fecha de creación original.
2. Una alerta **bloqueada** por la cola (hay otra anterior sin seguimiento)
   sigue siendo visible: el detalle se abre desde la notificación, el
   dashboard o la ficha del comprador. Peor: `alert_detail` la marca como
   leída y la pasa a IN_PROGRESS **antes** de comprobar el bloqueo.

## Decisiones cerradas con el usuario (no cambiar)

- **Para el agente, una alerta reasignada es nueva.** Solo ve lo ocurrido
  desde su asignación: sin bloque de asignación, sin notas de reasignación,
  sin seguimientos ni etapa del agente anterior. En la cola cuenta como
  "sin gestionar" hasta que él registre un seguimiento.
- **El admin lo ve todo**, como hoy: agente asignado, anterior, motivo,
  historial de asignaciones, notas REASIGNADA y todos los seguimientos.
- **Fecha para el agente**: la de su asignación (`assigned_at`), en listado,
  detalle, ficha del comprador y dashboard. El admin sigue viendo la fecha de
  creación y, aparte, la de asignación.
- **Alerta bloqueada**: el agente **no puede abrirla por ningún camino**. Al
  intentarlo vuelve a `/alerts` con el aviso "Esta alerta está en tu cola.
  Gestiona primero las anteriores para verla." Sin tocar su estado ni `read_at`.
- Nada de esto cambia lo que se **guarda** en base de datos (la trazabilidad
  del plan de asignación se mantiene íntegra). Solo cambia lo que ve el agente.

## Concepto central: ventana de asignación

Para una alerta, `assignment_start = alert.assigned_at or alert.created_at`
(las alertas anteriores a la asignación manual tienen `assigned_at = created_at`;
usar `coalesce` en SQL y `or` en Python). Todo lo que ve y cuenta para el
agente se calcula **desde `assignment_start`**:

| Qué | Hoy | Nuevo |
|---|---|---|
| Seguimientos visibles en el detalle (agente) | todos | `created_at >= assignment_start` y no `SYSTEM_ACTIONS` |
| Etapa en el listado (agente) | último seguimiento real | último seguimiento real **desde `assignment_start`** |
| Cola: alerta "iniciada" (`get_locked_alert_ids`) | tiene algún seguimiento real | tiene algún seguimiento real **desde `assignment_start`** (si no, una reasignada con seguimientos viejos no bloquearía y debe bloquear) |
| Cerrar la alerta (`can_complete` y `complete_alert`) | algún seguimiento real | algún seguimiento real **desde `assignment_start`** (para admin y agente: la alerta reasignada debe trabajarse antes de cerrarse) |
| Fecha mostrada al agente | `created_at` | `assignment_start` |
| Admin: detalle, etapa, historial | todo | **sin cambios** (ve todo, con la fecha de creación y la de asignación) |

Implementar la ventana en **un solo sitio** y reutilizarla: añadir a
`app/services/alert_assignment_service.py` (o un módulo pequeño
`app/services/alert_view.py`, a criterio del agente) funciones como:

- `assignment_start(alert) -> datetime`
- `real_follow_ups_clause(since)` / `follow_ups_since_assignment(db, alert)`
- `visible_follow_ups(follow_ups, alert, is_admin) -> list` (filtra en Python
  una lista ya cargada; útil en el listado donde `follow_ups` viene con
  `selectinload`)
- `display_date(alert, is_admin) -> datetime`

`_real_follow_ups` en `routes/alerts.py` pasa a aceptar `since` y a usarlo.

## Cambios por archivo

### `backend/app/web/routes/alerts.py`

- **`get_locked_alert_ids`**: la consulta de `started_ids` debe exigir
  `AlertFollowUp.created_at >= coalesce(PropertyAlert.assigned_at, PropertyAlert.created_at)`
  (JOIN con `PropertyAlert`, o calcular en Python a partir de `open_alerts`,
  que ya están cargadas: para cada alerta, comprobar si existe seguimiento real
  con `created_at >= assignment_start(alert)`; una consulta agrupada
  `min/any` por `alert_id` con la condición sirve). Mantener **dos consultas
  como máximo**; no volver al N+1.
- **`alert_detail`**:
  1. Permisos (como hoy).
  2. **Bloqueo antes de cualquier escritura**: `if is_alert_locked_for_user(...)`
     → redirect `/alerts` con flash `warning` (texto exacto de la decisión).
  3. Solo después: auto-marcar leída / PENDING→IN_PROGRESS.
  4. `follow_ups`: para agente, filtrados por la ventana; para admin, todos.
  5. `can_complete`: seguimiento real desde `assignment_start` (ambos roles).
  6. Contexto nuevo: `display_date`, `assignment_start`, y `show_assignment`
     (= `is_admin`).
- **`alerts_page`**: `alert_stages` para el agente solo con seguimientos desde
  `assignment_start`; pasar `display_dates` (dict `alert.id → fecha`) o
  resolverlo en plantilla con `(alert.assigned_at or alert.created_at)` cuando
  `not is_admin`. Elegir una forma y usarla también en la ficha del comprador.
- **`complete_alert`**: `_real_follow_ups(db, alert_id, since=assignment_start(alert)).count()`.
- **`mark_alert_read`, `add_follow_up`, `register_contact_on_alert`,
  `reactivate_alert`**: comprobar que el chequeo de bloqueo ocurre antes de
  cualquier escritura (hoy `mark_alert_read` y `add_follow_up` lo hacen;
  revisar `register_contact_on_alert`, que no aparece con chequeo de bloqueo:
  si un agente puede llamarlo, debe comprobarlo).

### `backend/app/web/templates/alerts/detail.html`

- Bloque "Agente asignado" (`#alertAssignment`, "Antes:", "Motivo:", "Historial
  de asignaciones", botón Reasignar): envolver en `{% if is_admin %}`.
- Historial de seguimientos: la ruta ya entrega la lista filtrada; la
  plantilla no necesita lógica extra, pero el estado vacío debe decir algo
  coherente para el agente ("Aún no hay seguimientos. Registra el primero.").
- Caja de estado: "Fecha Creación" → para el agente, etiqueta "Fecha" con
  `display_date`; para el admin, "Fecha creación" (`created_at`) y debajo
  "Asignada" (`assigned_at`) si difiere.
- El aviso "Esta alerta está bloqueada" de la columna Acciones deja de poder
  mostrarse al agente (ya no llega al detalle); puede quedarse por seguridad.

### `backend/app/web/templates/alerts/list.html`

- Columna "Fecha": para el agente, `assignment_start`; para el admin,
  `created_at` (como hoy).
- La fila "Bloqueada" (ya oculta los datos) no cambia.

### `backend/app/web/templates/buyers/detail.html` (pestaña Alertas)

- Para el agente: las alertas suyas **bloqueadas** se muestran como fila
  "En cola" sin datos ni botón "Ver detalle" (mismo criterio que el listado;
  la ruta `buyer_detail` debe pasar `locked_alert_ids`). Las alertas de otros
  agentes no se muestran al agente (comprobar qué hace hoy la pestaña con
  ellas y mantener la regla de acceso existente).
- Fecha de la columna: `assignment_start` para el agente.

### Dashboard del agente (`app/services/dashboard_service.py`, `dashboard/_agent.html`)

- "Hoy y pendiente" sale de seguimientos con `next_action_date`. Para el
  agente: solo seguimientos **desde `assignment_start`** de la alerta y solo
  alertas **no bloqueadas**. Un seguimiento del agente anterior con próxima
  acción no debe aparecer en la agenda del nuevo. Reutilizar
  `get_locked_alert_ids` (mover a un servicio si hace falta para evitar
  importar la ruta desde el servicio).

### `backend/app/services/alert_assignment_service.py` (`_notify_assigned`)

- El cuerpo de la notificación al agente **no incluye el motivo** (`reason`)
  de la reasignación; queda solo el título de la propiedad. El título "Te han
  asignado un comprador: …" se mantiene (no revela que es una reasignación).
- La url sigue siendo `/alerts/{id}`: si está bloqueada, `alert_detail`
  redirige con el aviso.

### Otros puntos de entrada a `/alerts/{id}`

`commercial_results/_buyers.html` y `report_logs/reminder_table.html`:
comprobar si son visibles para el agente; si lo son y muestran datos de
alertas bloqueadas, aplicar el mismo criterio. Si son solo de admin, dejar.

### Documentación

- `PLAN_ASIGNACION_ALERTAS.md`: añadir una fila/nota (fecha 2026-10-16) con
  la regla "el agente ve la alerta reasignada como nueva; el admin conserva la
  trazabilidad; bloqueo real de la cola".

## Tests

- `tests/test_alert_assignment.py`: mantener los existentes (el rastro se
  sigue guardando). Añadir: seguimientos del agente anterior **no**
  desbloquean la cola del nuevo; `visible_follow_ups` para agente excluye lo
  anterior a `assignment_start` y las notas de sistema, para admin no excluye
  nada; `assignment_start` cae a `created_at` cuando `assigned_at` es None.
- Nuevo `tests/test_alert_view.py` (o dentro del anterior) con la ruta
  `alert_detail` en proceso contra SQLite en memoria (patrón de
  `tests/test_alerts_pagination.py`): agente con alerta bloqueada → 302 a
  `/alerts`, flash `warning` con el texto, `read_at` sigue None y `status`
  PENDING; agente con alerta reasignada desbloqueada → el HTML no contiene
  "Antes:", "Reasignada", "Historial de asignaciones" ni el seguimiento
  anterior, y la fecha mostrada es la de asignación; admin → sí los contiene.
- `tests/test_alert_assignment_routes.py` (integración, se salta sin app):
  ajustar los que asuman que el agente ve la nota de reasignación o abre una
  alerta bloqueada; añadir el caso de redirección.
- Suite completa: el conjunto de fallos no debe cambiar (fallo previo conocido:
  `test_scheduler.py::test_check_automatic_reports_con_propiedad_activa`; los de
  integración dan error aquí por falta de PostgreSQL).

## Diseño/UX

Leer `.claude/skills/moyza-ui-ux-pro/SKILL.md` y `references/ux-rules.md`
antes de tocar plantillas. El flash de bloqueo es `warning` (ámbar). Al
terminar: `python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates`
sin avisos nuevos, y `bash backend/scripts/build_css.sh` (comprobar que las
clases usadas existen en el CSS compilado).

## Entrega

Sin commits. Informe con archivos tocados, decisiones donde el plan dejaba
margen, resultados de cada verificación con números, pasos de prueba manual
en producción (como admin y como agente) y deuda detectada. Marcar "Estado".

## Estado

- [x] Ventana de asignación (helpers) y cola/cierre con la ventana
- [x] `alert_detail`: bloqueo antes de escribir, filtrado para agente
- [x] Plantillas: detalle, listado, ficha del comprador
- [x] Dashboard del agente y notificación sin motivo
- [x] Tests
- [x] Lint, CSS y documentación
