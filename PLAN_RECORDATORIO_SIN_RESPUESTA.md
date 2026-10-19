# Plan: un solo aviso de compradores ("Sin respuesta" a las 24 h hábiles) y menos etapas

Fecha: 2026-10-19 · Rama `63-agregar-moes` · Sustituye las reglas de `PLAN_ALERTAS_DIAS_HABILES.md`

## 1. Qué pide el usuario (literal) y cómo se interpreta

| Petición | Interpretación que se ejecuta |
|---|---|
| "Dejar solo alertas de 24 h hábiles cuando no hay respuesta (pestaña de seguimiento, Sin respuesta); las otras alertas ya no, están generando mucho caos." | Se **eliminan** las dos reglas actuales de compradores: "sin gestión" (48 h) y "sin avance de Primera llamada". Queda **una sola**: 24 h hábiles después de registrar **"Sin respuesta"**, si no ha habido otro seguimiento, se avisa "vuelve a llamar". |
| "Estas alertas deben llegar a los agentes y al agente [admin]." | Al **agente asignado**: campana + Inicio + email diario. Al **admin**: bloque "Requiere atención" del Inicio agrupado por agente (sin email, como se decidió el 2026-10-18). |
| "Con 3 alertas sería suficiente, a la tercera lo cerrarían." | Un aviso por cada "Sin respuesta" registrado, **máximo tres** por alerta (por ventana de asignación). El tercero dice que toca cerrar la alerta como "Sin interés". A partir del cuarto "Sin respuesta" no hay más avisos. No se cierra sola: la cierra el agente. |
| "Quitar de seguimiento Primera llamada y Calificado." | Desaparecen del formulario de seguimiento. Los registros antiguos se siguen mostrando con su etiqueta. El seguimiento automático "CALIFICADO" que crea el guardado del perfil pasa a una acción propia `PERFIL_GUARDADO` (gestión real, no etapa). |

Avisos que **no** cambian: comprador asignado/reasignado (campana), seguimiento con fecha de próxima acción
vencida (`follow_up_due`, la fecha la pone el propio agente), y los de visitas. Si el usuario también quiere
quitar `follow_up_due`, es una línea en el scheduler.

## 2. Cómo queda hoy (para saber qué se quita)

- `services/buyer_attention_service.py`: reglas `no_action` (48 h hábiles sin gestión) y `stage_stall` (48 h
  sin pasar de Primera llamada). `find_buyers_needing_attention`, `BuyerAttention`, `first_stage_label`.
- `services/notification_service.py`: tipos `buyer_no_action` / `buyer_stage_stall`, `run_buyer_attention`
  (cadencia cada 2 días hábiles), `resolve_buyer_notifications`.
- `services/buyer_reminder_service.py`: email diario con dos secciones; `get_pending_buyers_by_agent` delega
  en el servicio de atención.
- `services/dashboard_service.py`: `attention_summary` ("2 sin gestión · 1 sin pasar de Primera Llamada"),
  modal del agente y "Requiere atención" del admin.
- `routes/alerts.py` + `templates/alerts/list.html` / `detail.html`: badge ámbar y "vence el …".
- `core/config.py`: `BUYER_REMINDER_HOURS` (48), `BUYER_STAGE_STALL_HOURS` (48), `BUYER_REMINDER_REPEAT_BUSINESS_DAYS` (2).
- `core/constants.py`: `FollowUpActionType.progression_stages()` ofrece Primera Llamada, Sin Respuesta,
  Contactado, Calificado, Visita Programada, Oferta. `STAGE_ORDER` con PRIMERA_LLAMADA=1 … OFERTA=5.
- `routes/alerts.py:~1522`: al guardar el perfil desde la alerta se crea un seguimiento `CALIFICADO` automático.
- Datos locales: 3 seguimientos PRIMERA_LLAMADA, 3 CALIFICADO, 1 SIN_RESPUESTA.

## 3. Diseño

### 3.1 Regla única: "Volver a llamar" (`callback`)

Para cada alerta abierta (`PENDING` / `IN_PROGRESS`), en su ventana de asignación (`alert_view.assignment_start`):

- `attempts` = número de seguimientos `SIN_RESPUESTA` en la ventana.
- Aplica si el **último seguimiento real** de la ventana es `SIN_RESPUESTA` (ningún seguimiento posterior,
  del tipo que sea) **y** `attempts <= BUYER_CALLBACK_MAX_ATTEMPTS` (3).
- `since` = fecha de ese último "Sin respuesta"; `due_at = add_business_hours(since, BUYER_CALLBACK_HOURS)` (24).
- Vencida cuando `now >= due_at`. Texto: "Intento {attempts} de 3 sin respuesta · vuelve a llamar" y, si
  `attempts == 3`: "Tercer intento sin respuesta · cierra la alerta (Sin interés)".
- Cualquier seguimiento posterior (incluido otro "Sin respuesta", que abre el siguiente intento) la resuelve.
  Cerrar, reasignar o borrar la alerta también.

`buyer_attention_service.py` se reescribe con esta única regla: `RULE_CALLBACK = "callback"`, `BuyerAttention`
con `attempts`, `max_attempts`, `is_last_attempt`. Se eliminan `RULE_NO_ACTION`, `RULE_STAGE_STALL`,
`first_stage_label`, `first_stage_since`. `find_buyers_needing_attention` mantiene la firma
(`company_id`, `agent_id`, `now`) y `get_pending_buyers_by_agent` sigue delegando (el Inicio y el email no
cambian de forma de llamada).

### 3.2 Canales

| Canal | Qué |
|---|---|
| Campana (agente) | Tipo nuevo `buyer_callback_due`. **Una notificación por intento** (dedupe por alerta + `attempts`), sin repetición. Título "Vuelve a llamar · {comprador}", cuerpo "Intento N de 3 sin respuesta desde el {fecha} · venció el {fecha}". En el tercero, el cuerpo pide cerrar. Al registrar un seguimiento, las pendientes de esa alerta se marcan leídas (`resolve_buyer_notifications`, ya existe). |
| Email diario (agente) | El mismo job de 08:00 Madrid en días hábiles, **una sola sección** "Pendientes de volver a llamar" con comprador, teléfono, intento N de 3 y desde cuándo. Si no hay nada, no se envía. |
| Inicio agente | Modal y "Hoy y pendiente": "N compradores pendientes de volver a llamar" con intento y vencimiento. `attention_summary` pasa a "3 pendientes de volver a llamar · 1 en tercer intento". |
| Inicio admin | "Requiere atención" agrupado por agente, mismo texto. |
| `/alerts` y detalle | Badge ámbar "Volver a llamar · intento 2 de 3" (rojo si es el tercero) y "Venció el …" en el detalle. Se quitan los badges de sin gestión / sin avance. |

### 3.3 Etapas de seguimiento

- `progression_stages()` → Sin Respuesta, Contactado, Visita Programada, Oferta/Negociación.
- `LEGACY_STAGES = {PRIMERA_LLAMADA, CALIFICADO}`: siguen en `labels()`, `stage_badge_color` y `STAGE_ORDER`
  (para ordenar historiales antiguos: PRIMERA_LLAMADA = 1, CALIFICADO = 2 como Contactado), pero `is_valid()`
  los **rechaza** en el formulario (si llegan por POST → flash de error).
- Nueva acción `PERFIL_GUARDADO` ("Perfil guardado"): repetible, gestión real (desbloquea la cola y permite
  cerrar), no avanza etapa, no sale en el formulario (la crea el guardado del perfil). Sustituye al
  `CALIFICADO` automático en `routes/alerts.py` y en `buyer_matching.profile_note`.
- Donde se muestre "etapa actual" (detalle, Inicio), los registros antiguos muestran su etiqueta heredada.

### 3.4 Limpieza de lo anterior

- Config: quitar `BUYER_REMINDER_HOURS`, `BUYER_STAGE_STALL_HOURS`, `BUYER_REMINDER_REPEAT_BUSINESS_DAYS`;
  añadir `BUYER_CALLBACK_HOURS=24` y `BUYER_CALLBACK_MAX_ATTEMPTS=3`. `BUYER_REMINDER_HOUR` y
  `BUYER_REMINDER_ENABLED` se quedan.
- Notificaciones antiguas `buyer_no_action` / `buyer_stage_stall` sin leer: **migración de datos**
  `z9a0b1c2d3e4` (sin cambio de esquema) que las marca leídas; el `downgrade` no hace nada. Los dos tipos se
  conservan en `NotificationKind.STYLES` para que el historial se pinte.
- `DashboardThresholds`: sin cambios (abandonados > 7 días es un KPI, no un aviso).
- `PLAN_ALERTAS_DIAS_HABILES.md`: añadir al principio una nota "Sustituido el 2026-10-19 por
  PLAN_RECORDATORIO_SIN_RESPUESTA.md; el calendario hábil se mantiene".

## 4. Fases

Un commit por fase: `feat(compradores): fase N - recordatorio sin respuesta …`. Skill `moyza-ui-ux-pro` en lo visual.

### Fase 1 · Etapas
- [ ] `constants.py`: `progression_stages`, `LEGACY_STAGES`, `is_valid`, `PERFIL_GUARDADO` (en
      `REPEATABLE_ACTIONS`, etiqueta y color), `STAGE_ORDER` renumerado con legados.
- [ ] `routes/alerts.py` guardado de perfil → `PERFIL_GUARDADO`; `buyer_matching.profile_note` docstring.
- [ ] Tests: el formulario rechaza PRIMERA_LLAMADA/CALIFICADO; el historial antiguo se pinta; `PERFIL_GUARDADO`
      desbloquea la cola y no avanza etapa (`alert_view` lo cuenta como real).

### Fase 2 · Regla única
- [ ] Reescribir `buyer_attention_service.py` (§3.1); config nueva; `get_pending_buyers_by_agent` adaptado.
- [ ] Tests: 1er, 2º y 3er intento; 4º sin aviso; seguimiento posterior resuelve; reasignación reinicia
      (`attempts` solo en la ventana); fin de semana y festivo de Jaén por medio; alerta cerrada no aplica.

### Fase 3 · Canales
- [ ] `notification_service.py`: `BUYER_CALLBACK_DUE`, `run_buyer_attention` sin cadencia (una por intento),
      `resolve_buyer_notifications` sobre el tipo nuevo; `BUYER_KINDS` incluye los antiguos solo para resolver.
- [ ] Email: una sección; `dashboard_service.py`: textos y `attention_summary`; `/alerts` y detalle: badge y
      vencimiento; quitar referencias a "sin gestión" / "Primera llamada".
- [ ] Migración de datos `z9a0b1c2d3e4` (marcar leídas las antiguas).
- [ ] Tests de canales (patrón `test_buyer_attention_channels.py`): una notificación por intento, email con
      la sección, Inicio agente y admin.

### Fase 4 · QA y despliegue
- [ ] Job con fecha simulada: "Sin respuesta" un viernes 17:00 → vence lunes 17:00 (o martes si el lunes es
      festivo); tres intentos; cuarto sin aviso. Gmail falso.
- [ ] `ui_lint.py`; verificación con `fetch_page.py` (admin y agentes 6 y 12).
- [ ] Nota de despliegue en `MULTIEMPRESA_MOYZA_MOES.md` (§15): variables que desaparecen y aparecen, migración
      de datos, y aviso de que el email y la campana cambian de contenido.

### Criterios de aceptación
1. Tras "Sin respuesta", a las 24 h hábiles el agente recibe un aviso en la campana y lo ve en el Inicio; el admin lo ve en "Requiere atención".
2. Tres "Sin respuesta" → tres avisos, el tercero pide cerrar; el cuarto no avisa.
3. Registrar cualquier seguimiento resuelve el aviso; nada más genera avisos de compradores (salvo asignación y próxima acción fijada por el agente).
4. El formulario de seguimiento no ofrece Primera llamada ni Calificado; los antiguos se ven; guardar el perfil crea "Perfil guardado".
5. Las notificaciones antiguas de sin gestión / sin avance quedan leídas tras la migración.

## 5. Brief para el agente ejecutor

> Implementa `PLAN_RECORDATORIO_SIN_RESPUESTA.md` por fases, un commit por fase, sin push, con el skill
> `moyza-ui-ux-pro` en lo visual. Lee primero `PLAN_ALERTAS_DIAS_HABILES.md` (lo que se sustituye),
> `services/buyer_attention_service.py`, `services/notification_service.py` (380-520), `services/buyer_reminder_service.py`,
> `services/dashboard_service.py` (usos de `get_pending_buyers_by_agent`, `attention_summary`, modal),
> `services/alert_view.py`, `core/business_calendar.py`, `core/constants.py` (`FollowUpActionType`),
> `core/config.py`, `jobs/scheduler.py`, `routes/alerts.py` (seguimientos, guardado de perfil, listado, detalle),
> `templates/alerts/list.html`, `alerts/detail.html`, `dashboard/*`, y los tests `test_buyer_attention_service.py`,
> `test_buyer_attention_channels.py`, `test_dashboard_service.py`, `test_alert_view.py`. Última migración:
> `y8z9a0b1c2d3` (la tuya: `z9a0b1c2d3e4`, solo datos). Reporta la salida real de pytest, ui_lint y del job con
> fechas simuladas.
