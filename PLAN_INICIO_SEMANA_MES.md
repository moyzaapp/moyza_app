# Plan: Inicio con semana y mes a la vez, tabla ordenable y aviso al iniciar sesión

Fecha: 2026-10-19. Rama `63-agregar-moes`. Depende de `PLAN_DASHBOARD_INICIO.md` (implementado).
Solo frontend y la capa de servicio del Inicio: sin migraciones, sin cambios de modelo.

## 1. Problema

1. El aviso "Compradores sin atender" se ve descuadrado en el móvil (franja sin fondo arriba,
   panel desplazado) y solo sale una vez al día por navegador. Se quiere que salga **en cada
   inicio de sesión** y que se lea bien en el teléfono.
2. Los objetivos semanales y mensuales solo se ven pulsando Semana / Mes. Los usuarios no
   pulsan y creen que no hay objetivos. Se quiere ver **semana y mes a la vez**, sin selector.
3. La tabla "Cumplimiento del equipo" (admin) debe poder **ordenarse por columna**.

## 2. Diagnóstico

- El modal se renderiza dentro de `<div class="max-w-7xl mx-auto space-y-6">` (`home.html:13`).
  `space-y-6` aplica `margin-top: 1.5rem` a todo hijo que no tenga el atributo `[hidden]`; el
  modal usa la clase `hidden`, así que recibe el margen y el `fixed inset-0` nace 24 px más
  abajo. Además el cuerpo y el pie usan `p-6` también a 375 px.
- La apertura automática la decide `dashboard.js` con `localStorage pending_buyers_dismissed_<fecha>`.
  Cerrar arrastrando la hoja o pulsar "Gestionar" no guarda la clave; la clave no distingue
  usuario ni empresa.
- El período llega por `?period_type=&period_start=` (`routes/dashboard.py:45-52`) y
  `admin_home` / `agent_home` reciben un único `Period`. Los objetivos se guardan por tipo
  de período y fecha exacta (semana: captaciones y bajadas; mes: + cierres), no se prorratean.
- La tabla se ordena en servidor (`team_rows`, % global desc) y no tiene ordenación en cliente.
  Ya existe un script de ordenación por columnas en `properties/home.html:150-195`
  (`table.js-sortable`, `data-sort-type`, `data-sort-value`).

## 3. Decisiones (confirmadas con el usuario el 2026-10-19)

| # | Decisión | Elegido |
|---|---|---|
| D1 | Cuándo sale el aviso de compradores sin atender | **En cada inicio de sesión.** No vuelve a salir al navegar de vuelta a Inicio dentro de la misma sesión; el botón "Ver compradores sin atender" sigue disponible para reabrirlo. |
| D2 | Selector Semana / Mes / Año en Inicio | **Se quita.** Inicio muestra siempre la semana en curso y el mes en curso. El año y la navegación histórica quedan en Resultados Comerciales (enlace "Ver histórico"). |
| D3 | Tabla "Cumplimiento del equipo" con ambos períodos | **Revisado el 2026-10-20**: se probó una tabla con dos grupos de columnas (Semana / Mes) y el usuario prefirió la tabla original. Queda **la tabla de siempre, con la semana en curso** (Agente, Visitas, Contactos, Capt., Bajadas, Cierres, Global; flecha frente a la semana anterior), ahora ordenable. Los objetivos del mes se ven en las tarjetas "Este mes". |
| D4 | Visitas y contactos (métricas sin objetivo) | **Solo del mes**, en la fila de KPIs del equipo y como dos columnas al final de la tabla. |
| D5 | Ordenación de la tabla | En cliente, por cualquier columna; en métricas con objetivo ordena por % (los "sin objetivo" al final), en visitas y contactos por valor, en Global por % global. El último orden elegido se recuerda en el navegador. |

## 4. Diseño

### 4.1 Aviso "Compradores sin atender"

- **Encuadre**: el macro `ui.modal` lleva `!mt-0` en la raíz, así ningún `space-y-*` lo
  desplaza (arregla todos los modales, no solo este). Cuerpo `p-4 sm:p-6` y pie `px-4 sm:px-6`
  en móvil. Subtítulo más corto en móvil ("3 compradores · más de 48 h hábiles").
- **Apertura por inicio de sesión**: el login (`routes/auth.py`) pone una cookie
  `moyza_welcome=1` (no httponly, 2 minutos). `dashboard.js` abre el modal si la cookie existe
  y la borra. Se elimina `data-dismiss-daily` y el `localStorage`. Si no hay compradores
  pendientes el modal no se renderiza y la cookie se borra igualmente.
- Documentación: actualizar `PLAN_DASHBOARD_INICIO.md` §3.4 y `PLAN_ALERTAS_DIAS_HABILES.md`
  (donde dice "una vez al día").

### 4.2 Semana y mes a la vez

**Ruta** `GET /dashboard`: deja de leer `period_type` y `period_start`; construye
`week = svc.period("WEEKLY")` y `month = svc.period("MONTHLY")` y pasa ambos al contexto.
Los parámetros antiguos se ignoran (los enlaces viejos siguen funcionando).

**Servicio** `DashboardService`: se separa lo que depende del período de lo que no.

- `agent_period_block(agent, period)` → `objective_kpis`, `activity_kpis`, `objective_keys`,
  `has_target`, `completion`, `ranking`, `admin_notes`, `period`.
- `admin_period_block(period)` → `kpis`, `completion_avg`, `completion_agents`, `team`
  (filas con celdas, % global y tendencia), `objective_keys`, `missing_targets`, `period`.
- `agent_home(agent)` → `{"week": block, "month": block, "agenda", "portfolio", "trend",
  "pending_buyers", "pending_summary"}`.
- `admin_home()` → `{"week": block, "month": block, "activity_kpis" (visitas y contactos del
  mes con delta), "pending", "abandoned", "attention", "feed", "trend", "pending_by_agent"}`.
- `attention` avisa de objetivos sin definir **de la semana y del mes**.
- Tendencia: sigue siendo semanal (8 semanas agente, 12 equipo).
- `team_rows` devuelve además `completion_sort` y cada celda `sort_value`, para la ordenación.

**Inicio del agente** (`_agent.html`), sección "Mis resultados":

```
┌ Esta semana · 13–19 oct ──────────┐ ┌ Este mes · octubre ───────────────────┐
│ (anillo) Capt. 2/3   (anillo) Baj. │ │ (anillo) Capt.  (anillo) Baj.  (anillo) Cierres │
│ Global 67 % · puesto 2 de 5        │ │ Global 50 % · puesto 3 de 5                      │
│ Visitas 4 · Contactos 11           │ │ Visitas 12 · Contactos 38                        │
└────────────────────────────────────┘ └──────────────────────────────────────────────────┘
```

Dos tarjetas, lado a lado en escritorio y apiladas en móvil. Anillos solo para métricas con
objetivo; visitas y contactos como línea de texto. Si no hay objetivo en un período, la
tarjeta lo dice ("Sin objetivos esta semana; los define el administrador").
"Observaciones del administrador" muestra la nota de la semana y la del mes si existen.

**Inicio del admin** (`_admin.html`):

- Fila 1 (no depende del período): Compradores pendientes · Abandonados · Visitas del mes ·
  Contactos del mes.
- Fila 2 "Esta semana": Captaciones · Bajadas · Cumplimiento medio.
- Fila 3 "Este mes": Captaciones · Bajadas · Cierres · Cumplimiento medio.
- Tabla "Cumplimiento del equipo" con cabecera agrupada:

```
Agente │ SEMANA 13–19 oct            │ MES octubre                            │ MES
       │ Capt.  Bajadas  Global      │ Capt.  Bajadas  Cierres  Global        │ Visitas Contactos
```

  Cada celda con objetivo conserva barra + % + "valor / objetivo"; Global con badge y
  flecha frente al período anterior (semana anterior / mes anterior).
- Se quita `period_nav` de `home.html`; el componente se borra si no lo usa nadie más.
  Enlace "Ver histórico y año" a `/commercial-results?tab=rendimiento`.

### 4.3 Tabla ordenable

- El script de `properties/home.html` pasa a `ui.js` como `UI.sortableTables()` (se ejecuta
  solo al cargar sobre `table.js-sortable`); Propiedades sigue funcionando igual.
- La tabla del equipo lleva `js-sortable` y `data-table-id="teamTable"`; cada `th` ordenable
  lleva `data-sort-type` (`text` o `number`), indicador ↕ / ↑ / ↓, `aria-sort` y área táctil
  de 40 px; cada `td` lleva `data-sort-value`.
- Primer clic en una métrica: de mayor a menor; en Agente: A → Z. Filas sin valor al final.
- El orden se guarda en `localStorage` (`sort:teamTable`) y se reaplica al cargar.

## 5. Fases y archivos

| Fase | Qué | Archivos |
|---|---|---|
| 1 | Aviso: encuadre móvil y apertura por inicio de sesión | `components/ui_macros.html`, `.claude/.../assets/ui_macros.html`, `routes/auth.py`, `static/js/dashboard.js`, `dashboard/_admin.html`, `dashboard/_agent.html`, `PLAN_DASHBOARD_INICIO.md`, `PLAN_ALERTAS_DIAS_HABILES.md`, test de ruta del login |
| 2 | Ordenación de tablas en `ui.js` + tabla del equipo ordenable | `static/js/ui.js`, `.claude/.../assets/ui.js`, `properties/home.html`, `dashboard/_admin.html` |
| 3 | Servicio y ruta con dos períodos | `services/dashboard_service.py`, `routes/dashboard.py`, `tests/test_dashboard_service.py`, `tests/test_dashboard_routes.py` |
| 4 | Plantillas de Inicio con semana y mes | `dashboard/home.html`, `_admin.html`, `_agent.html`, `components/period_nav.html` (borrar), `components/kpi.html` si hace falta |
| 5 | QA: linter del skill, render de `/dashboard` como admin y agente en ambas empresas, tests, prueba manual a 375 px | — |

Un commit por fase. Reinicio del contenedor tras cada fase (Jinja cachea).

### Estado (2026-10-19)

- [x] Fase 1: macro con `!mt-0` y padding móvil; cookie `moyza_welcome` en el login;
      `dashboard.js` abre `[data-auto-open-on-login]` y la consume; planes actualizados.
- [x] Fase 2: `UI.sortableTables()` en `ui.js` (indicador, `aria-sort`, teclado, memoria en
      `localStorage`, `data-sort-col` para cabeceras agrupadas); Propiedades usa el mismo código.
- [x] Fase 3: `DashboardService.current_periods`, `agent_period_block`, `admin_period_block`,
      `team_objective_kpis`, `team_activity_kpis`, `team_table`; `attention(missing_targets=…)`;
      ruta sin período (parámetros heredados ignorados). Tests actualizados.
- [x] Fase 4: `home.html` sin selector (enlace "Ver histórico y año"), `_agent.html` con dos
      tarjetas (semana / mes), `_admin.html` con KPIs generales + semana + mes y la tabla original
      (semana en curso) ordenable; `period_nav.html` eliminado. CSS de Tailwind recompilado.
      (2026-10-20: la tabla de dos grupos de columnas se descartó a petición del usuario; D3.)
- [x] Fase 5: 85 tests de Inicio / atención / rendimiento en verde más el resto de suites;
      render de `/dashboard` como admin y agente en MOYZA y MOES; linter sin avisos.
      Pendiente de prueba manual en el móvil (375 px): aviso al iniciar sesión y tabla con scroll.

## 6. Fuera de alcance

- Prorratear objetivos o heredarlos entre períodos.
- Objetivos anuales en Inicio (quedan en Resultados Comerciales).
- Guardar la preferencia de orden en servidor.
