# Plan: fuera «Sin actividad» para los agentes

Fecha: 2026-11-23. Continuación de `PLAN_RUIDO_CAMPANA.md` (D1 y D5) y de
`PLAN_RECORDATORIO_SIN_RESPUESTA.md`.

## 1. Problema

La regla R1 (48 h hábiles sin seguimiento, `buyer_attention_service`) tiene
dos variantes con el mismo aviso `buyer_no_action`:

- **«Sin gestionar»** (`never_managed`): ninguna gestión desde la asignación.
- **«Sin actividad»**: hubo gestión (Contactado, visita, oferta…) y pasan 48 h
  hábiles sin otro seguimiento. Cada gestión nueva abre otro ciclo de 48 h.

La segunda es ruido para los comerciales: un comprador contactado y en marcha
genera un aviso cada dos días hábiles de silencio, y aparece a la vez en la
campana, el email diario, el badge bajo la etapa del listado («Contactado» y
debajo «Sin actividad»), el banner del detalle y el reloj «Plazo de gestión».
La ventana de inicio ya la excluye desde el 2026-11-17 (D1).

Además «Hoy y pendiente» del Inicio del agente muestra «N compradores en
“Sin respuesta” desde hace más de 3 días» (`DashboardThresholds.NO_RESPONSE_DAYS`,
días naturales), que duplica a R3 «volver a llamar».

## 2. Decisiones (confirmadas por el usuario el 2026-11-23)

- **D1** Para los agentes, R1 queda solo como «Sin gestionar»: una alerta con
  alguna gestión real desde la asignación no tiene reloj R1. Desaparece «Sin
  actividad» de campana, email, badge del listado, banner y reloj del detalle.
- **D2** El admin sigue viendo «Sin actividad» por el momento (listado y
  detalle de la alerta, como información). Su ventana de inicio ya muestra solo
  «Sin gestionar».
- **D3** Los avisos «Comprador sin actividad» que existan se marcan leídos
  (migración de datos, como `j6q7v8c9m0d1` con `follow_up_due`).
- **D4** La sección del email diario pasa a llamarse «Sin gestionar».
- **D5** Se quita la línea «en “Sin respuesta” desde hace más de N días» de
  «Hoy y pendiente» (y `NO_RESPONSE_DAYS`).

Se mantienen sin cambios: alerta asignada, «Sin gestionar», «Volver a llamar»
(1 aviso por intento, máx. 3), visita en mi inmueble, acompañante, ficha no
enviada por WhatsApp y nota del administrador.

## 3. Diseño

### 3.1 Servicio (`app/services/buyer_attention_service.py`)

- `alert_clock(..., include_stalled: bool = False)`: tras descartar R3, si la
  ventana de asignación tiene seguimientos reales (`window` no vacío) y
  `include_stalled` es False, devuelve `None` (sin reloj). Con True, como hoy
  (`never_managed=False`, etiqueta «Sin actividad»).
- `evaluate_alert`, `evaluate_alerts` y `find_buyers_needing_attention`
  aceptan y propagan `include_stalled` (por defecto False). Así el job diario
  (email + campana), el horario (R3), `resolve_buyer_notifications`,
  `get_pending_buyers_by_agent` y los dos Inicios excluyen «Sin actividad»
  sin tocar nada más.
- Docstring del módulo y `RULE_LABELS` / `NO_ACTIVITY_LABEL`: se conservan
  (los usa el admin).

### 3.2 Rutas (`app/web/routes/alerts.py`)

- Listado: `evaluate_alerts(alerts, include_stalled=admin_view)`.
- Detalle: `alert_clock(alert, include_stalled=admin_view)`. El agente deja de
  ver el banner «Sin actividad» y el reloj «Plazo de gestión» en alertas ya
  gestionadas; conserva «Sin gestionar» (nunca gestionada) y R3.

### 3.3 Avisos y email

- `run_buyer_attention` no cambia: con los `items` ya filtrados nunca recibe
  una R1 parada. `_buyer_notification_text` solo produce «Comprador sin
  gestionar · Nombre» en la práctica.
- `resolve_buyer_notifications` marca leídos en la siguiente pasada los avisos
  «sin actividad» que queden (la regla ya no aplica); la migración D3 lo hace
  de inmediato en el despliegue.
- Email (`buyer_reminder_service._build_email_body`): sección «Sin gestionar»,
  texto «Llevan más de N horas hábiles sin ninguna gestión desde que se
  asignaron»; fuera la columna «Situación» (siempre diría lo mismo).
- `dashboard_service.attention_summary`: deja de contar «sin actividad»
  (nunca llega); se simplifica el texto.
- `pending_buyers_for_agent`: el filtro `never_managed or callback` queda
  redundante; se deja como red de seguridad con el comentario actualizado.

### 3.4 Inicio del agente (D5)

- `dashboard_service.agenda(...)`: fuera `no_response`, `no_response_days` y
  su consulta; `is_empty = not due_total and not unread`.
- `dashboard/_agent.html`: fuera el `<li>` de «Sin respuesta desde hace más de
  N días».
- `constants.DashboardThresholds.NO_RESPONSE_DAYS`: se elimina.

### 3.5 Migración de datos

`alembic/versions/<rev>_mark_buyer_no_activity_read.py`, `down_revision`
= `p2w3x4y5z6a7`:

```sql
UPDATE notifications SET read_at = (now() AT TIME ZONE 'UTC')
WHERE kind = 'buyer_no_action' AND read_at IS NULL
  AND title LIKE 'Comprador sin actividad%';
```

Downgrade sin efecto.

### 3.6 Tests

- `tests/test_buyer_attention_service.py`: una alerta con gestión y 48 h
  hábiles sin nada → `alert_clock` devuelve `None` por defecto y «Sin
  actividad» con `include_stalled=True`; «Sin gestionar» y R3 no cambian;
  tras 4 «Sin respuesta» (fuera de R3) tampoco hay reloj por defecto.
- `tests/test_buyer_attention_channels.py`: el job no crea `buyer_no_action`
  para alertas gestionadas; el email no lista «Sin actividad» y la sección se
  llama «Sin gestionar».
- `tests/test_dashboard_service.py`: fuera la aserción de `no_response`.
- Rutas: el admin ve el badge «Sin actividad» en `/alerts` y el agente no
  (`test_alerts_unmanaged_filter.py` o nuevo test de rutas).

### 3.7 Documentación

- `PLAN_RUIDO_CAMPANA.md`: nota en «Estado» remitiendo aquí.
- `PLAN_RECORDATORIO_SIN_RESPUESTA.md` y `PLAN_ALERTAS_DIAS_HABILES.md`:
  nota de que «Sin actividad» solo la ve el admin desde el 2026-11-23.
- `PLAN_DASHBOARD_INICIO.md`: fuera la línea de «Sin respuesta > 3 días».
- `MULTIEMPRESA_MOYZA_MOES.md`, sección de despliegue: `alembic upgrade head`
  + reinicio.

## 4. Fases

1. Servicio + rutas + plantillas + Inicio + tests (un agente).
2. Migración + documentación (otro agente, en paralelo).
3. Revisión del diff y suite completa.

### Estado

- [x] Fase 1 (2026-11-23): `include_stalled` en `buyer_attention_service` (4 funciones), listado y
      detalle con `include_stalled=admin_view`, email con sección «Sin gestionar», `agenda` sin
      `no_response`, `NO_RESPONSE_DAYS` eliminado. Añadido fuera del plan: `cession_window_open`
      usa `include_stalled=True` (el plazo para ceder no cambia) y el detalle muestra «Puedes
      ceder hasta el …» junto al botón, porque el agente ya no ve «Plazo de gestión».
- [x] Fase 3 (2026-11-23): revisión sin defectos; hueco cubierto en la nota de despliegue (los
      avisos de alertas paradas anteriores al 10/11 se titulaban «Comprador sin gestión»: se
      ejecuta `resolve_buyer_notifications` una vez tras la migración).
- [x] Fase 2 (2026-11-23): migración `q3x4y5z6a7b8_mark_buyer_no_activity_read` (revisa
      `p2w3x4y5z6a7`); probada en local con upgrade, downgrade -1 y upgrade (marca leída una
      «Comprador sin actividad» de prueba y deja sin tocar una «sin gestionar»). Notas en
      `PLAN_RUIDO_CAMPANA.md`, `PLAN_RECORDATORIO_SIN_RESPUESTA.md`, `PLAN_ALERTAS_DIAS_HABILES.md`,
      `PLAN_DASHBOARD_INICIO.md` y `MULTIEMPRESA_MOYZA_MOES.md` (§15). La base local tenía aplicada
      `q3c4p5t6a7b8` (captaciones, otra rama, mismo padre): se probó cambiando temporalmente la marca
      de `alembic_version` y se dejó como estaba.

## 5. Fuera de alcance

- Cambiar los umbrales (48 h / 24 h / 3 intentos).
- Quitar «Sin actividad» al admin: se revisará más adelante.
- Email y WhatsApp siguen igual de restringidos (nada nuevo por esos canales).
