# Plan: asignar la alerta de comprador a un agente distinto del de la propiedad

Fecha: 2026-10-13 · Rama `63-agregar-moes`

## 1. Cómo funciona hoy el flujo alerta ↔ propiedad ↔ agente

### 1.1 Asignación

| Punto | Comportamiento actual | Archivo |
|---|---|---|
| Crear alerta (modal "Nueva alerta" en Compradores y formulario rápido en la ficha del comprador) | `agent_id = property_item.agent_id`, **siempre** el agente captador de la propiedad. Si la propiedad no tiene agente, se rechaza ("La propiedad no tiene agente asignado"). | `routes/alerts.py::create_alert` (~línea 919 y 947) |
| Quien la crea | Admin sobre cualquier propiedad. **Agente solo sobre sus propiedades asignadas** (cambio del 2026-10-16): el buscador del modal y la ficha del comprador solo le ofrecen las suyas, y `create_alert` rechaza cualquier otra con "Solo puedes crear alertas sobre las propiedades que tienes asignadas". Así la alerta siempre queda a su nombre. | `routes/alerts.py::search_properties`, `::create_alert`; `buyers/detail.html` |
| Reasignar después | **No existe.** No hay ninguna acción para cambiar el agente de una alerta ya creada. | |
| Modelo | `property_alerts.agent_id` (FK `agents`, NOT NULL). No guarda quién asignó ni cuándo. | `models/property_alert.py:27` |

### 1.2 Quién ve y trabaja la alerta (todo depende de `alert.agent_id`)

| Uso | Regla | Archivo |
|---|---|---|
| Listado `/alerts` del agente | `PropertyAlert.agent_id == su agente`, dentro de la empresa activa (`scope_alerts` por la empresa de la propiedad). | `routes/alerts.py:233-245` |
| Detalle, marcar leída, seguimientos, reactivar | Solo si `alert.agent_id == su agente` (admin siempre). | `routes/alerts.py:760, 780, 1006, 1061, 1218` |
| Cola secuencial (una alerta sin seguimiento bloquea las siguientes) | Por agente **y por empresa**, ordenada por `created_at`. | `routes/alerts.py:85-110, 174-200` |
| Acceso al comprador | El agente accede a un comprador si tiene alguna alerta suya (entre otros criterios). | `routes/alerts.py::can_access_buyer` |
| Recordatorio email 48 h y modal del Inicio | Agrupa por `(alert.agent_id, empresa de la propiedad)`. | `services/buyer_reminder_service.py:93` |
| Resultados Comerciales: contactos venta/alquiler y cierres | Cuentan por `PropertyAlert.agent_id` y la empresa de la propiedad. | `services/performance_report_service.py:376, 400` |
| Inicio: KPIs, agenda, "sin actividad", tendencia | Por `PropertyAlert.agent_id`. | `services/dashboard_service.py` |
| Notificación de seguimiento vencido | Al `alert.agent`. | `services/notification_service.py:343` |
| Pestaña Compradores de Resultados Comerciales | Por `alert.agent_id`. | `routes/commercial_results.py:109` |

Conclusión: cambiar `agent_id` basta para que **todo** (lista, cola, recordatorios, métricas, Inicio) siga al
nuevo agente. No hay ningún sitio que vuelva a mirar `property.agent_id` para decidir de quién es la alerta.
Lo que falta es: (1) poder elegir el agente al crear, (2) poder reasignar después, (3) dejar rastro,
(4) avisar al nuevo agente, y (5) resolver el caso del agente de la otra empresa.

### 1.3 El problema multiempresa

La alerta hereda la empresa de la propiedad. Un agente solo ve la empresa (o empresas) a las que pertenece
(`agent_companies`, selector del sidebar). Si una alerta de una propiedad **MOYZA** se asigna a un agente que
solo está en **MOES**, hoy ese agente **no la vería nunca**: ni en su lista, ni en la campana, ni en el
recordatorio del Inicio (el email sí le llegaría, porque el email no pasa por el selector de empresa).
Ver decisión §4-1.

---

## 2. Diseño propuesto

### 2.1 Elegir el agente al crear la alerta

En los dos formularios (modal "Nueva alerta" y formulario rápido de la ficha del comprador):

- Al seleccionar la propiedad, aparece el bloque **"Agente asignado"** con un select ya **preseleccionado con
  el agente de la propiedad** y la nota "Agente de la propiedad". El autocompletado de propiedades ya devuelve
  el nombre del agente; se amplía para devolver también su id.
- Si se elige otro agente, el bloque cambia a aviso ámbar: "La alerta irá a **{agente}** y no a {captador},
  agente de la propiedad" y aparece un campo **"Motivo"** (texto corto, obligatorio solo cuando el agente es
  distinto del captador; ejemplos en placeholder: "Carga de trabajo", "Sin respuesta").
- Lista de agentes del select: ver decisión §4-1. Agrupada por empresa con `<optgroup>` como en el acompañante
  de visitas (MOYZA · MOYZA, MOES PREMIUM · MOES PREMIUM).
- Quién puede elegir: ver decisión §4-2. Por defecto solo el admin ve el select; el agente sigue viendo
  "Se asignará a {captador}" como texto.
- Propiedad sin agente: deja de ser un bloqueo si se elige agente explícitamente (decisión §4-7).
- Backend `create_alert`: nuevo campo `agent_id` (opcional; si falta → captador). Validación en servidor:
  agente existente, permitido según §4-1 y §4-2; motivo obligatorio si difiere del captador. Se guardan
  `assigned_by`, `assigned_at` y se registra en el historial (§2.3). Flash: "Alerta creada para {comprador} y
  asignada a {agente}".

### 2.2 Reasignar una alerta existente

- En el **detalle de la alerta** (solo admin, y solo si está abierta: `PENDING` / `IN_PROGRESS`), junto al
  nombre del agente: botón **"Reasignar"** que abre un modal con el select de agentes (misma lista y
  agrupación que en el alta), motivo obligatorio y confirmación.
- Ruta nueva `POST /alerts/{alert_id}/reassign` (`agent_id`, `reason`). Efectos:
  - `alert.agent_id = nuevo`, `assigned_by`, `assigned_at = ahora`, `previous_agent_id`.
  - `read_at = NULL` y, si estaba `IN_PROGRESS` sin seguimientos, vuelve a `PENDING`: para el nuevo agente es
    una alerta nueva. Los seguimientos existentes se conservan (son historial del comprador).
  - Entrada en el historial (§2.3) y nota automática en los seguimientos: "Reasignada de {A} a {B} por {admin}:
    {motivo}" (tipo de acción nuevo `REASIGNADA`, que **no** avanza etapa, como `SIN_RESPUESTA`).
  - Notificación in-app `alert_assigned` al nuevo agente (§2.4).
- En el listado `/alerts` del admin: acción de fila "Reasignar" (mismo modal) para no entrar al detalle.
  Reasignación en lote (seleccionar varias → un agente) queda como opcional (§4-4).

### 2.3 Rastro

Columnas nuevas en `property_alerts`: `assigned_by` (FK users, nullable), `assigned_at` (datetime),
`previous_agent_id` (FK agents, nullable), `assignment_reason` (String, nullable).
Tabla nueva `alert_assignment_logs` (`alert_id`, `from_agent_id`, `to_agent_id`, `assigned_by`, `reason`,
`created_at`) para conservar el historial completo cuando hay más de una reasignación. Migración
`v5w6x7y8z9a0`, `down_revision = 'u4v5w6x7y8z9'`. Backfill: `assigned_at = created_at`,
`assigned_by = created_by`, sin log (las alertas actuales nunca se reasignaron).

El detalle de la alerta muestra "Asignada a {agente} · por {usuario} el {fecha}" y, si hubo cambios,
"Antes: {agente anterior}" con el historial desplegable.

### 2.4 Avisos (sin spam)

- Notificación in-app `alert_assigned` al agente nuevo (ya estaba en el catálogo del Inicio, sin implementar):
  título "Te han asignado un comprador: {nombre}", cuerpo "{propiedad} · {motivo}", enlace al detalle.
  (2026-10-16, decisión §4-10: el cuerpo es solo "{propiedad}"; el motivo no se envía al agente.)
  Se emite en el alta solo cuando el agente **no** es el captador, y siempre en la reasignación.
- Al agente anterior: nada (decisión §4-5).
- Ningún email ni WhatsApp.

### 2.5 Cola secuencial, recordatorios y métricas

- **Cola**: una alerta reasignada entra en la cola del nuevo agente ordenada por `assigned_at` (no por
  `created_at`), para que una alerta antigua no se cuele delante de las suyas ni le bloquee de inmediato.
  `_get_agent_open_alerts_ordered` pasa a ordenar por `coalesce(assigned_at, created_at)`.
- **Recordatorio 48 h**: el reloj de "última gestión" se reinicia con `assigned_at` (se usa
  `greatest(último seguimiento, assigned_at, created_at)`), para no reclamar al nuevo agente por tiempo del anterior.
- **Métricas**: "contactos" cuentan para el agente que tiene la alerta en el momento de contar (período por
  `created_at`). Es decir, al reasignar, el contacto pasa al nuevo agente. Los cierres ya se atribuyen a
  `alert.agent_id` en el momento del cierre. Decisión §4-6 confirma o cambia esto.

### 2.6 Multiempresa

Según la decisión §4-1. Con la opción recomendada (B):

- El select ofrece agentes de **ambas** empresas.
- Si el agente elegido no pertenece a la empresa de la propiedad, al confirmar se le añade a esa empresa
  (`add_to_company`, lo mismo que hace el admin desde la ficha del agente) y se avisa en el propio formulario
  antes de guardar: "Carlos no pertenece a MOYZA; al asignarle se le dará acceso a MOYZA".
- En el listado `/alerts` del agente aparece un banner cuando tiene alertas abiertas asignadas en **otra**
  empresa a la que sí tiene acceso: "Tienes 2 compradores asignados en MOES PREMIUM · Cambiar a MOES PREMIUM"
  (enlace que hace el `switch-company`). Así no depende de que se acuerde de cambiar.
- La campana del Inicio sigue siendo por empresa activa; la notificación `alert_assigned` se crea en la empresa
  de la propiedad y se ve al cambiar.

---

## 3. Fases de implementación

Un commit por fase: `feat(alertas): fase N - …`. Usar el skill `moyza-ui-ux-pro` en todo lo visual.

### Fase 1 · Modelo, migración y servicio
- [ ] Columnas y tabla de §2.3, modelo `AlertAssignmentLog`, relaciones en `PropertyAlert`
      (`assigned_by_user`, `previous_agent`, `assignment_logs`).
- [ ] `services/alert_assignment_service.py`: `assignable_agents(db, company_id)` (lista agrupada según §4-1),
      `validate_assignment(...)`, `assign(db, alert, agent, by_user, reason, *, is_new)` (aplica §2.2 y §2.6,
      escribe log, nota de seguimiento y notificación). Puro y testeable como `visit_agents.py`.
- [ ] `FollowUpActionType.REASIGNADA` (no avanza etapa; etiqueta y color en el mapa de estados).
- [ ] `NotificationKind.ALERT_ASSIGNED` + plantilla de título/cuerpo.
- [ ] Tests unitarios del servicio: captador por defecto, motivo obligatorio si difiere, agente de otra
      empresa según §4-1, reset de `read_at`/estado, log y nota, no notificar si es el captador.

### Fase 2 · Elegir agente al crear
- [ ] `search_properties` devuelve `agent_id`.
- [ ] Modal "Nueva alerta" (`alerts/list.html`) y formulario rápido (`buyers/detail.html`): bloque "Agente
      asignado" con select agrupado, aviso ámbar y motivo (JS: mostrar motivo solo si difiere del captador).
- [ ] `create_alert`: campo `agent_id` + `assignment_reason`, validación, uso del servicio, flash.
- [ ] Tests de ruta: alta sin agente → captador; con otro agente sin motivo → rechazada; con motivo → asignada,
      log, notificación al nuevo y no al captador; agente no admin según §4-2.

### Fase 3 · Reasignar existentes
- [ ] `POST /alerts/{id}/reassign` + modal en detalle y acción de fila en listado (admin).
- [ ] Detalle: bloque "Asignada a … por … el …", historial desplegable, nota automática en seguimientos.
- [ ] Cola por `assigned_at`, recordatorio 48 h desde `assigned_at` (§2.5) con tests de `get_locked_alert_ids`
      y `get_pending_buyers_by_agent`.
- [ ] Tests de ruta: solo admin; solo abiertas; reset de estado; el agente anterior deja de verla y el nuevo la ve.

### Fase 4 · Multiempresa y avisos
- [ ] Según §4-1: alta automática en la empresa (B) o restricción (A) o visibilidad por asignación (C).
- [ ] Banner "compradores asignados en otra empresa" en `/alerts` del agente (B y C).
- [ ] Test de aislamiento: agente solo-MOES recibe alerta MOYZA y puede trabajarla; nada más de MOYZA se expone
      de lo que la opción elegida permita.

### Fase 5 · QA y despliegue
- [ ] `ui_lint.py` sobre plantillas tocadas; revisión en móvil y escritorio con `fetch_page.py`.
- [ ] Nota de despliegue en `MULTIEMPRESA_MOYZA_MOES.md` (§9): `alembic upgrade head` + reinicio.

### Criterios de aceptación
1. Al crear una alerta el admin puede elegir cualquier agente; por defecto queda el captador y sin motivo no se puede cambiar.
2. La alerta aparece solo en la lista del agente asignado, con su cola, recordatorio y métricas.
3. Una alerta abierta se puede reasignar desde el detalle y desde el listado; queda historial y nota en seguimientos.
4. El nuevo agente recibe una notificación in-app; nadie recibe email ni WhatsApp.
5. Un agente de la otra empresa puede recibir y trabajar la alerta según la opción elegida en §4-1.
6. Las alertas existentes no cambian de agente ni de orden en la cola tras la migración.

---

## 4. Decisiones tomadas (2026-10-13)

| # | Pregunta | Decisión |
|---|---|---|
| 1 | Agente de la otra empresa | **B.** Cualquier agente; si no pertenece a la empresa de la propiedad, al asignarle se le añade a esa empresa (`add_to_company`). Aviso en el formulario antes de confirmar y banner "compradores asignados en otra empresa" en `/alerts`. |
| 2 | Quién elige el agente al crear | **Solo el admin.** El agente sigue viendo "Se asignará a {captador}" como texto. |
| 3 | Reasignar alertas ya creadas | **Sí**, desde el detalle y desde el listado; solo admin y solo abiertas. |
| 4 | Reasignación en lote | **Después.** No entra en esta versión. |
| 5 | Avisos | **Solo al nuevo agente**, in-app. |
| 6 | Métricas | **Pasan al nuevo agente.** |
| 7 | Propiedad sin agente captador | **Sí**, se puede crear la alerta si se elige agente explícitamente. |
| 8 | Motivo | **Texto libre corto y OPCIONAL** (un solo input, placeholder "Motivo (opcional)"). Sin lista fija. Se guarda en `assignment_reason` y, si hay texto, en la nota automática de seguimiento. |
| 9 | Estado al reasignar | **Correcto**: Pendiente y sin leer, conservando seguimientos. |
| 10 | Qué ve el agente de una alerta reasignada y cola (2026-10-16, `PLAN_ALERTA_COMO_NUEVA.md`) | **El agente ve la alerta reasignada como nueva; el admin conserva la trazabilidad; bloqueo real de la cola.** Para el agente todo se calcula desde `assigned_at` (o `created_at`): sin bloque "Agente asignado", sin notas `REASIGNADA` ni seguimientos/etapa del agente anterior, fecha = la de su asignación, y en la cola cuenta como sin gestionar hasta que él registre un seguimiento (cerrar también lo exige, para ambos roles). Una alerta bloqueada no se abre por ningún camino: `/alerts/{id}` vuelve a `/alerts` con el aviso "Esta alerta está en tu cola. Gestiona primero las anteriores para verla." sin tocar estado ni `read_at`. El admin lo ve todo (creación y asignación por separado). El aviso `alert_assigned` ya no lleva el motivo. No cambia nada de lo que se guarda (historial, nota, agente anterior y motivo siguen en BD). Lógica en `services/alert_view.py`. |
| 11 | Alerta sin referencia (búsqueda general) (2026-10-16, `PLAN_ALERTA_SIN_REFERENCIA.md`, decisiones en `docs/DECISIONES_ALERTAS_BUSQUEDA.md`) | **La propiedad es opcional.** Alerta `origin='search'` con empresa propia (`property_alerts.company_id`); el admin elige el agente (obligatorio, no hay captador) y el agente queda asignado a sí mismo. Una sola alerta: la propiedad elegida se asocia a esa misma alerta y se puede cambiar; **el agente que atiende la conserva** aunque la propiedad sea de otro agente (no hay reasignación al asociar ni aviso al captador). `scope_alerts` y la cola pasan a filtrar por `PropertyAlert.company_id`. El aviso `alert_assigned` de una búsqueda dice "Búsqueda general · {operación}". |
| 12 | Perfil y propuesta en todas las alertas; perfil obligatorio al contactar (2026-10-19, `PLAN_PERFIL_OBLIGATORIO.md`, decisiones en `docs/DECISIONES_ALERTAS_BUSQUEDA.md` §5) | **El origen deja de condicionar el flujo**: todas las alertas tienen Contactar → Perfil → Propuesta y "Cambiar propiedad" (sin cambiar `agent_id`). **Perfil mínimo** = tipo + precio máximo + zona o ciudad (`buyer_matching.profile_is_complete`). El seguimiento **Contactado** lleva el perfil dentro; sin perfil completo no se registran Visita programada, Oferta ni Cerrado (éxito) ni se asocia/cambia propiedad (validado en servidor). Sin respuesta y cierres negativos, sin perfil. Primer perfil completo = un `CONTACTADO`; ediciones = `PERFIL_GUARDADO`. Alertas sin comprador, fuera del requisito. Admin: chip "Sin perfil" en `/alerts`. |

Ajustes derivados: en §2.1 y §2.2 el motivo deja de ser obligatorio (la validación solo exige agente válido);
el aviso ámbar "La alerta irá a X y no a Y" se mantiene. Las alertas con motivo vacío no muestran la línea
"Motivo" en el detalle.

---

## 5. Brief para el agente ejecutor

> Implementa `PLAN_ASIGNACION_ALERTAS.md` por fases, un commit por fase, sin push, con el skill
> `moyza-ui-ux-pro` en todo lo visual. Lee primero `routes/alerts.py` entero (creación, listado, detalle, cola
> secuencial, `can_access_buyer`), `models/property_alert.py`, `models/alert_follow_up.py`,
> `services/buyer_reminder_service.py`, `services/notification_service.py`, `services/performance_report_service.py`
> (atribución de contactos y cierres), `services/dashboard_service.py` (usos de `PropertyAlert.agent_id`),
> `services/company_scope.py` (`add_to_company`, `scope_agents`), `services/visit_agents.py` (referencia de
> servicio puro + select agrupado por empresa), `templates/alerts/list.html` (modal y autocompletado),
> `templates/alerts/detail.html`, `templates/buyers/detail.html` (formulario rápido), `templates/visits/agents_fields.html`
> (optgroups por empresa), `MULTIEMPRESA_MOYZA_MOES.md`, y la última migración `u4v5w6x7y8z9`. Respeta las
> decisiones de §4. Ningún email ni WhatsApp. Aplica la migración y corre tests y `ui_lint.py` en el contenedor
> y reporta la salida real.
