# Plan: fecha de reasignación a la vista, honorarios en %, observaciones internas, hora de España en la ficha y "ceder comprador"

Fecha: 2026-10-28 · Rama `63-agregar-moes`

Cinco peticiones del 2026-10-28. Las cuatro primeras son pequeñas y van en una fase cada una; la quinta
("ceder compradores") es la grande y va en dos fases. Las decisiones pendientes están en §7.

---

## 1. Fecha de reasignación a simple vista (también para el admin) — IMPLEMENTADO (fase A)

### Hoy

`alert_view.display_date(alert, is_admin)` devuelve `created_at` para el admin y `assigned_at or created_at`
para el agente (PLAN_ALERTA_COMO_NUEVA.md). El listado `/alerts` (`alerts/list.html:361`), la pestaña de
alertas de la ficha del comprador (`routes/alerts.py:2822`) y el orden de la tabla (`routes/alerts.py:637`)
siguen esa regla. El admin solo ve la fecha de la última asignación entrando en el detalle ("Asignada el…").

### Cambio

- La columna **Fecha** muestra para todos los roles la **última fecha de asignación** (`assignment_start`),
  que en una alerta reasignada es la fecha de la última reasignación y en una normal la de creación.
- Para el admin, cuando esa fecha difiere de la creación, debajo sale en gris pequeño "Creada el dd/mm/aaaa"
  para no perder la información (el agente no ve esa línea: para él la alerta es nueva).
- El orden de la tabla del admin pasa también a `assignment_start` (hoy ordena por creación): una alerta
  reasignada hoy sube arriba, que es lo que se espera al "aparecer a simple vista".
- El filtro de fechas del listado (si lo hay sobre `created_at`) no cambia.
- Afecta a: `services/alert_view.py::display_date` (pasa a devolver `assignment_start` siempre; se deja
  una función `created_label(alert)` para la línea secundaria), `routes/alerts.py` (orden, `display_dates`
  en los dos sitios), `alerts/list.html`, pestaña de alertas en `buyers/detail.html`.
- Tests: `tests/test_alert_view.py` (display_date), listado del admin ordena por reasignación.

---

## 2. Honorarios en caso de compra: importe o porcentaje — IMPLEMENTADO (fase B)

### Hoy

Input de texto solo dígitos con "€" fijo a la izquierda y "+ IVA" fijo a la derecha
(`properties/visit_form.html:130-150`, `visits/edit_form.html:137-155`). El servidor limpia con
`PropertyVisit.clean_purchase_fees` (quita €, +, IVA y espacios) y valida `PURCHASE_FEES_PATTERN = \d[\d.,]*`
(`routes/visits.py:56, 282, 906`). Se guarda solo el importe ("2500") y `purchase_fees_display` lo pinta
siempre como "€2500 + IVA" en el preview y el PDF.

### Cambio

- A la izquierda del input, en lugar del "€" fijo, un **selector pequeño `€ | %`** (select de dos opciones,
  por defecto €). El "+ IVA" fijo se mantiene a la derecha en ambos casos.
- Se guarda en `purchase_fees` el importe o el porcentaje con su signo: `"2500"` o `"2%"`. Sin migración:
  la columna ya es `String` y los valores antiguos (solo dígitos) siguen siendo euros.
- `clean_purchase_fees` conserva el `%`; `PURCHASE_FEES_PATTERN` pasa a `\d[\d.,]*%?`.
- `purchase_fees_display`: `"€2500 + IVA"` o `"2% + IVA"`. Preview y PDF no cambian (ya usan la propiedad).
- Nuevas propiedades de ayuda en el modelo para rellenar el formulario de edición:
  `purchase_fees_unit` (`"€"` / `"%"`) y `purchase_fees_amount` (sin signo).
- Validación: porcentaje entre 0 y 100 (mensaje "El porcentaje de honorarios debe estar entre 0 y 100").
- Tests: `clean_purchase_fees("2 % + IVA") == "2%"`, display, alta y edición con porcentaje.

---

## 3. Observaciones de la visita: solo internas

### Hoy

`notes` (obligatorio) sale en el preview (`visits/preview.html:115-118`) y en el PDF
(`visit_sheet_generator.py:386-392`). Dentro de la app **no se ve en ningún sitio** salvo en el formulario de
edición: ni en el listado de visitas (`visits/table.html`) ni en la pestaña de visitas de la propiedad
(`properties/detail.html:653+`).

### Cambio

- **PDF y preview**: se quita el bloque "Observaciones". (El preview debe ser idéntico a lo que se firma.)
  Los PDF ya generados no se regeneran; cualquier regeneración posterior ya no las incluye.
- **Formulario** (alta y edición): el campo pasa a llamarse "Observaciones internas" con ayuda "Solo las ve el
  equipo en la app; no salen en la ficha que firma el cliente". Sigue siendo obligatorio.
- **Dónde se leen en la app**: en el listado de visitas (`visits/table.html`) y en la pestaña de visitas de la
  propiedad, un icono "nota" en la fila que abre un `ui.drawer`/popover con el texto completo (patrón del
  skill moyza-ui-ux-pro: nada de columnas anchas con texto largo). Visibles para admin y para los agentes que
  ya ven esa visita (no cambia el alcance).
- Tests: el PDF generado no contiene "Observaciones" (`pypdf`), el listado sí las muestra.

---

## 4. Hora de España en la ficha de visita

### Hoy

`PropertyVisit.created_at` se guarda en UTC naive (`default=datetime.utcnow`). El preview
(`routes/visits.py:586-587`) y el PDF (`visit_sheet_generator.py:245, 402`) hacen `strftime` directo
→ **hora UTC** (1 h menos en invierno, 2 h en verano). Lo mismo con las fechas de firma, consentimiento y
confirmación de los metadatos (`:505, 509, 618-631`) y "generado … UTC". Las pantallas de la app ya usan
`madrid_dt` y salen bien.

### Cambio

- Función `to_madrid` ya existe en `core/business_calendar.py`; se añade un helper `fmt_madrid(dt, fmt)` en
  ese módulo (o `core/timezone.py`) y lo usan `visit_sheet_generator.py` y `routes/visits.py::preview`.
- Todas las fechas/horas de la ficha (FECHA, "a las HH:MM horas", firmas, metadatos) pasan a hora de Madrid y
  el pie dice "generado electrónicamente el dd/mm/aaaa a las HH:MM (hora de España)".
- Tests: con una visita creada a las 10:00 UTC en julio, el PDF dice 12:00.

---

## 5. Ceder compradores (agentes)

### 5.1 Qué hay

- Reasignar es solo admin (`alert_assignment_service.validate_reassignment`), desde el detalle y el listado,
  con historial `alert_assignment_logs`, nota `REASIGNADA` en seguimientos, alerta a Pendiente y sin leer,
  aviso `alert_assigned` al nuevo agente. El reloj de avisos (R1 48 h hábiles) arranca de nuevo con
  `assigned_at` (`buyer_attention_service.alert_clock`).
- Los admins no tienen campana en producción ("admin solo Inicio", PLAN_ALERTAS_DIAS_HABILES.md), pero la
  tabla `notifications` y `admins_of_company` ya existen.

### 5.2 Diseño

**Ceder** = reasignación hecha por el propio agente de la alerta, con límites:

| Regla | Propuesta |
|---|---|
| Quién | El agente asignado a la alerta (admin sigue con "Reasignar" sin límite). |
| Cuándo | Alerta abierta (Pendiente / En proceso) y **antes de que venza el aviso "sin gestión"**: menos de `BUYER_REMINDER_HOURS` (48) horas **hábiles** desde `assignment_start`, el mismo reloj que ya ve el agente en el detalle. Pasado el plazo, el botón sale desactivado: "Pasadas 48 h hábiles solo un administrador puede reasignar". Ver §7-1. |
| A quién | Agentes de la **empresa de la alerta** (misma lista que ve el admin, filtrada a esa empresa; sin dar acceso a otra empresa, que es cosa del admin). Ver §7-2. |
| Motivo | Texto corto **obligatorio** al ceder (el admin lo verá en el historial). Ver §7-3. |
| Aviso de comisión | En el modal, antes de confirmar: aviso ámbar "Los compradores cedidos no te generan comisión en caso de venta" con casilla "Entiendo que cedo este comprador" obligatoria. |
| Efectos | Igual que reasignar: Pendiente, sin leer, seguimientos conservados, reloj de 48 h desde cero para el nuevo agente, aviso `alert_assigned` al nuevo con texto "Te han cedido un comprador: {nombre}". La nota de seguimiento dice "Cedida de A a B: motivo". |
| Rastro | Columna nueva `kind` en `alert_assignment_logs` (`created` / `reassigned` / `ceded`) y `ceded_at` + `ceded_by_agent_id` en `property_alerts` (último cedente) para pintar el distintivo "Cedido" sin recorrer el historial. |
| Distintivo | Chip "Cedido" junto al estado en el listado y en el detalle (admin y agente receptor); en el detalle del receptor: "Cedido por {agente} el dd/mm" sin el motivo. Ver §7-4. |
| Aviso a admins | Notificación `alert_ceded` a todos los admins de la empresa: "{A} ha cedido el comprador {nombre} a {B}", enlace al detalle. Como el admin no tiene campana, se muestra en el Inicio del admin (bloque "Cesiones recientes" con las de los últimos 7 días) y queda en `/notifications`. Ver §7-5. |
| Historial para el admin | Página nueva `/alerts/assignments` (solo admin, enlace desde Compradores: "Historial de cesiones"): tabla con fecha, comprador, de → a, tipo (cedida / reasignada por admin), motivo, estado actual de la alerta; filtros por agente y rango de fechas; resumen "cesiones por agente" del período. Reutiliza `alert_assignment_logs`. |
| Indicadores | No cambia ningún indicador: contactos y cierres siguen al `agent_id` actual. Si más adelante quieres descontar cedidos de la comisión, el rastro ya está. |

### 5.3 Cambios por archivo

- Migración `c2d3e4f5a6b7`: `alert_assignment_logs.kind` (String, NOT NULL, default `reassigned`; backfill:
  `from_agent_id IS NULL` → `created`), `property_alerts.ceded_at`, `property_alerts.ceded_by_agent_id`
  (FK agents ON DELETE SET NULL). Downgrade limpio.
- `services/alert_assignment_service.py`: `can_cede(alert, agent, now)` (puro: abierto, es su agente,
  `business_hours_between(assignment_start, now) < BUYER_REMINDER_HOURS`), `validate_cession`,
  `cede(db, alert, to_agent, by_user, reason)` que reutiliza `assign(..., is_new=False, kind="ceded")`;
  `assignable_agents_for_cession(db, company_id)` (solo esa empresa).
- `services/notification_service.py`: `NotificationKind.ALERT_CEDED` (icono `users`, tono ámbar),
  `notify_alert_ceded(db, alert, from_agent, to_agent, actor)` a `admins_of_company`.
- `routes/alerts.py`: `POST /alerts/{id}/cede` (agente), `GET /alerts/assignments` (admin), `can_cede` y
  `cession_groups` en el contexto del detalle y del listado; el admin ve "Cedido" en el listado.
- Plantillas: botón "Ceder" + modal (`assign_fields` en modo `cede`: select de la empresa, motivo
  obligatorio, aviso de comisión y casilla) en `alerts/detail.html` y acción de fila en `alerts/list.html`
  (solo filas cedibles); chip "Cedido"; página `alerts/assignments.html`; bloque "Cesiones recientes" en
  `dashboard/_admin.html`.
- JS: `alert-assign.js` modo `cede` (la casilla habilita el botón).
- Tests: `tests/test_alert_cession.py` (ventana hábil con `now` inyectado, no cedible pasadas 48 h hábiles,
  solo su alerta, solo agentes de la empresa, admin notificado, chip, página de historial solo admin).
- Docs: `MULTIEMPRESA_MOYZA_MOES.md` §19 (nota de despliegue: migración) y este plan.

### 5.4 Fases y commits

| Fase | Contenido | Commit |
|---|---|---|
| A | §1 fecha de reasignación a la vista (**IMPLEMENTADO**; la pestaña de alertas de la ficha del comprador también ordena por la última asignación para el admin) | `feat(alertas): fecha de la última asignación a simple vista para todos los roles` |
| B | §2 honorarios en % (**IMPLEMENTADO**) | `feat(visitas): honorarios en caso de compra en importe o porcentaje` |
| C | §3 observaciones internas | `feat(visitas): observaciones internas fuera de la ficha firmada` |
| D | §4 hora de España | `fix(visitas): hora de España en la ficha de visita y sus metadatos` |
| E | §5 migración + servicio + ruta + modal + chip + aviso a admins | `feat(alertas): ceder comprador a otro agente dentro de las 48 h hábiles` |
| F | §5 página de historial para el admin + bloque del Inicio + docs | `feat(alertas): historial de cesiones y reasignaciones para el admin` |

Despliegue: `alembic upgrade head` (migración `c2d3e4f5a6b7`) y reinicio. Sin dependencias nuevas.

---

## 6. Fuera de alcance

- Regenerar los PDF ya firmados sin observaciones o con hora corregida (documentos firmados, se dejan).
- Calcular comisiones: solo se avisa y se deja rastro.
- Ceder en lote o ceder alertas cerradas.

---

## 7. Preguntas (respondidas → se ejecuta)

1. **Plazo de 48 h**: ¿horas **hábiles** (mismo reloj que el aviso "sin gestión", recomendado) o 48 h
   naturales?
2. **A quién puede ceder un agente**: ¿solo a agentes de la **misma empresa** de la alerta (recomendado) o a
   cualquier agente, dándole acceso a la empresa como hace el admin?
3. **Motivo** al ceder: ¿obligatorio (recomendado, para que el admin sepa por qué) u opcional como al
   reasignar?
4. **El agente que recibe** el comprador: ¿debe ver que es cedido y por quién ("Cedido por Ana el 28/10"),
   o para él es una alerta nueva sin rastro, como ahora con las reasignaciones del admin? Recomiendo que lo
   vea, por el tema de la comisión.
5. **Aviso al admin**: además de la notificación y el bloque en el Inicio, ¿quieres una sección en el **email
   diario** existente de compradores sin atender? Recomiendo no (cero spam), lo pregunto por si acaso.
6. **Fecha (punto 1)**: confirmo que el **orden** del listado del admin también pasa a la fecha de última
   asignación (la alerta reasignada sube arriba). Si prefieres que solo cambie el texto y no el orden, dímelo.
