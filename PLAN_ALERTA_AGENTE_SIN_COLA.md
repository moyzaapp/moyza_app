# Plan: la alerta que crea el propio agente no entra en su cola

Fecha: 2026-11-27. Rama `63-agregar-moes`. Continuación de `PLAN_ASIGNACION_ALERTAS.md`
(cola secuencial) y `PLAN_ALERTA_COMO_NUEVA.md` (bloqueo real por asignación).

## 1. Problema

Cuando un comprador llega presencialmente, el agente crea la alerta (modal «Agregar alerta
comprador» en `/alerts` o «Crear búsqueda» en la ficha del comprador) y tiene que gestionarla en
el momento. Hoy la alerta entra al final de su cola secuencial: si tiene alguna alerta anterior
sin gestionar, al abrir la nueva rebota a `/alerts` con «Esta alerta está en tu cola. Gestiona
primero las anteriores para verla» (`ALERT_LOCKED_MESSAGE`). Las alertas que asigna
administración deben seguir entrando en la cola como hasta ahora.

## 2. Cómo funciona hoy

- Una sola ruta de alta, `POST /alerts/create` (`routes/alerts.py::create_alert`). Un agente
  queda siempre asignado a sí mismo (`resolve_search_assignee`, propiedad propia +
  `resolve_assignee`); `assign(..., is_new=True)` pone `assigned_at = created_at` y
  `assigned_by = current_user.id`. No se guarda nada que distinga «la creó el agente».
- La cola: `alert_view.agent_open_alerts_ordered` ordena las abiertas del agente en la empresa
  por `coalesce(assigned_at, created_at), id`; `alert_view.get_locked_alert_ids` recorre la
  lista y bloquea todo lo posterior a la primera sin seguimiento real desde su asignación.
  Lo usan `is_alert_locked_for_user`, `_search_link_denied`, el listado («En cola»), la ficha
  del comprador, la página de compatibles de una propiedad y la agenda del Inicio.
- `assigned_at` lo usan además el reloj R1 «Sin gestionar», el plazo para ceder, las fechas
  mostradas y el Inicio: **no se toca** para saltar la cola.

## 3. Decisiones (usuario, 2026-11-27: «lo recomendado»)

- **D1** Una alerta creada por el propio agente queda **fuera de la cola**: ni se bloquea ni
  bloquea a las que vengan detrás (incluidas las de administración).
- **D2** Sigue en el listado en su posición por fecha, con su reloj R1 «Sin gestionar» (48 h
  hábiles), en el Inicio y en la ficha como cualquier otra. Solo cambia el bloqueo.
- **D3** La excepción se aplica también a las alertas abiertas que los agentes ya crearon antes
  del despliegue (backfill en la migración).
- **D4** Si administración reasigna la alerta a otro agente, o el agente la cede, deja de ser
  «creada por el propio agente»: para el nuevo agente entra en la cola con normalidad.
- Las alertas de administración no cambian.

## 4. Diseño

### 4.1 Modelo y migración

- `property_alerts.self_created` (Boolean, NOT NULL, server_default false). «La creó el agente
  que la tiene asignada».
- Migración `alembic/versions/t6u7v8w9x0y1_alert_self_created.py`, `down_revision =
  's5t6u7v8w9x0'` (cabeza actual). Añade la columna y hace el backfill (D3):

  ```sql
  UPDATE property_alerts a SET self_created = true
  FROM agents g JOIN users u ON lower(u.email) = lower(g.email)
  WHERE a.agent_id = g.id AND a.assigned_by = u.id
    AND a.previous_agent_id IS NULL AND a.ceded_at IS NULL
    AND a.status IN ('PENDING', 'IN_PROGRESS');
  ```

  (comprobar los valores reales de `status` en `constants.AlertStatus`). Downgrade: quitar la
  columna.

### 4.2 Alta, reasignación y cesión (`alert_assignment_service.assign`)

- En `assign(..., is_new=True)`: `alert.self_created = not is_admin(by_user) and el agente
  asignado es el del usuario` (en la práctica siempre que crea un agente). Mejor calcularlo en
  `create_alert` y pasarlo, o dentro de `assign` con el `agent` del usuario; elegir lo que
  menos toque.
- En `assign(..., is_new=False)` (reasignación del admin, reasignación en lote, cesión):
  `alert.self_created = False` (D4).
- `AlertAssignmentLog` no cambia.

### 4.3 Cola (`alert_view.py`)

- `get_locked_alert_ids`: las alertas con `self_created` se excluyen del recorrido (ni se
  bloquean ni cuentan como «anterior sin gestionar»). Implementación: filtrar
  `agent_open_alerts_ordered(...)` en Python (`if alert.self_created: continue`) antes del bucle,
  o añadir `PropertyAlert.self_created.is_(False)` en la consulta de la cola; cuidado con otros
  usos de `agent_open_alerts_ordered` (el listado lo usa para otra cosa: comprobar).
- Nada más cambia: `is_alert_locked_for_user`, listado, ficha, compatibles y agenda ya parten de
  `get_locked_alert_ids`.

### 4.4 Textos

- `buyers/detail.html` (banner al agente): «… crea su búsqueda: así entra en la cola y todo
  queda en el seguimiento» → «… crea su búsqueda y gestiónala ahora mismo: todo queda en el
  seguimiento».
- Flash tras crear (agente), `create_alert`: mantener «Ábrela para tomar su perfil de búsqueda»
  (ya invita a gestionarla); revisar que no mencione la cola.
- `alerts/list.html` confirm de reactivar («Volverá a la cola del agente»): se deja (reactivar
  es admin y la alerta vuelve con normalidad; si estaba `self_created` sigue estándolo, es
  coherente con D4 porque no cambia de agente).

### 4.5 Tests

- `tests/test_alert_view.py`: agente con una alerta anterior sin gestionar + una creada por él
  (`self_created=True`) → la suya no está en `get_locked_alert_ids`; una de administración
  posterior a la suya sin gestionar no queda bloqueada por la suya (D1), pero sí por la anterior
  de administración sin gestionar.
- `tests/test_buyer_detail_work_alert.py` (`test_el_agente_crea_la_busqueda_y_va_a_la_alerta`):
  nuevo test con una alerta anterior sin gestionar → el agente crea la búsqueda y **abre** la
  nueva (200, no rebota); la alerta tiene `self_created=True`. Mismo caso desde el modal de
  `/alerts` con propiedad propia.
- `tests/test_alert_assignment.py`: reasignar (admin) y ceder ponen `self_created=False` y la
  alerta entra en la cola del nuevo agente.
- Migración: probada en local con upgrade, downgrade -1 y upgrade (backfill sobre una alerta
  creada por un agente y una de administración).

### 4.6 Documentación

- Nota en «Estado» de `PLAN_ALERTA_COMO_NUEVA.md` y en `PLAN_ASIGNACION_ALERTAS.md` §2.5
  remitiendo aquí. `MULTIEMPRESA_MOYZA_MOES.md` §15: `alembic upgrade head` + reinicio.

## 5. Fases

1. Modelo + migración + `assign` + cola + textos + tests (un agente).
2. Revisión del diff y suite completa.

### Estado

- [x] Fase 1 (2026-11-27)
- [x] Fase 2 (2026-11-27): diff revisado sin defectos. Suite completa 1541 pasan (más los 24 de `test_commercial_results`, `test_company_isolation` y `test_property_review_*` repetidos en verde tras limpiar datos que dejó una ejecución interrumpida; los dos fallos ajenos conocidos deseleccionados, `test_scheduler` ignorado).

Fase 1, hecho:

- `models/property_alert.py`: columna `self_created` (Boolean, NOT NULL, `server_default
  false`). Migración `t6u7v8w9x0y1_alert_self_created.py` (sobre `s5t6u7v8w9x0`) con el
  backfill de §4.1 y downgrade que borra la columna.
- `alert_assignment_service.py`: nueva `is_self_assignment(agent, by_user)` (email del agente
  = email del usuario, sin distinguir mayúsculas ni espacios, y el usuario no es admin).
  `assign()` pone `alert.self_created = is_new and is_self_assignment(...)`: en el alta lo
  calcula `assign` (no hace falta tocar `create_alert`); con `is_new=False` (reasignación,
  lote, cesión, baja de usuarios) siempre `False` (D4).
- `alert_view.get_locked_alert_ids`: filtra en Python las `self_created` de
  `agent_open_alerts_ordered` antes del recorrido. `agent_open_alerts_ordered` no cambia
  (además de aquí solo lo usan tests vía el alias `_get_agent_open_alerts_ordered`), así que el
  orden del listado sigue igual (D2). Siguen las dos consultas por empresa.
- `buyers/detail.html`: «crea su búsqueda y gestiónala ahora mismo: todo queda en el
  seguimiento». Los flashes de `create_alert` no mencionan la cola; el confirm de reactivar
  se deja (§4.4).
- Tests nuevos: `test_alert_view.py` (fuera de la cola + la posterior de administración solo
  bloqueada por la anterior de administración; el agente abre la suya con una anterior sin
  gestionar), `test_buyer_detail_work_alert.py` («Crear búsqueda» y modal de `/alerts` con
  propiedad propia se abren con una anterior sin gestionar; la que crea el admin para el
  agente sí queda en cola), `test_alert_assignment.py` (alta propia fuera de la cola;
  reasignar y ceder → `self_created=False` y bloqueada en la cola del nuevo agente).
- Migración probada en local con alertas temporales (una creada por el agente, una de
  administración y una del agente cerrada; solo la primera queda `true`): upgrade, downgrade
  y upgrade sin errores. Como la base local tiene la fila ajena `q3c4p5t6a7b8` (Captaciones),
  `alembic upgrade head` se niega; se aplicó el SQL offline (`alembic upgrade
  s5t6u7v8w9x0:head --sql | psql` y `downgrade t6u7v8w9x0y1:s5t6u7v8w9x0 --sql`), como en
  PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md. Filas temporales borradas.
- Tests: los tres archivos tocados 58 passed; `test_alert_search`, `test_unified_view_alerts`,
  `test_alerts_pagination`, `test_alert_assignment_routes` (sin el fallo conocido
  `test_agente_no_puede_elegir_agente`), `test_send_property`, `test_profile_required`,
  `test_property_matches_page`: 210 passed. Además `test_alert_cession` (25), cola en
  dashboard, atención y bajas (115, sin el fallo conocido del dashboard): todo en verde.

Desviación: el backfill excluye además a los usuarios con rol admin
(`lower(coalesce(roles.name, '')) <> 'admin'`), para que siga la misma regla que `assign()`
si un admin tuviera ficha de agente y se hubiera asignado una alerta a sí mismo.
