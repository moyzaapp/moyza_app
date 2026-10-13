# Plan: paginación de /alerts (Compradores)

Fecha: 2026-10-14. Rama: `57-cambios-de-visitas-compradores-y-otros`.

## Contexto y objetivo

`/alerts` ya responde en 350–460 ms en producción (antes ~3.000 ms) tras agrupar
consultas e indexar (commit `bbb2e0b`). Lo que queda es el navegador: la tabla de
alertas se pinta completa (1.218 filas en producción, ~8,9 MB de HTML para el admin,
3.654 SVG y 3.654 botones) y la tabla de Compradores también. El navegador tarda
varios segundos en construir el DOM, generar estilos y calcular la disposición.

Objetivo: que el tamaño de la página **no dependa del total de alertas ni de
compradores**. Paginación en servidor, filtros que siguen buscando en todo, y
contadores que siguen siendo totales reales.

## Decisiones cerradas con el usuario (no cambiar)

- **Tamaño de página**: 50 / 100 / 200 / 300. **Por defecto 100.** Un solo selector
  para las dos tablas (alertas y compradores). Sin opción "Todas".
- **Vista por defecto de alertas** (sin `q` y sin `status_filter`): solo
  `PENDING` + `IN_PROGRESS`. Las casillas Pendiente y En Proceso aparecen marcadas
  para que el usuario entienda qué está viendo.
- **Buscar texto (`q`) sin marcar ningún estado** busca en **todos** los estados
  (si no, buscar un comprador con alerta completada daría "sin resultados").
- **Los filtros siguen aplicándose sobre todas las alertas** (filtrar → ordenar →
  página N). Al cambiar de página se conservan `q`, `status_filter`, `agent_id`
  y `per_page`.
- **Contadores de las tarjetas** (Pendientes / En proceso / Completadas): totales
  por estado bajo los filtros de texto y agente, pero **antes** del filtro de
  estado y sin paginar. Hoy se calculan después del filtro de estado; hay que
  moverlos.
- **Compradores**: se pagina también, con su propio número de página y su propio
  buscador (nombre, teléfono o email). El `<select>` de compradores del modal
  "Agregar alerta con filtro" (`fcBuyerSelect`) se sustituye por el autocompletado
  que ya usa "Agregar alerta comprador" (`/alerts/search-buyers`), porque ese
  select carga todos los compradores de la empresa.
- **Preferencia persistente**: cuando llega `per_page` explícito, se guarda en una
  cookie `alerts_per_page` (1 año, `samesite=lax`); cuando no llega, se usa la
  cookie y, si no hay, 100. Valores fuera de la lista → 100.

## Qué NO cambia

- Reglas de acceso (`visible_buyers_query`, `can_access_buyer`), orden de las
  alertas (prioridad, luego fecha desc), orden de compradores (nombre asc).
- El **bloqueo de la cola** (`get_locked_alert_ids`) se sigue calculando sobre
  **toda** la cola del agente, no sobre la página.
- `alert_stages` solo para las alertas de la página (ya se cargan sus
  `follow_ups` con `selectinload`).
- Los demás contextos del template (`assignable_groups`, `other_company_alerts`,
  valores de filtros, `AlertStatus`, etc.).
- Ningún otro listado de la app. Solo `/alerts`.

## Archivos que toca este plan (y solo estos)

- `backend/app/web/routes/alerts.py` — ruta `alerts_page` y helpers.
- `backend/app/web/templates/alerts/list.html`.
- `backend/app/web/templates/components/ui_macros.html` — nuevo macro `pagination`.
- `backend/tests/test_alerts_pagination.py` — nuevo.
- Este archivo (marcar estado al terminar).

**Prohibido tocar**: `base.html`, `Dockerfile`, cualquier cosa en `app/static/`,
`template_env.py`, `main.py`. Otro agente trabaja en paralelo sobre esos archivos
(build de Tailwind). No hacer commits.

## Diseño

### Parámetros de la ruta `GET /alerts`

| Parámetro | Tipo | Default | Notas |
|---|---|---|---|
| `q` | str | "" | ya existe |
| `status_filter` | list[str] | [] | ya existe |
| `agent_id` | str | None | ya existe (solo admin) |
| `page` | int ≥ 1 | 1 | página de alertas |
| `per_page` | int | cookie o 100 | validar contra `PAGE_SIZES = (50, 100, 200, 300)` |
| `b_q` | str | "" | búsqueda de compradores |
| `b_page` | int ≥ 1 | 1 | página de compradores |

Fuera de rango (página mayor que el total): mostrar la última página válida, no
error. `page` no numérico → 1.

### Orden de cálculo en la ruta

1. `base_query` con empresa, agente (si no es admin), `q`, `agent_id`. **Sin estado.**
2. `status_counts` por `GROUP BY status` sobre (1) → tarjetas.
3. Determinar estados efectivos: `status_filter` válidos; si vacío y `q` vacío →
   `[PENDING, IN_PROGRESS]`; si vacío y `q` con texto → sin filtro de estado.
4. `filtered = base_query.filter(status in efectivos)` si aplica.
5. `total_alerts = filtered.count()` (sobre `PropertyAlert.id`; ojo con el JOIN
   a `Agent` y `Property` que ya hace la consulta: usar `with_entities(func.count(PropertyAlert.id))`
   o `.count()` tras comprobar que no multiplica filas — no hay 1:N en esos joins).
6. `alerts = filtered.options(contains_eager…, selectinload(follow_ups)).order_by(…).offset((page-1)*per_page).limit(per_page).all()`.
7. Compradores: `visible = visible_buyers_query(...)`; si `b_q`, filtrar por
   `ilike` en nombre / teléfono / email; `total_buyers = count`; página con
   `offset/limit`; `buyer_alert_counts` solo para los compradores de la página;
   `buyer_operation_counts` sobre **todos** los visibles (es un `GROUP BY`, es
   barato, y así el desglose "N Venta / N Alquiler" sigue siendo el total).
8. Resto igual que hoy.

Extraer la aritmética de paginación a una función pura reutilizable (por ejemplo
`paginate_params(page, per_page, total) -> dict(page, per_page, total, pages,
offset, start, end, has_prev, has_next)`) y testearla sin BD.

### Macro `pagination` en `components/ui_macros.html`

Firma sugerida: `pagination(p, param="page", label="alertas")` donde `p` es el
dict anterior y `param` el nombre del parámetro de página (`page` o `b_page`).
Debe construir enlaces **conservando el resto de la query string** (usar
`request.query_params` y reemplazar solo el parámetro de página; cuidado con
`status_filter` que es multivalor: no colapsarlo).

Contenido:
- Texto "Mostrando 1–100 de 633 alertas" (o "Sin resultados").
- Anterior / Siguiente con área táctil ≥ 40 px, deshabilitados en los extremos
  (`aria-disabled`, sin `href`).
- Números de página compactos: primera, …, actual ±2, …, última. En móvil
  (`sm:hidden`) solo "Página 3 de 7" + Anterior/Siguiente.
- `<nav aria-label="Paginación de {label}">`, página actual con `aria-current="page"`.
- Estilo según `.claude/skills/moyza-ui-ux-pro/references/tokens.md` y
  `components.md`: botones secundarios (`bg-white border border-gray-300`,
  `rounded-xl`), actual `bg-gray-900 text-white`. Sin colores semánticos.

### Selector de tamaño de página

Un `<select name="per_page">` dentro del **formulario de filtros** existente
(junto al botón Filtrar), con `onchange="this.form.requestSubmit()"` y las
cuatro opciones. Al cambiar, vuelve a página 1 (no incluir `page` en ese form,
o ponerlo a 1). Etiqueta visible "Por página" y `aria-label`.

Como las dos tablas comparten `per_page`, los enlaces de paginación de
compradores también lo conservan (lo hace solo si se preserva la query string).

### Template `alerts/list.html`

- Casillas de estado: marcadas según los **estados efectivos** (no solo
  `status_filter` crudo), para que la vista por defecto muestre Pendiente y
  En Proceso marcadas. Pasar `effective_statuses` al contexto.
- Si la vista es la por defecto, un texto discreto bajo los filtros: "Mostrando
  alertas pendientes y en proceso. Marca Completada o Cancelada para verlas."
- "Limpiar filtros" → `/alerts` (vuelve al defecto). Mostrarlo también cuando
  hay `page>1`, `b_q` o `per_page` distinto del por defecto no es necesario;
  mantener la condición actual.
- Paginación de alertas al pie de su tabla; paginación de compradores al pie de
  la suya. En ambas, encima de la tabla, el "Mostrando X–Y de Z".
- Sección Compradores: añadir un buscador propio (`<form method="GET">` con
  `b_q` y **campos ocultos** para `q`, `status_filter` (uno por valor),
  `agent_id`, `per_page`, para no perder los filtros de alertas al buscar
  compradores). Botón "Buscar" y enlace "Limpiar" que quita solo `b_q`/`b_page`.
- El contador del título "Compradores (N)" y los badges "N Venta / N Alquiler"
  deben seguir mostrando totales, no el tamaño de página.
- Columna "Alertas" de compradores usa `buyer_alert_counts` (ya es así).
- Modal "Agregar alerta con filtro": quitar el `<select id="fcBuyerSelect">` y
  el bucle `{% for buyer in buyers %}` de las líneas ~1181-1188. Poner un
  input de búsqueda con autocompletado contra `/alerts/search-buyers` (copiar el
  patrón del modal "Agregar alerta comprador": input visible, lista de
  resultados, `input hidden name="buyer_id"`, navegación con teclado si el
  patrón existente la tiene). Ajustar `setFcBuyerMode` y la validación al enviar
  ("Selecciona un comprador de la lista o cambia a 'Nuevo comprador'").
  Cualquier otro `{% for buyer in buyers %}` fuera de la tabla (hay uno en ~654)
  debe revisarse: si alimenta un select con todos los compradores, sustituir
  por autocompletado; si es otra cosa, dejarlo.
- Estado vacío de alertas: si no hay resultados **y** la vista es la por
  defecto, el mensaje debe sugerir marcar Completada/Cancelada o limpiar filtros.
  Usar el macro `empty_state` si encaja.

### Diseño/UX

Antes de escribir HTML, leer `.claude/skills/moyza-ui-ux-pro/SKILL.md`,
`references/tokens.md`, `references/components.md` y `references/ux-rules.md`.
Al terminar, ejecutar
`python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates`
desde la raíz del repo y dejar `alerts/list.html` sin avisos nuevos.

## Verificación (sin base de datos disponible en esta máquina)

No hay Docker ni PostgreSQL en el entorno de desarrollo; `fetch_page.py` no se
puede usar. Verificar así:

1. `python -c "import app.main"` desde `backend/` (la app importa).
2. Compilar `alerts/list.html` y `components/ui_macros.html` con el entorno de
   `app.web.template_env.templates`.
3. **Render con datos falsos**: renderizar `alerts/list.html` con 100 alertas y
   100 compradores de prueba (objetos `SimpleNamespace` sirven; ver cómo se hizo
   en la sesión: se cargó el bloque del bucle con `env.from_string`). Comprobar
   que la paginación muestra "1–100 de 1218" cuando `total=1218`, que los
   enlaces conservan `q`, `status_filter` multivalor y `per_page`, y que el HTML
   de la tabla baja a menos de 1 MB para el admin.
4. Tests nuevos en `backend/tests/test_alerts_pagination.py`:
   - función pura de paginación: límites, página fuera de rango, `per_page`
     inválido → 100, `start/end` correctos, 0 resultados.
   - estados efectivos: sin filtros → `[PENDING, IN_PROGRESS]`; con `q` y sin
     estados → `None`; con estados → esos.
   - si los tests de rutas existentes (`tests/test_alert_assignment_routes.py`)
     tienen un patrón que funcione sin BD real, añadir un test de la ruta que
     compruebe que `page=2&per_page=50` devuelve las alertas 51-100 y conserva
     filtros en los enlaces. Si requieren la app levantada, marcarlos con el
     mismo `skip` que usan ellos.
   - pytest no está instalado en el venv local (`/home/jnausa/entornos/pruebas_moyza`).
     Instalarlo con `pip install pytest` (dependencia de desarrollo, no va a
     `requirements.txt`) y dejarlo anotado en el informe final.
5. Ejecutar **toda** la suite `python -m pytest -q tests` y que no empeore
   (hay un test previo que falla y es ajeno:
   `test_check_automatic_reports_con_propiedad_activa`).
6. `ui_lint.py` sin avisos nuevos en `alerts/list.html`.

## Entrega

Sin commits. Informe final con: archivos tocados, decisiones tomadas donde el
plan dejaba margen, resultado de cada verificación (con números: tamaño de HTML
antes/después, tests pasados/fallados), y cualquier duda o deuda que quede.
Actualizar la sección "Estado" de este archivo.

## Estado

- [x] Ruta y helper de paginación (`PAGE_SIZES`, `normalize_per_page`,
      `paginate_params`, `effective_alert_statuses`; contadores antes del filtro
      de estado; cookie `alerts_per_page`)
- [x] Macro `pagination` (+ `pagination_summary`; recibe `request.query_params`
      porque los macros se importan sin contexto)
- [x] Template: filtros, selector, dos paginaciones, buscador de compradores
- [x] Modal "Agregar alerta con filtro" con autocompletado
- [x] Tests (`tests/test_alerts_pagination.py`: 45 tests; la ruta se prueba en
      proceso contra SQLite en memoria, sin app ni PostgreSQL)
- [x] Lint UI y render de prueba (list.html: 31 avisos antes y 31 después, mismas
      reglas; 1218 alertas: tabla 8,6 MB → 0,71 MB con 100 por página)
