# Plan: menos ruido en la campana y en la ventana de inicio del agente

Fecha: 2026-11-17. Rama `63-agregar-moes`. Relacionado: `PLAN_ALERTAS_DIAS_HABILES.md`,
`PLAN_RECORDATORIO_SIN_RESPUESTA.md`, `PLAN_VENTANA_SIN_GESTION.md`, `PLAN_DASHBOARD_INICIO.md`.

## 1. Problema

Los agentes reciben demasiados avisos y han dejado de mirar la campana. Datos de producción
(últimos 30 días, consulta sobre `notifications`):

| Aviso (`kind`) | Creados | Sin leer | Diagnóstico |
|---|---|---|---|
| `buyer_no_action` (R1 sin gestionar / sin actividad) | 2.817 | 282 | Se repite cada 2 días hábiles por cada comprador, sin tope. |
| `follow_up_due` (próxima acción vencida) | 1.959 | 1.909 | Uno por alerta y día, todos los días, nunca se apaga solo. El 97 % no se lee. |
| `buyer_callback_due` (R3 vuelve a llamar) | 306 | 146 | Moderado; tope de 3 por comprador. |
| `alert_assigned` | 278 | 224 | Indispensable. |
| Visitas, notas, cesiones | 93 | 70 | Poco volumen. |

Además, la ventana "Compradores que requieren atención" que sale al entrar muestra al agente
también los compradores "Sin actividad" (hubo gestión y luego 48 h hábiles sin nada), que el
agente percibe como ruido porque ya actuó.

## 2. Decisiones (confirmadas por el usuario el 2026-11-17)

| # | Decisión | Elegido |
|---|---|---|
| D1 | Ventana de inicio del agente | **Solo "Sin gestionar"** (nunca gestionado desde la asignación) **y "Vuelve a llamar"**. Fuera "Sin actividad". Igual criterio que la ventana del admin desde noviembre. |
| D2 | "Vuelve a llamar" (R3) | **Se queda en la ventana y en la campana**, como hoy: un aviso por intento, máximo 3. |
| D3 | Aviso "Próxima acción vencida" (`follow_up_due`) | **Se elimina** de la campana. El bloque "Hoy y pendiente" del Inicio lo sigue mostrando a diario. Los 1.909 sin leer se marcan leídos con una migración de datos. |
| D4 | Email diario de compradores vencidos | **Se deja como está.** |
| D5 | Repetición de R1 en la campana | **Propuesto, pendiente de confirmar:** un solo aviso al cruzar las 48 h hábiles, sin repetir cada 2 días. La ventana y el email ya recuerdan lo que sigue pendiente. Se mantiene configurable (`BUYER_REMINDER_REPEAT_BUSINESS_DAYS=0` = sin repetición). |

Lo que **no cambia**: `alert_assigned`, las reglas R1 y R3 en sí (48 h / 24 h hábiles, 3 intentos),
la sección "Requiere atención" y la ventana del admin, el email, y "Sin actividad" sigue contando
para la campana (un aviso al cruzar), el email y el listado.

## 3. Diseño

### 3.1 Ventana del agente (D1)

`DashboardService.pending_buyers_for_agent` devuelve hoy todas las filas de
`get_pending_buyers_by_agent` (R1 completo + R3). Se filtra a `never_managed or rule == callback`.
Mismo filtro para el botón "N compradores requieren atención" de "Hoy y pendiente" y para
`pending_summary`, porque abren la misma ventana. Subtítulo de la ventana: "sin gestionar y
pendientes de volver a llamar · horas hábiles".

El email (`run_buyer_reminders`) y la campana usan la lista completa; no se tocan.

### 3.2 Fuera `follow_up_due` (D3)

- `scheduler.py`: quitar el job `notify_follow_ups_due` y la función `notify_follow_ups_due`.
- `notification_service.py`: quitar `run_follow_up_due`. Se conserva `NotificationKind.FOLLOW_UP_DUE`
  y su estilo para que las antiguas se sigan pintando en `/notifications`.
- Migración de datos `mark_follow_up_due_read`: `UPDATE notifications SET read_at = now()
  WHERE kind = 'follow_up_due' AND read_at IS NULL` (misma plantilla que
  `z9a0b1c2d3e4_mark_buyer_stage_stall_read.py`). `cleanup_read` las borrará a los 90 días.
- Tests: quitar los de `run_follow_up_due` en `test_notification_service.py` y revisar
  `test_send_property.py` (solo referencia el kind).

### 3.3 R1 solo al cruzar (D5, si se confirma)

- `config.py`: `BUYER_REMINDER_REPEAT_BUSINESS_DAYS` por defecto `0`.
- `notification_service.buyer_reminder_due`: `repeat_business_days <= 0` → solo avisa si no hay
  aviso del vencimiento en curso (`last_created_at is None`). Hoy `max(repeat, 1)` impide el 0.
- Sigue aplicando: al reasignar o gestionar se resuelve el aviso; si vuelve a vencer (nuevo
  `due_at`), vuelve a avisar una vez.
- Tests: `test_cadencia_al_cruzar_y_cada_dos_dias_habiles` y
  `test_notifica_al_cruzar_y_cada_dos_dias_habiles` pasan a comprobar "una vez por vencimiento"
  con el valor por defecto, y la cadencia de 2 días con el valor explícito.

### 3.4 Documentación

- `PLAN_ALERTAS_DIAS_HABILES.md` §4 decisiones 4 y 7 (cadencia).
- `PLAN_RECORDATORIO_SIN_RESPUESTA.md` (nota sobre `follow_up_due`).
- `PLAN_DASHBOARD_INICIO.md` §3.4 (ventana del agente) y §4.3 (`follow_up_due`).
- `MULTIEMPRESA_MOYZA_MOES.md` o guía de despliegue: la migración y la variable nueva.

## 4. Fases

| Fase | Qué | Archivos |
|---|---|---|
| 1 | Ventana del agente solo con "sin gestionar" + "vuelve a llamar" | `services/dashboard_service.py`, `dashboard/_agent.html`, `tests/test_buyer_attention_channels.py` (`test_inicio_agente_y_admin_con_las_dos_reglas`) |
| 2 | Eliminar `follow_up_due` + migración de datos | `jobs/scheduler.py`, `services/notification_service.py`, `alembic/versions/<nueva>_mark_follow_up_due_read.py`, `tests/test_notification_service.py` |
| 3 | R1 solo al cruzar (si D5 se confirma) | `core/config.py`, `services/notification_service.py`, `tests/test_buyer_attention_channels.py` |
| 4 | Documentación y QA: tests, `alembic upgrade head` en local, render del Inicio del agente, prueba del job con `now` inyectado | planes, `.env.example` |

Despliegue: `alembic upgrade head` + reinicio. Sin cambios de modelo ni de plantillas del admin.

### Estado (2026-11-17)

- [x] Fase 1: `pending_buyers_for_agent` filtra `never_managed or callback`; subtítulo de la ventana;
      test `test_ventana_del_agente_excluye_sin_actividad`.
- [x] Fase 2: job y `run_follow_up_due` eliminados; migración `j6q7v8c9m0d1` aplicada en local
      (0 `follow_up_due` sin leer); tests del job retirados.
- [x] Fase 3 (D5 confirmada): `BUYER_REMINDER_REPEAT_BUSINESS_DAYS=0` por defecto y
      `buyer_reminder_due` sin repetición con 0; test `test_por_defecto_un_aviso_por_vencimiento_sin_repeticion`.
- [x] Fase 4: planes y guía de despliegue actualizados; 151 tests en verde (el único fallo,
      `test_check_automatic_reports_con_propiedad_activa`, es el conocido y ajeno); Inicio del
      agente renderiza con la ventana filtrada; linter sin avisos. Sin commitear.

> **2026-11-23 · ver `PLAN_SIN_ACTIVIDAD_AGENTES.md`:** la variante «Sin actividad» de R1 se retira
> para los agentes (campana, email, badge, banner y reloj del detalle); el admin la sigue viendo en el
> listado y el detalle de la alerta. Los avisos pendientes se marcan leídos con la migración
> `q3x4y5z6a7b8`. Del Inicio del agente sale además la línea «Sin respuesta desde hace más de 3 días».

## 5. Fuera de alcance

- Resumen diario agrupado en la campana (se descartó al mantener avisos individuales).
- Cambiar el email.
- Aviso único para reasignaciones en bloque (`alert_assigned` por alerta se mantiene).
