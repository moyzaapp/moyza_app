# Plan: Resultados Comerciales (antes "Dashboard Compradores") y módulo de Rendimiento

Fecha: 2026-10-08 · Requisitos del usuario 14 a 18 · Se ejecuta **antes** de `PLAN_DASHBOARD_INICIO.md`,
que depende de los cambios de este plan en `PerformanceReportService`.

## 1. Situación actual

| Qué | Estado | Archivo |
|---|---|---|
| Sección "Dashboard Compradores" | Ruta `/alerts-dashboard`, solo admin. Dos pestañas: **General** (totales de alertas, abandonadas > 7 días, tabla por agente con tiempos de respuesta y conversión) y **Rendimiento por período** (semana / mes). | `routes/alerts.py::alerts_dashboard` (línea 1369), `templates/alerts/dashboard.html` (517 líneas) |
| Pantalla duplicada | `/performance-reports` muestra lo mismo que la pestaña Rendimiento, con su propia plantilla y su propia copia de la lógica de período. Los formularios de objetivos y notas redirigen a `/alerts-dashboard?tab=rendimiento`. | `routes/performance_reports.py`, `templates/alerts/performance_report.html` |
| Métricas | `calculate_metrics(agent_id, start, end)`: contactos venta / alquiler (alertas por `business_type`), bajadas (historial de precio), captaciones CRM (`market_entry_date`), cierres (seguimiento `CERRADO`), hojas de visita. **No filtra por empresa.** | `services/performance_report_service.py:65-148` |
| Objetivos | Tabla `agent_performance_targets` con 5 campos (`target_contactos`, `target_bajadas`, `target_captaciones_crm`, `target_cierres`, `target_hojas_visita`) por agente y período (`WEEKLY` / `MONTHLY`). El formulario muestra siempre los 5. | `models/agent_performance_target.py` |
| Snapshots | `agent_performance_reports`: copia congelada de las métricas al cerrar semana (lunes 00:01) y mes (día 1 00:01) desde el scheduler. Sin empresa. | `models/agent_performance_report.py`, `jobs/scheduler.py:112-152` |
| Venta / alquiler | `properties.business_type` ("Venta" / "Alquiler") y `property_alerts.business_type` (mismos valores). Captaciones, bajadas y cierres hoy **no** distinguen el tipo. | `models/property.py:45`, `models/property_alert.py:104` |
| Gráficas | Ninguna. Barras de progreso en CSS. | |

---

## 2. Diseño propuesto

### 2.1 Nombre y estructura (req. 14)

- La sección pasa a llamarse **Resultados Comerciales**. Ruta nueva `/commercial-results`; `/alerts-dashboard` y
  `/performance-reports` quedan como redirecciones 301 a la nueva ruta (conservan los query params) para no
  romper enlaces guardados.
- Sidebar: "Dashboard Compradores" → "Resultados Comerciales" (icono de gráfica), solo admin.
- Tres pestañas:
  1. **Rendimiento** (por defecto): objetivos y resultados por agente, con período semana / mes / **año**.
  2. **Evolución**: gráficas (req. 18).
  3. **Compradores**: la pestaña "General" actual (alertas, abandonadas, tabla por agente). Se conserva tal cual, renombrada.
- La plantilla `alerts/performance_report.html` desaparece; la pestaña Rendimiento vive en una sola plantilla
  `commercial_results/performance.html` (se elimina la duplicación).

### 2.2 Período anual (req. 15)

- `period_type` admite `YEARLY`. En `PerformanceReportService`: `current_year_start()`, `year_bounds()`,
  `is_current_period` para año, navegación año anterior / siguiente.
- Selector: Semana · Mes · **Año**. Cabecera del período: "2026".
- Objetivos anuales en `agent_performance_targets` con `period_type='YEARLY'` y `period_start = 1 de enero`.
- Snapshot anual: job `freeze_yearly_reports` el 1 de enero a las 00:01 (mismo patrón que mensual).
- El año en curso se calcula en vivo (como semana y mes en curso).

### 2.3 Objetivos por tipo de período (req. 16 y 17)

Una sola constante gobierna formularios, anillos, barras y % de cumplimiento:

```python
# app/core/constants.py
class PerformanceObjectives:
    WEEKLY  = ("captaciones_crm", "bajadas")
    MONTHLY = ("captaciones_crm", "bajadas", "cierres")
    YEARLY  = ("captaciones_crm", "bajadas", "cierres")      # pendiente de confirmar (§5-1)

    @classmethod
    def for_period(cls, period_type) -> tuple: ...
```

- **Semana**: solo captaciones y bajadas tienen objetivo. Contactos, cierres y hojas de visita se muestran como
  resultado (número y desglose), sin barra ni "obj.".
- **Mes**: contactos y hojas de visita dejan de ser objetivo; siguen visibles como resultado.
- El formulario "Objetivos del período" solo muestra los campos de `for_period(period_type)`.
- `save_targets` ignora cualquier campo que no sea objetivo en ese período (no borra lo que ya hubiera guardado).
- % global de cumplimiento (lo usa el Inicio) = media simple de los % de las métricas de `for_period`.

### 2.4 Desglose venta / alquiler (req. 18, parte de datos)

`calculate_metrics` devuelve, además de los totales actuales, el desglose:

| Métrica | Fuente del tipo | Nuevas claves |
|---|---|---|
| Captaciones CRM | `Property.business_type` | `captaciones_venta`, `captaciones_alquiler` |
| Bajadas | `Property.business_type` de la propiedad del historial | `bajadas_venta`, `bajadas_alquiler` |
| Cierres | `PropertyAlert.business_type`; si es NULL, el `business_type` de la propiedad de la alerta | `cierres_venta`, `cierres_alquiler` |
| Contactos | ya existe (`contactos_venta`, `contactos_alquiler`) | sin cambio |

- Comparación insensible a mayúsculas (`ilike('venta')` / `ilike('alquiler')`), como ya hace contactos.
  Valores distintos o NULL cuentan en el total pero no en ningún tipo (se muestra "otros" solo si existe).
- Snapshots: 6 columnas nuevas en `agent_performance_reports` (migración) para congelar el desglose.
- Objetivos siguen siendo **totales** (sin separar por tipo) salvo decisión contraria (§5-2).
- En la pestaña Rendimiento cada tarjeta de captaciones, bajadas y cierres muestra debajo del número
  "V 3 · A 1" con dos colores fijos (venta = color de marca, alquiler = ámbar), igual que hoy contactos.

### 2.5 Métricas por empresa (arreglo previo)

`PerformanceReportService(db, company_id)`; todas las consultas de `calculate_metrics` filtran por
`Property.company_id` (alertas y seguimientos vía su propiedad, bajadas, captaciones, hojas de visita).
`agent_performance_targets` y `agent_performance_reports` ganan `company_id` (migración, backfill a MOYZA,
parte de la clave de `get_report`, `get_target`, `freeze_report`). `freeze_all_for_period` recorre
empresas × agentes de cada empresa. Un agente que está en las dos empresas tiene objetivos y resultados
separados en cada una.

### 2.6 Pestaña Evolución (req. 18, parte visual)

Gráficas con Chart.js vendorizado (`static/js/chart.umd.js`, decisión ya tomada en el plan del Inicio).
Datos inyectados como JSON en la página; sin llamadas extra.

```
┌─ Evolución · 2026 ──────────────────────────────────────── [◀ 2026 ▶] ─┐
│ Indicador: (●) Captaciones ( ) Cierres ( ) Bajadas    Agente: [Todos ▾] │
├─ Resultados por agente en el año ───────────────────────────────────────┤
│   Laura G.   ████████░░░░  venta 8 · alquiler 3     ─ ─ objetivo 15     │
│   Carlos M.  ██████████░░  venta 6 · alquiler 6     ─ ─ objetivo 12     │
│   Ana R.     ████░░░░░░░░  venta 4 · alquiler 0     ─ ─ objetivo 10     │
│   (barras horizontales apiladas venta/alquiler, marca del objetivo anual)│
├─ Evolución mensual ─────────────────────────────────────────────────────┤
│   12 ┤            ╭─╮                                                   │
│    8 ┤      ╭─────╯ ╰──╮   ── Laura  ── Carlos  ── Ana                  │
│    4 ┤ ╭────╯          ╰────                                            │
│    0 ┼─E──F──M──A──M──J──J──A──S──O──N──D                               │
│   (líneas por agente del indicador elegido; con "Todos", suma del equipo│
│    apilada venta/alquiler en barras)                                    │
├─ Cumplimiento anual ────────────────────────────────────────────────────┤
│   Laura 72 % · Carlos 85 % · Ana 40 %   (media de los objetivos del año)│
└─────────────────────────────────────────────────────────────────────────┘
```

- Gráfica 1 (**por agente, año**): barras horizontales apiladas venta / alquiler, una por agente, con línea
  vertical del objetivo anual de ese indicador. Selector de indicador: captaciones, cierres, bajadas.
- Gráfica 2 (**evolución mensual**): 12 meses del año elegido. Con un agente: línea venta + línea alquiler.
  Con "Todos": barras apiladas venta / alquiler del equipo y línea de total.
- Tarjetas de **cumplimiento anual** por agente (% global sobre los objetivos del año).
- Los meses cerrados se leen del snapshot mensual; el mes en curso se calcula en vivo. Una consulta por
  indicador agrupada por `date_trunc('month')` para el mes en curso; el resto sale de `agent_performance_reports`.
- Tooltips con valores exactos; leyenda clicable para ocultar series; colores venta / alquiler consistentes en
  toda la sección; texto alternativo con la tabla de datos debajo de cada gráfica (accesible y copiable).

---

## 3. Fases de implementación

Un commit por fase: `feat(resultados): fase N - …`.

### Fase 1 · Servicio de métricas
- [ ] `PerformanceReportService(db, company_id)` + filtro por empresa en todas las consultas (§2.5).
- [ ] Desglose venta / alquiler en `calculate_metrics` (§2.4), con totales inalterados.
- [ ] Período `YEARLY`: helpers de año, `is_current_period`, `period()` unificado (mueve `_parse_period` de
      `routes/performance_reports.py` y la copia de `routes/alerts.py` al servicio; devuelve también
      `prev_start`, `next_start`, `show_next`, etiqueta).
- [ ] `PerformanceObjectives` en `core/constants.py` + `objective_keys(period_type)` y
      `completion_pct(metrics, target, period_type)` en el servicio.
- [ ] Migración `t3u4v5w6x7y8`: `company_id` en targets y reports (backfill a MOYZA, índice único
      `(agent_id, company_id, period_type, period_start)`), 6 columnas de desglose en reports.
- [ ] Tests `tests/test_performance_service.py`: aislamiento por empresa, desglose venta/alquiler (incluido
      NULL y mayúsculas), límites de año, claves de objetivo por período, % global.

### Fase 2 · Sección Resultados Comerciales
- [ ] `routes/commercial_results.py` con `GET /commercial-results?tab=rendimiento|evolucion|compradores`,
      `POST /commercial-results/{agent_id}/targets` y `/notes` (mueven desde `performance_reports.py`).
- [ ] Redirecciones 301 desde `/alerts-dashboard` y `/performance-reports`.
- [ ] Plantillas `commercial_results/home.html` (cabecera + pestañas), `_performance.html`, `_buyers.html`
      (contenido actual de la pestaña General), parciales `metric_card.html` (número, desglose V/A, barra solo
      si es objetivo), `targets_form.html` (campos según período).
- [ ] Selector Semana · Mes · Año y navegación; año en curso en vivo.
- [ ] Sidebar renombrado. Eliminar `alerts/performance_report.html` y `alerts/dashboard.html` cuando la nueva
      sección esté completa.

### Fase 3 · Snapshots y scheduler
- [ ] `freeze_all_for_period` por empresa; job `freeze_yearly_reports` (1 de enero 00:01).
- [ ] Verificar que semana y mes siguen congelando igual (test con fecha fija, sin depender del día actual).

### Fase 4 · Pestaña Evolución
- [ ] Vendorizar Chart.js 4 UMD en `static/js/chart.umd.js` (si el plan del Inicio no lo hizo antes).
- [ ] `PerformanceReportService.yearly_series(company_id, year, indicator, agent_id=None)` → por agente
      (venta, alquiler, objetivo) y por mes.
- [ ] Plantilla `_evolution.html` + `static/js/commercial_results.js` (monta las dos gráficas, selector de
      indicador y agente sin recargar: todos los datos del año van en el JSON inicial).
- [ ] Tabla de datos accesible bajo cada gráfica.

### Fase 5 · QA
- [ ] Tests de ruta: redirecciones, pestañas, formulario de objetivos solo con los campos del período,
      aislamiento por empresa al cambiar de empresa.
- [ ] Revisión visual en móvil y escritorio. Estados vacíos (sin agentes, sin objetivos, año sin datos).
- [ ] Nota de despliegue en `MULTIEMPRESA_MOYZA_MOES.md`: `alembic upgrade head` + reinicio.

### Criterios de aceptación
1. El menú dice "Resultados Comerciales" y los enlaces antiguos siguen funcionando.
2. En semana solo hay objetivo de captaciones y bajadas; en mes, captaciones, bajadas y cierres. El resto se ve como resultado.
3. Existe la vista por año con objetivos anuales y navegación entre años.
4. Captaciones, cierres y bajadas muestran venta y alquiler por separado en tarjetas y gráficas.
5. La pestaña Evolución muestra barras por agente apiladas venta / alquiler con objetivo y la evolución mensual del año.
6. Un agente en las dos empresas tiene resultados y objetivos distintos en cada una.
7. Los snapshots semanales y mensuales existentes no cambian de valor tras la migración.

---

## 4. Impacto en otros planes

- `PLAN_DASHBOARD_INICIO.md`: los anillos de objetivo y el % global usan `PerformanceObjectives`; el KPI de
  captaciones, bajadas y cierres muestra el desglose venta / alquiler; el toggle de período incluye Año; el
  arreglo "métricas por empresa" sale de allí y se hace aquí.
- `PLAN_VISITAS_AGENTES.md` (hecho): `hojas_visita` ya cuenta por agente participante; aquí solo se le añade
  el filtro por empresa.

---

## 5. Decisiones tomadas (2026-10-08)

| # | Pregunta | Decisión |
|---|---|---|
| 1 | Objetivos anuales | **Captaciones, bajadas y cierres** (igual que el mes). `PerformanceObjectives.YEARLY` queda confirmado. |
| 2 | Objetivos por tipo | **Un objetivo total por indicador.** El desglose venta / alquiler es solo de resultados. |
| 3 | Unificar pantallas | **Sí.** `/performance-reports` y `/alerts-dashboard` redirigen a `/commercial-results`. |
| 4 | Tipo del cierre | **`business_type` de la alerta; si falta, el de la propiedad.** |
| 5 | Objetivos ya guardados de contactos y hojas de visita | **Se dejan en la tabla** como histórico; no se muestran ni cuentan. |
| 6 | Gráfica inicial | **Como está en §2.6**: barras por agente apiladas venta / alquiler con objetivo, evolución mensual del año y cumplimiento anual. |

---

## 6. Brief para el agente ejecutor

> Implementa `PLAN_RESULTADOS_COMERCIALES.md` por fases, un commit por fase (`feat(resultados): fase N - …` con
> la línea de co-autoría del repo), sin push, sin tocar los cambios no commiteados del usuario. Lee primero:
> `services/performance_report_service.py`, `routes/performance_reports.py`, `routes/alerts.py` (función
> `alerts_dashboard` y su plantilla `alerts/dashboard.html`), `templates/alerts/performance_report.html`,
> `jobs/scheduler.py`, `models/agent_performance_target.py`, `models/agent_performance_report.py`,
> `services/company_scope.py` y `MULTIEMPRESA_MOYZA_MOES.md`. Respeta las respuestas de §5. Todas las
> consultas filtran por empresa activa. Aplica la migración y corre los tests en el contenedor
> (`docker exec moyza_backend …`) y reporta la salida real.
