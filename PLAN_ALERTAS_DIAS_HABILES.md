# Plan: avisos de compradores en horas hábiles (calendario de Jaén) y aviso de "sin avance"

Fecha: 2026-10-18 · Rama `63-agregar-moes`

> **Prerrequisito:** hay trabajo sin commitear de otra sesión (PLAN_ALERTA_COMO_NUEVA.md,
> `services/alert_view.py`, cambios en `buyer_reminder_service.py`, `notification_service.py`,
> `dashboard_service.py`, `constants.py`, `property_alert.py`…). Este plan toca esos mismos archivos.
> **No ejecutar hasta que ese trabajo esté commiteado**, y el agente ejecutor debe partir de la versión
> commiteada (la "ventana de asignación" de `alert_view.py` es justo la base que necesita la regla nueva).

## 1. Qué avisos existen hoy sobre compradores (y qué no)

| Aviso | Regla | Canal | Cuándo | Archivo |
|---|---|---|---|---|
| **Recordatorio "sin gestión"** | Alertas en estado **`PENDING`** cuya última gestión (último seguimiento, o la creación/asignación si no hay) tiene más de **48 h de reloj** (`BUYER_REMINDER_HOURS`). | Email por agente y empresa, con tabla de compradores. Se repite **cada día** mientras siga igual (no hay "ya avisado"). | Todos los días a las 06:00 UTC, incluidos sábados, domingos y festivos. | `services/buyer_reminder_service.py`, `jobs/scheduler.py:92-108, 247-255` |
| Modal y "Hoy y pendiente" del Inicio (agente) y "Requiere atención" (admin) | La misma regla de 48 h. | En pantalla, al entrar al Inicio (modal una vez al día). | Al cargar `/dashboard`. | `services/dashboard_service.py:473, 747` |
| "Compradores abandonados" (admin) | `PENDING` con más de 7 días desde la asignación. | Inicio y Resultados Comerciales. | Al cargar. | `DashboardThresholds.ABANDONED_BUYER_DAYS` |
| Comprador asignado | Al asignar o reasignar a un agente distinto del captador. | In-app (campana). | En el momento. | `alert_assignment_service.py` |
| Seguimiento vencido | Seguimientos con `next_action_date` hoy o pasada. | In-app. | Job diario 08:00 Madrid. | `notification_service.py:330+` |

### 1.1 El hueco que explica lo que ves

- Al **abrir** una alerta, el agente asignado la marca leída y el estado pasa de `PENDING` a `IN_PROGRESS`
  (`routes/alerts.py:1079-1085`). El recordatorio solo mira `PENDING`
  (`REMINDER_STATUSES = ["PENDING"]`). Resultado: **basta con abrir la alerta para que no vuelva a avisar
  nunca**, aunque el comprador se quede semanas en "Primera llamada". En la base local hay 3 alertas
  `IN_PROGRESS` y 1 `PENDING`: el recordatorio solo vigila esa 1.
- Las 48 h son de reloj: una alerta creada el viernes a las 18:00 se reclama el domingo a las 18:00 y el
  email sale el lunes a las 06:00 UTC, igual que si hubiera llegado un martes.
- No hay noción de **etapa** en los avisos: `PRIMERA_LLAMADA → CONTACTADO → CALIFICADO → VISITA_PROGRAMADA →
  OFERTA` existe (`FollowUpActionType.STAGE_ORDER`), y "Sin respuesta" es una acción repetible que no avanza
  la etapa, pero nada avisa de que un comprador lleva N días sin avanzar.
- No hay calendario laboral en ningún sitio (ni librería ni tabla de festivos).

---

## 2. Diseño propuesto

### 2.1 Calendario hábil de Jaén

Módulo nuevo `app/core/business_calendar.py`:

- Librería `holidays` (python-holidays, disponible en el contenedor: `holidays==0.106`) con país `ES` y
  comunidad `AN` (Andalucía): festivos nacionales, autonómicos (28 de febrero, Jueves Santo) y los traslados
  al lunes que aprueba la Junta cada año. Se añade a `requirements.txt`.
- **Festivos locales de Jaén** (dos al año, los fija el Ayuntamiento): lista por año en
  `core/constants.py` (`LOCAL_HOLIDAYS = {2026: [...], 2027: [...]}`), con los dos de Jaén capital como
  valor inicial **a confirmar por el usuario** (§4-2). Opcional después: tabla y pantalla de admin.
- Días hábiles: **lunes a viernes** no festivos (§4-3), zona horaria `Europe/Madrid`.
- API:
  - `is_business_day(date) -> bool`
  - `add_business_hours(start: datetime, hours: int) -> datetime`: suma `hours` contando solo días hábiles
    completos (24 h por día hábil). "48 h hábiles" desde el viernes 18:00 vence el **martes 18:00**; desde el
    jueves 10:00, el **lunes 10:00** si el viernes es festivo. (Alternativa con horario de oficina en §4-1.)
  - `business_hours_between(start, end) -> float` para mostrar "lleva 2 d 5 h hábiles".
  - `next_business_day_at(hour) -> datetime` para programar el email.
- Tests sin BD: fin de semana, 1 de mayo, 28 de febrero, Jueves y Viernes Santo de 2026 y 2027, festivo
  local, traslado al lunes, cambio de hora (marzo/octubre).

### 2.2 Dos reglas, una base común

Ambas se calculan sobre la **ventana de asignación** (`alert_view.assignment_start`: `assigned_at` o
`created_at`) y solo para alertas **abiertas** (`PENDING` **e** `IN_PROGRESS`): abrir la alerta ya no apaga
los avisos (§4-4).

| Regla | Qué mide | Umbral | Ejemplo |
|---|---|---|---|
| **R1 · Sin gestión** (la de hoy, corregida) | Desde la última gestión real (`alert_view.real_follow_ups_clause`: excluye notas del sistema como `REASIGNADA`) o, si no hay, desde la asignación. | `BUYER_REMINDER_HOURS` = 48 **h hábiles** | Alerta asignada el viernes 12:00, nadie la toca → vence el martes 12:00. |
| **R2 · Sin avance de etapa** (nueva) | Desde el último seguimiento que **avanzó la etapa** (`STAGE_ORDER` ≥ 1, no repetible) o, si no hay ninguno, desde la asignación. "Sin respuesta" **no** reinicia este reloj. | `BUYER_STAGE_STALL_HOURS` = 48 h hábiles (§4-5) | Comprador en "Primera llamada" con tres "sin respuesta" en una semana: R1 no salta (hay gestión), **R2 sí**: "4 días hábiles sin avanzar de Primera llamada". |

Servicio nuevo `services/buyer_attention_service.py` (sustituye a `get_pending_buyers_by_agent`, que pasa a
ser un envoltorio para no romper el Inicio ni el email):

```python
@dataclass
class BuyerAttention:
    alert: PropertyAlert
    rule: Literal["no_action", "stage_stall"]
    since: datetime             # desde cuándo corre el reloj
    due_at: datetime            # since + umbral en horas hábiles
    business_hours_elapsed: float
    stage_label: str | None     # "Primera llamada" (R2)

def find_buyers_needing_attention(db, company_id=None, agent_id=None, now=None) -> list[BuyerAttention]
```

Una alerta puede cumplir R1 y R2 a la vez; se muestra una sola fila con la causa más grave (R1 primero).

### 2.3 Canales (§4-6 y §4-7)

| | R1 · Sin gestión | R2 · Sin avance |
|---|---|---|
| Email diario (el actual) | Sí. Una sección "Sin gestión". | Sí, **dentro del mismo email**, sección "Sin avance de etapa". No se envía un segundo correo. |
| In-app (campana + `/notifications`) | `BUYER_NO_ACTION`: una notificación **al cruzar el umbral** y otra **cada 2 días hábiles** mientras siga igual (dedupe por alerta + regla + fecha de vencimiento). | `BUYER_STAGE_STALL`, misma cadencia. |
| Inicio agente (modal + "Hoy y pendiente") | Sí (ya existe). | Sí, con la etapa: "3 d hábiles en Primera llamada". |
| Inicio admin ("Requiere atención") | Sí, agrupado por agente. | Sí. |
| Listado `/alerts` y detalle | Badge ámbar "48 h hábiles sin gestión" / "Sin avance: 3 d hábiles en Primera llamada" en la fila, y en el detalle la fecha de vencimiento ("vence el martes 12:00"). | Igual. |

Email solo en **días hábiles a las 08:00 Madrid** (hoy 06:00 UTC todos los días): el job comprueba
`is_business_day(hoy)` y, si no lo es, no envía (§4-8). Nada de WhatsApp.

### 2.4 Qué cambia para el usuario final

- Un comprador que llega el viernes por la tarde no genera reclamación el fin de semana ni el lunes festivo.
- Abrir la alerta ya no "silencia" al comprador: hay que registrar una gestión (R1) y hacerla avanzar (R2).
- El email de las mañanas lista las dos cosas por separado y solo llega en días hábiles.
- En el listado se ve de un vistazo cuánto lleva cada comprador en horas hábiles y cuándo vence.

---

## 3. Fases

Un commit por fase: `feat(compradores): fase N - avisos en horas hábiles …`. Skill `moyza-ui-ux-pro` en lo visual.

### Fase 1 · Calendario hábil
- [ ] `holidays` en `requirements.txt` (+ `pip install` en el contenedor; recordar rebuild de imagen en producción).
- [ ] `core/business_calendar.py` (§2.1), `LOCAL_HOLIDAYS` en `constants.py`, `BUYER_STAGE_STALL_HOURS` y
      `BUYER_REMINDER_REPEAT_BUSINESS_DAYS` en `config.py`.
- [ ] `tests/test_business_calendar.py`.

### Fase 2 · Servicio de atención y reglas
- [ ] `services/buyer_attention_service.py` (§2.2) usando `alert_view` (ventana de asignación, seguimientos reales).
- [ ] `get_pending_buyers_by_agent` delega en el servicio nuevo (misma forma de salida + campos nuevos
      `rule`, `due_at`, `business_hours_elapsed`, `stage_label`).
- [ ] `REMINDER_STATUSES` pasa a incluir `IN_PROGRESS`.
- [ ] Tests: R1 con fin de semana por medio; R2 con "sin respuesta" repetidos; alerta reasignada arranca de
      cero; nota `REASIGNADA` no cuenta; alerta cerrada no aparece; empresa aislada.

### Fase 3 · Canales
- [ ] Email: dos secciones, horas hábiles en la columna "Sin gestión", solo días hábiles a las 08:00 Madrid
      (`jobs/scheduler.py`: cron con `timezone="Europe/Madrid"` y comprobación de día hábil).
- [ ] Notificaciones in-app `BUYER_NO_ACTION` y `BUYER_STAGE_STALL` con la cadencia de §2.3; job que las
      genera a continuación del email (misma pasada, para no duplicar consultas).
- [ ] Inicio (agente y admin): la lista y el modal incluyen R2 con la etapa; textos en horas/días hábiles.
- [ ] `/alerts` y detalle: badge y "vence el …".
- [ ] Tests de las notificaciones (dedupe y cadencia) y de ruta del listado.

### Fase 4 · QA y despliegue
- [ ] Prueba con fecha simulada (`now` inyectable en el servicio y en el job) cubriendo viernes → martes y un festivo.
- [ ] `ui_lint.py`; revisión móvil.
- [ ] Nota de despliegue en `MULTIEMPRESA_MOYZA_MOES.md`: nueva dependencia (rebuild), variables nuevas, el job
      cambia de hora y de calendario, y **los agentes van a recibir avisos de alertas `IN_PROGRESS` que hasta
      ahora estaban en silencio** (avisar al equipo el día del despliegue).

### Criterios de aceptación
1. Una alerta asignada el viernes a las 12:00 no se reclama hasta el martes a las 12:00; si el lunes es festivo en Jaén, hasta el miércoles.
2. Abrir la alerta no detiene los avisos; registrar una gestión real detiene R1; avanzar de etapa detiene R2.
3. El email diario sale solo en días hábiles a las 08:00 Madrid, con las dos secciones.
4. La campana avisa una vez al cruzar el umbral y de nuevo cada 2 días hábiles, sin duplicados.
5. Inicio, listado y detalle muestran la causa, la etapa y el vencimiento en horas hábiles.

---

## 4. Preguntas antes de ejecutar

| # | Pregunta | Recomendación |
|---|---|---|
| 1 | **Qué son "48 h hábiles"**: (a) dos días hábiles completos a la misma hora (viernes 18:00 → martes 18:00), o (b) horas de oficina, por ejemplo 9:00-20:00 de lunes a viernes (48 h = unas 4,4 jornadas)? | (a): más simple de explicar y de ver en el listado |
| 2 | **Festivos locales de Jaén**: ¿los de Jaén capital para las dos empresas? Mi dato, **a confirmar**: 11 de junio (Virgen de la Capilla) y 18 de octubre (San Lucas). ¿Hay agentes en otros municipios con festivos distintos? | Jaén capital para todos; lista en configuración por año |
| 3 | **Sábado**: ¿día hábil o no? | No hábil (lunes a viernes) |
| 4 | **Alertas ya abiertas (`IN_PROGRESS`)**: confirmas que los avisos deben seguir aunque el agente haya abierto la alerta. Hoy abrirla los apaga. | Sí, seguir |
| 5 | **Regla "sin avance" (R2)**: ¿48 h hábiles para **cualquier** etapa, o solo cuando está en la primera ("Primera llamada")? ¿Mismo umbral que R1? | Cualquier etapa, mismo umbral; se puede afinar por etapa después |
| 6 | **Canal de R2**: in-app + Inicio + sección en el email diario que ya existe (sin correo nuevo). ¿O solo in-app, sin email? | In-app + sección en el email existente |
| 7 | **Cadencia in-app**: una notificación al cruzar el umbral y otra cada 2 días hábiles mientras siga igual. ¿Vale, o solo una vez? | Al cruzar y cada 2 días hábiles |
| 8 | **Email solo en días hábiles** a las 08:00 Madrid (hoy todos los días a las 06:00 UTC). ¿De acuerdo? | Sí |
| 9 | **Admin**: ¿solo lo ve en "Requiere atención" del Inicio (como hoy), o también quiere el email diario con el resumen de todos los agentes? | Solo Inicio |

---

## 5. Brief para el agente ejecutor

> Implementa `PLAN_ALERTAS_DIAS_HABILES.md` por fases, un commit por fase, sin push, con el skill
> `moyza-ui-ux-pro` en lo visual. Antes de empezar comprueba con `git status` que no hay cambios sin
> commitear en `services/`, `core/` ni `routes/alerts.py`; si los hay, para y repórtalo. Lee primero
> `services/alert_view.py` (ventana de asignación y seguimientos reales), `services/buyer_reminder_service.py`,
> `services/notification_service.py`, `services/dashboard_service.py` (usos de `get_pending_buyers_by_agent`),
> `jobs/scheduler.py`, `core/config.py`, `core/constants.py` (`FollowUpActionType`, `DashboardThresholds`),
> `routes/alerts.py` (listado, detalle, auto-lectura), `templates/alerts/list.html`, `alerts/detail.html`,
> `dashboard/*`, `MULTIEMPRESA_MOYZA_MOES.md`. Respeta las decisiones de §4. El servicio y el job deben aceptar
> `now` inyectable para los tests. Reporta la salida real de pytest y ui_lint y el resultado de una ejecución
> del job con fecha simulada de viernes y de festivo.
