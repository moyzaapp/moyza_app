# Plan: Inicio (Dashboard) por rol, notificaciones in-app e indicadores de agentes

Fecha: 2026-10-08 · Depende de: `PLAN_VISITAS_AGENTES.md` (hecho, commits a178761..442ef04) y de
`PLAN_RESULTADOS_COMERCIALES.md` (objetivos por tipo de período, período anual, desglose venta/alquiler y
métricas por empresa). **Orden de ejecución: Resultados Comerciales primero, luego este plan.**

## 1. Situación actual

| Qué | Estado | Archivo |
|---|---|---|
| Ruta `/dashboard` | Solo admin. Plantilla con una tarjeta fija "Clientes 120" (dato inventado). | `backend/app/web/routes/dashboard.py`, `templates/dashboard/home.html` |
| Login | Redirige siempre a `/dashboard`. Un **agente** cae en `require_admin_role`, que lo manda a `/clients` con el flash "Acceso denegado". Es decir, cada agente ve un error al entrar. | `routes/auth.py:135`, `dependencies/auth.py:51-70` |
| Sidebar | Entrada "Dashboard" solo para admin. Hay además "Dashboard Compradores" (`/alerts-dashboard`, con pestañas general / rendimiento) y "Reportes de Rendimiento" (`/performance-reports`). | `templates/components/sidebar.html` |
| Indicadores de agente | Ya existen y están bien resueltos: `PerformanceReportService.calculate_metrics` (contactos venta/alquiler, bajadas, captaciones CRM, cierres, hojas de visita) + objetivos por período (`agent_performance_targets`) + snapshot congelado al cerrar período (`agent_performance_reports`). Semana/mes. Solo los ve el admin. | `services/performance_report_service.py`, `templates/alerts/performance_report.html` |
| Notificaciones | No existe el concepto. Lo más parecido: badge de compradores no leídos en el sidebar (`/api/alerts/unread-count`, sondeo cada 2 min). | `sidebar.html:289-311` |
| Gráficas | Ninguna librería. Tailwind servido en local (`static/js/tailwind.js`). Barras de progreso en CSS en el reporte de rendimiento. | `static/js/` |
| Código duplicado | La lógica de período (`_parse_period`, navegación prev/next, snapshot vs. cálculo en vivo) está copiada en `routes/performance_reports.py` y en `routes/alerts.py::alerts_dashboard`. | |

Fuentes de datos ya disponibles para el Inicio (todas con `created_at` y agente, filtrables por empresa activa):
visitas (`property_visits`), compradores/alertas (`property_alerts` con `status`, `priority`, `read_at`, `agent_id`),
seguimientos (`alert_follow_ups` con `action_type`, `next_action_date`), propiedades (`status`, `market_entry_date`,
`agent_id`), bajadas de precio (`property_price_history`), envíos WhatsApp de fichas (`visit_whatsapp_logs`),
objetivos y snapshots de rendimiento.

---

## 2. Objetivo y principios

Una sola página de **Inicio** en `/dashboard`, accesible a **todos los roles**, que responde en 5 segundos
a tres preguntas: *¿qué pasó que me afecta?*, *¿cómo voy contra mis metas?*, *¿qué tengo que hacer hoy?*
El contenido cambia por rol; la estructura y el lenguaje visual son los mismos.

Principios:
1. **Cero spam.** Las notificaciones viven solo dentro de la app (campana + Inicio). Nada de email ni WhatsApp.
2. **Una fuente de verdad por métrica.** Los indicadores se calculan con `PerformanceReportService`; el Inicio no reinventa fórmulas.
3. **Todo por empresa activa.** Un agente de las dos empresas ve el Inicio de la empresa activa.
4. **Rápido.** Una sola carga server-side; las consultas se agrupan y se limitan al período. Sin sondeos salvo la campana (reutiliza el patrón del badge de compradores).
5. **Vacíos con intención.** Cada bloque tiene estado vacío con acción sugerida ("Aún no tienes visitas esta semana · Registrar visita").

---

## 3. Diseño visual

### 3.1 Lenguaje visual

**Manda el skill del proyecto `.claude/skills/moyza-ui-ux-pro`** (`references/tokens.md`, `components.md`,
`charts.md`, `ux-rules.md`). Lo que sigue es un resumen; ante cualquier diferencia, gana el skill.

- Tarjetas `bg-white rounded-2xl border border-gray-200` sin sombra, `p-4 sm:p-6`; títulos `text-gray-900`, metadatos `text-gray-500`.
- Botón primario oscuro neutro (`bg-gray-900`), uno por bloque. Acciones de fila en tono suave.
- La marca (`brand_color`) solo en franja del sidebar, avatar y punto junto al nombre. **No** en botones ni en series de gráficas.
- Semáforo de cumplimiento (tokens.md): `≥100 %` verde, `60-99 %` **ámbar**, `<60 %` **rojo**. Sin objetivo = gris. Aviso = `amber`, nunca `yellow`.
- Series de gráficas (charts.md): venta `#2563EB`, alquiler `#F59E0B`, otros `#9CA3AF`, objetivo `#111827` discontinuo.
- KPI: macro `kpi_card` de `assets/ui_macros.html` (copiar a `components/ui_macros.html` si aún no está). Máximo 4 por fila.
- Iconografía: Heroicons outline 24, `stroke-width="1.5"`, un icono por tipo de evento en el feed. Nada de emojis como icono (los de los bocetos de abajo son solo orientativos).
- Datos a JS con `{{ valor | tojson }}` en `<script type="application/json">`; tabla de respaldo bajo cada gráfica.
- Antes de cerrar cada fase: `python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates` y revisión con `scripts/fetch_page.py`.
- Tipografía numérica grande para KPIs (`text-3xl font-bold`), con **delta vs. período anterior** (`▲ 3` verde / `▼ 2` rojo / `=` gris).
- Responsive móvil-primero: en móvil las tarjetas apilan en una columna; la rejilla de KPIs pasa a 2 columnas.

### 3.2 Inicio del AGENTE

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Hola, Laura 👋                                    [Semana ▾] ◀ 6–12 oct ▶     │
│ MOYZA · miércoles 8 de octubre                          ● En curso           │
├──────────────┬──────────────┬──────────────┬──────────────┬──────────────────┤
│ Hojas visita │ Contactos    │ Captaciones  │ Bajadas      │ Cierres          │
│   4  ▲1      │   9  ▼2      │   1  =       │   2  ▲2      │   0              │
│ ◯ 80% de 5   │ ◯ 60% de 15  │ ◯ 50% de 2   │ ◯ 100% de 2  │ ◯ 0% de 1        │
├──────────────┴──────────────┴──────────────┴──────────────┴──────────────────┤
│ ┌─ Novedades (3 nuevas) ─────────────────┐ ┌─ Hoy y pendiente ─────────────┐ │
│ │ 🏠 Carlos visitó TU inmueble           │ │ ⏰ Llamar a M. Pérez (vencido) │ │
│ │    Calle Ejemplo 12 · hace 2 h  [Ver]  │ │ ⏰ Visita programada 17:00     │ │
│ │ 🏠 Visita con Ana (acompañante)        │ │ 📥 3 compradores sin leer      │ │
│ │    Piso Centro · ayer                  │ │ 🔁 2 "sin respuesta" >3 días   │ │
│ │ ✅ Ficha firmada y enviada · Ático     │ │                         [Ver →]│ │
│ │                         [Marcar leídas]│ └───────────────────────────────┘ │
│ └────────────────────────────────────────┘                                   │
│ ┌─ Mi tendencia (8 semanas) ─────────────────────────────────────────────┐   │
│ │  Hojas de visita ▂▃▅▃▆▇▅█   Contactos ▃▃▂▅▄▆▇▆   (línea de objetivo --)│   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│ ┌─ Mi cartera ───────────────────────────┐ ┌─ Observaciones del admin ─────┐ │
│ │ 14 activas · 2 pausadas · 1 reservada  │ │ "Buen ritmo de visitas, falta │ │
│ │ 3 sin visitas en 30 días  [Ver]        │ │  cerrar el ático"  · semana 40│ │
│ └────────────────────────────────────────┘ └───────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

Bloques del agente:
1. **Cabecera**: saludo, empresa activa, selector semana/mes con navegación (mismos query params que `/performance-reports`), badge "En curso" / "Período cerrado".
2. **KPIs con objetivo**: las 5 métricas de `calculate_metrics` + anillo de progreso SVG contra `agent_performance_targets`. El anillo solo aparece en las métricas que son objetivo para ese tipo de período (`OBJECTIVE_KEYS_BY_PERIOD`: semana = captaciones y bajadas; mes y año = captaciones, bajadas y cierres); las demás se muestran como resultado sin anillo. Captaciones, bajadas y cierres llevan el desglose "venta · alquiler" como subtítulo. Delta contra el período anterior.
3. **Novedades**: notificaciones del usuario (ver §4), no leídas primero, máximo 8, con "Marcar todas como leídas" y enlace a `/notifications` (lista completa).
4. **Hoy y pendiente**: seguimientos con `next_action_date` vencida o de hoy (de sus compradores), compradores `PENDING` sin leer, compradores en `SIN_RESPUESTA` con más de N días. Enlaces directos a `/alerts`.
5. **Tendencia**: dos series de 8 semanas (hojas de visita, contactos) con línea de objetivo. Gráfica ligera (ver decisión §6-4).
6. **Mi cartera**: conteo por estado de sus propiedades y "sin visitas en 30 días" (candidatas a bajada/acción).
7. **Observaciones del admin**: `admin_notes` del período actual si existen.

### 3.3 Inicio del ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Inicio · MOYZA                                   [Semana ▾] ◀ 6–12 oct ▶     │
├──────────────┬──────────────┬──────────────┬──────────────┬──────────────────┤
│ Hojas visita │ Contactos    │ Captaciones  │ Cierres      │ Compradores      │
│  23  ▲5      │  61  ▲4      │   6  ▼1      │   2  =       │ 17 pendientes    │
│ equipo       │ equipo       │ equipo       │ equipo       │ 4 abandonados    │
├──────────────┴──────────────┴──────────────┴──────────────┴──────────────────┤
│ ┌─ Cumplimiento del equipo ──────────────────────────────────────────────┐   │
│ │ Agente      Visitas   Contactos  Capt.  Bajadas  Cierres   Global      │   │
│ │ Laura G.    ████ 80%  ███  60%   ██ 50% ████100%  ░░  0%   ███ 58%  ↗ │   │
│ │ Carlos M.   ████100%  ████ 95%   ░░  0% ██  40%   ████100% ███ 67%  ↗ │   │
│ │ Ana R.      █   20%   ██   35%   —      —         —        ░░  28%  ↘ │   │
│ │                                              [Objetivos y notas →]     │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│ ┌─ Requiere atención ────────────────────┐ ┌─ Actividad reciente ──────────┐ │
│ │ ⚠ 4 compradores sin atender >7 días    │ │ 🏠 Carlos visitó inmueble de   │ │
│ │ ⚠ Ana R. sin actividad 6 días          │ │    Laura · Calle Ejemplo · 2 h │ │
│ │ ⚠ 2 fichas de visita no enviadas (WA)  │ │ 📉 Bajada 320k→305k · Piso Sur │ │
│ │ ⚠ 1 objetivo sin definir esta semana   │ │ ✅ Cierre · M. Pérez · Carlos  │ │
│ └────────────────────────────────────────┘ │ 🆕 Captación · Chalet Norte    │ │
│ ┌─ Tendencia del equipo (12 semanas) ────┐ │                       [Ver →] │ │
│ │ barras apiladas por agente: visitas    │ └───────────────────────────────┘ │
│ │ línea: contactos                       │                                   │
│ └────────────────────────────────────────┘                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

Bloques del admin:
1. **KPIs del equipo** (suma de agentes de la empresa activa) con delta vs. período anterior + compradores pendientes / abandonados (misma regla de 7 días que `/alerts-dashboard`).
2. **Cumplimiento del equipo**: una fila por agente con mini-barras por métrica y un **% global** (media de los % de las métricas que tienen objetivo). Flecha de tendencia vs. período anterior. Click en el agente → panel de objetivos y notas en `/performance-reports`.
3. **Requiere atención**: lista calculada (no es tabla de notificaciones): compradores `PENDING` > 7 días, agentes sin actividad (ni visita, ni seguimiento, ni alerta leída) en N días, fichas con WhatsApp en `ERROR` las últimas 48 h, agentes sin objetivo definido en el período en curso.
4. **Actividad reciente**: feed unificado de los últimos 20 eventos de la empresa (visita registrada con énfasis cuando el agente no es el captador, bajada de precio, cierre, captación, ficha firmada). Se construye en memoria a partir de 5 consultas acotadas por fecha.
5. **Tendencia del equipo**: 12 semanas, barras apiladas por agente para hojas de visita, línea para contactos.
6. **Novedades** (notificaciones del admin, §4) en la campana de la cabecera y como bloque compacto encima de "Requiere atención" cuando hay no leídas.

---

## 4. Notificaciones in-app

### 4.1 Modelo

Tabla nueva `notifications` (migración `u4v5w6x7y8z9`, `down_revision = 't3u4v5w6x7y8'`, la de Resultados Comerciales):

```python
class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)          # ver catálogo
    title = Column(String, nullable=False)         # "Carlos M. visitó tu inmueble"
    body = Column(String, nullable=True)           # "Calle Ejemplo 12 · visitante: J. Pérez"
    url = Column(String, nullable=True)            # "/properties/42"
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    entity_type = Column(String, nullable=True)    # "visit" | "alert" | "property" | ...
    entity_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    read_at = Column(DateTime, nullable=True)
```

Índice compuesto `(user_id, read_at, created_at)` para el badge y el listado. Retención: tarea de limpieza
que borra leídas con más de 90 días (se añade al scheduler existente).

### 4.2 Servicio

`app/services/notification_service.py`:
- `notify(db, *, users, company_id, kind, title, body=None, url=None, actor=None, entity=None)`: crea una fila por usuario, **deduplica** (misma `kind` + `entity` + usuario sin leer en las últimas 24 h → no repite) y nunca notifica al propio actor.
- `unread_count(db, user_id, company_id)`, `recent(db, user_id, company_id, limit)`, `mark_read(db, user_id, ids | all)`.
- Resolución agente → usuario por email (`Agent.email == User.email`), igual que `get_agent_from_user` pero inverso; helper `users_for_agent(db, agent)`.
- `admins_of_company(db, company_id)`: usuarios con rol admin y pertenencia a la empresa.
- Todo dentro de la transacción del evento que la origina; si falla la notificación se registra en log y no se rompe el flujo principal (try/except alrededor de `notify`).

### 4.3 Catálogo de eventos v1

| `kind` | Quién la recibe | Cuándo se emite (dónde engancharla) |
|---|---|---|
| `visit_on_my_property` | Agente captador de la propiedad | `create_visit` cuando `visit.agent_id != property.agent_id` (y acompañante tampoco es el captador) |
| `visit_as_companion` | Agente acompañante | `create_visit` cuando hay `companion_agent_id` |
| `visit_completed` | Agente principal y acompañante | `finalize_visit` (ficha firmada y enviada) |
| `visit_sheet_send_failed` | Agente principal + admins | `finalize_visit` / `send_visit_sheet_whatsapp` cuando el log queda en `ERROR` |
| `alert_assigned` | Agente asignado | Alta de alerta de comprador con `agent_id` (ya tiene badge propio; aquí solo aparece en el feed, sin duplicar el badge de compradores) |
| `follow_up_due` | Agente de la alerta | Job diario a las 08:00 Madrid: seguimientos con `next_action_date` = hoy o vencidos (uno por alerta y día) |
| `target_reached` | Agente | Al calcular métricas en el Inicio, si una métrica alcanza el 100 % y no existe ya la notificación para ese período |
| `period_closed` | Agente | Al congelar el período (`freeze_report`), con resumen "4 de 5 objetivos cumplidos" |
| `admin_note_added` | Agente | `save_notes` en `/performance-reports` |

Los admins reciben además `visit_on_my_property` en modo resumen cuando quieran (decisión §6-3).

### 4.4 UI

- **Campana** en la cabecera (`components/navbar.html`): punto con contador de no leídas (endpoint `/api/notifications/unread-count`, mismo patrón que `alertsBadge`, sondeo cada 2 min). Click → panel desplegable con las 8 últimas y "Ver todas".
- **Página** `/notifications`: lista paginada, filtro leídas/no leídas, "Marcar todas como leídas". Click en una → `mark_read` + redirección a `url`.
- **Inicio**: bloque "Novedades" (§3.2-3) con las no leídas primero.

---

## 5. Arquitectura e implementación

### 5.1 Servicio de Inicio

`app/services/dashboard_service.py` con dos entradas puras (sin `request`), fáciles de testear:

```python
class DashboardService:
    def __init__(self, db, company_id): ...
    def period(self, period_type, period_start_str) -> Period   # mueve _parse_period aquí
    def agent_home(self, agent, period) -> AgentHomeData
    def admin_home(self, period) -> AdminHomeData
```

- `AgentHomeData`: `kpis` (lista de `Kpi(key, label, value, previous, target, pct, delta)`), `agenda`,
  `portfolio`, `trend` (series semanales), `admin_notes`.
- `AdminHomeData`: `kpis`, `team` (lista por agente con `pct_global` y `trend`), `attention`, `activity_feed`, `trend`.
- Reutiliza `PerformanceReportService.calculate_metrics` y `get_target`; el período anterior se calcula con los mismos helpers.
- Series de tendencia con una sola consulta agrupada por semana (`date_trunc('week', created_at)`) por tabla, no 8×N consultas.
- `routes/performance_reports.py` y `routes/alerts.py::alerts_dashboard` pasan a usar `DashboardService.period` (se elimina la duplicación; sin cambiar su comportamiento).

### 5.2 Rutas y plantillas

- `routes/dashboard.py`: `GET /dashboard` para todos los roles; decide `agent_home` o `admin_home` según `is_admin`. Un agente sin ficha de agente (`get_agent_from_user` → `None`) ve una vista mínima con aviso.
- Plantillas: `dashboard/home.html` (layout + cabecera + selector) que incluye `dashboard/_agent.html` o `dashboard/_admin.html`, y parciales reutilizables en `dashboard/components/`: `kpi_card.html` (número + delta + anillo), `progress_ring.html` (SVG), `feed_item.html`, `attention_item.html`, `trend_chart.html`.
- Sidebar: entrada "Inicio" (icono casa) visible para todos, primera de la lista; "Dashboard Compradores" se mantiene.
- Login: sigue redirigiendo a `/dashboard` (ahora válido para todos). Se elimina el flash "Acceso denegado" al entrar.
- `/notifications` + `api/v1/endpoints/notifications.py` (`unread-count`, `recent`, `mark-read`) usando `get_api_user` + `resolve_company_for_api` como el resto de `/api/*`.

### 5.3 Gráficas

Opción recomendada: **Chart.js 4 (UMD) vendorizado** en `static/js/chart.umd.js`, igual que `tailwind.js` (sin CDN, funciona offline en el despliegue). Los datos se inyectan como JSON en un `<script type="application/json">` por gráfica y un `dashboard.js` los monta. Anillos de progreso y mini-barras del ranking en SVG/CSS puro (no necesitan librería). Alternativa sin librería: sparklines en SVG generadas en el servidor (menos interactivas).

### 5.4 Rendimiento

- Objetivo: `/dashboard` < 300 ms con 10 agentes y 12 semanas de historia.
- Consultas acotadas por `created_at` y empresa; `joinedload` de `property`, `agent` en el feed.
- Si hiciera falta: caché en memoria de 60 s por `(company_id, user_id, period)` en `DashboardService` (opcional, no en v1).

---

## 6. Decisiones tomadas (2026-10-08)

| # | Pregunta | Decisión |
|---|---|---|
| 1 | ¿Inicio en `/dashboard` para todos los roles y el agente aterriza ahí tras login? | **Sí.** |
| 2 | Notificaciones | **Tabla propia + campana en cabecera + página `/notifications`.** |
| 3 | Eventos v1 | **Los 6 propuestos**: `visit_on_my_property`, `visit_as_companion`, `visit_completed`, `visit_sheet_send_failed`, `follow_up_due`, `admin_note_added`. Admin: solo feed y "Requiere atención", sin campana en v1. `target_reached` y `period_closed` quedan para después. |
| 4 | Gráficas | **Chart.js vendorizado en local.** |
| 5 | Período por defecto | **Semana**, con toggle semana / mes / año (el año llega con `PLAN_RESULTADOS_COMERCIALES.md`). |
| 6 | Visibilidad entre agentes | **Solo lo suyo**, con "estás en el puesto N de M" sin nombres. |
| 7 | Aviso de compradores sin atender | **Reutilizar la regla existente de 48 h** (`BUYER_REMINDER_HOURS`, `buyer_reminder_service.get_pending_buyers_by_agent`), no inventar otro umbral. Se muestra como **ventana emergente al entrar al Inicio** (ver §3.4) además del bloque "Requiere atención". Los otros umbrales (agente sin actividad > 5 días, "sin respuesta" > 3 días) se mantienen como constantes para el bloque del admin. |
| 8 | % global de cumplimiento | Media simple de los % de las métricas **que son objetivo en ese tipo de período** (ver `OBJECTIVE_KEYS_BY_PERIOD` en `PLAN_RESULTADOS_COMERCIALES.md`). |
| 9 | Retención de notificaciones leídas | 90 días, limpieza en el scheduler. |
| 10 | "Dashboard Compradores" | Pasa a llamarse **Resultados Comerciales** y se rediseña según `PLAN_RESULTADOS_COMERCIALES.md`. El Inicio enlaza a él. |

### 3.4 Ventana emergente de compradores sin atender (decisión 7)

- **Fuente**: `get_pending_buyers_by_agent(db, settings.BUYER_REMINDER_HOURS)` filtrado por la empresa activa.
  Es exactamente la lista que hoy se manda por email a las 06:00; en pantalla se ve al momento.
- **Agente**: al cargar el Inicio, si tiene compradores con más de 48 h sin gestión, aparece un modal con la
  lista (nombre, teléfono, horas sin gestión, botón "Gestionar" → `/alerts/{id}`) y "Lo reviso después".
  Se cierra una vez por día por navegador (`localStorage` con clave `pending_buyers_dismissed_<fecha>`), para
  que no sea spam pero reaparezca al día siguiente si sigue sin gestionar. El bloque "Hoy y pendiente" lo
  sigue mostrando siempre.
- **Admin**: mismo modal pero agrupado por agente ("Laura G. · 3 compradores · el más antiguo 71 h"), con
  enlace a `/alerts?agent_id=…`. También aparece en "Requiere atención".
- **Accesibilidad**: `role="dialog"`, cierre con Escape, foco en el primer botón.

---

## 7. Fases de implementación

Cada fase deja la app funcionando y se commitea aparte (`feat(inicio): fase N - …`).

### Fase 1 · Cimientos
- [ ] `services/dashboard_service.py` con `period()` (mover `_parse_period` y navegación prev/next) y refactor de `routes/performance_reports.py` y `routes/alerts.py::alerts_dashboard` para usarlo. Sin cambios funcionales.
- [ ] Tests unitarios de `period()` (semana/mes, normalización, `show_next`).
- [ ] **Arreglo previo 1 · métricas por empresa.** Hecho en `PLAN_RESULTADOS_COMERCIALES.md` (commit 2e4c52e).
- [ ] **Alinear Resultados Comerciales con el skill** (quedó con dos desviaciones conocidas): serie venta debe ser
      `#2563EB` y no `brand_color` (`templates/commercial_results/home.html` `sale_color`, `static/js/commercial_results.js`
      `ACCENT`/venta); semáforo verde / ámbar / rojo en `templates/commercial_results/metric_card.html:43` y
      `_evolution.html:97` (hoy verde / azul / naranja). Pasar `ui_lint.py` sobre `templates/commercial_results/`.
- [ ] **Arreglo previo 2 · "Volver a editar datos" del preview.** El botón en `templates/visits/preview.html`
      apunta a `/visits/new/{property_id}` y crea una segunda visita. Debe llevar a
      `/visits/edit/{visit_id}`; `update_visit` ya respeta `draft`/`preview` y, al guardar, redirigir al
      preview (`/visits/preview/{visit_id}`) en vez de a `/visits` cuando el estado es `draft`/`preview`.
      Test de integración: editar desde el preview no aumenta el número de visitas.

### Fase 2 · Inicio del agente
- [ ] `DashboardService.agent_home` (KPIs + delta + objetivo, agenda, cartera, tendencia 8 semanas, notas admin).
- [ ] `GET /dashboard` abierto a todos los roles; plantillas `home.html`, `_agent.html`, componentes `kpi_card`, `progress_ring`.
- [ ] Sidebar "Inicio" para todos. Verificar login de agente sin flash de error.
- [ ] Vendorizar Chart.js (si se aprueba) + `static/js/dashboard.js`.

### Fase 3 · Inicio del admin
- [ ] `DashboardService.admin_home` (KPIs equipo, cumplimiento por agente con % global y tendencia, "Requiere atención", feed de actividad, tendencia 12 semanas).
- [ ] Plantillas `_admin.html`, componentes `feed_item`, `attention_item`, `trend_chart`.
- [ ] Constantes de umbrales en `core/constants.py`.

### Fase 4 · Notificaciones
- [ ] Modelo `Notification` + migración `u4v5w6x7y8z9` + `notification_service.py`.
- [ ] Hooks de emisión: `create_visit`, `finalize_visit`, `send_visit_sheet_whatsapp`, alta de alerta, `save_notes`, `freeze_report`.
- [ ] Job diario `follow_up_due` en el scheduler existente + limpieza a 90 días.
- [ ] API `unread-count` / `recent` / `mark-read`, campana en `navbar.html`, página `/notifications`, bloque "Novedades" en Inicio.

### Fase 5 · QA y despliegue
- [ ] Tests: `tests/test_dashboard_service.py` (KPIs, deltas, % global, agenda, feed con visita de otro agente), `tests/test_notification_service.py` (dedupe, no notificar al actor, resolución agente→usuario, aislamiento por empresa).
- [ ] Prueba de aislamiento multiempresa: un admin con las dos empresas cambia de empresa y el Inicio cambia por completo.
- [ ] Revisión visual en móvil (375 px) y escritorio; estados vacíos de cada bloque.
- [ ] Nota de despliegue: `alembic upgrade head` + `docker restart moyza_backend`.

### Criterios de aceptación
1. Un agente entra, aterriza en Inicio sin errores, ve sus 5 KPIs con progreso contra objetivo y su agenda del día.
2. Cuando otro agente registra una visita en su inmueble, al captador le aparece en la campana y en "Novedades" sin que se envíe ningún email ni WhatsApp.
3. El admin ve el cumplimiento del equipo con % global por agente y el feed con la visita cruzada marcada.
4. Cambiar de empresa cambia todo el contenido del Inicio; ninguna notificación cruza de empresa.
5. `/performance-reports` y `/alerts-dashboard` siguen funcionando igual tras el refactor de período.
6. `/dashboard` responde en menos de 300 ms en local con los datos actuales.

---

## 8. Brief para el agente ejecutor

> Implementa `PLAN_DASHBOARD_INICIO.md` por fases, un commit por fase (`feat(inicio): fase N - …` con la línea de
> co-autoría del repo). Requiere `PLAN_VISITAS_AGENTES.md` (hecho) y `PLAN_RESULTADOS_COMERCIALES.md` (hecho:
> `PerformanceReportService(db, company_id)`, `period()`, `PerformanceObjectives`, `PeriodType`, desglose
> venta/alquiler, `routes/commercial_results.py`, Chart.js en `static/js/chart.umd.js`). Carga el skill
> `moyza-ui-ux-pro` y síguelo en todo lo visual. Lee primero: `routes/dashboard.py`, `routes/commercial_results.py`,
> `services/performance_report_service.py`, `services/buyer_reminder_service.py`, `services/company_scope.py`,
> `services/visit_agents.py`, `templates/commercial_results/*`, `templates/components/sidebar.html` y `navbar.html`,
> `jobs/scheduler.py`, `MULTIEMPRESA_MOYZA_MOES.md`. Respeta las decisiones de §6. Toda consulta va filtrada por
> empresa activa. No envíes correos ni WhatsApp desde las notificaciones. Al terminar, ejecuta `ui_lint.py` y los
> tests en el contenedor y reporta tiempos reales de `/dashboard`.
