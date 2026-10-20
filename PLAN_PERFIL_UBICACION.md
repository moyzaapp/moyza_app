# Plan: ubicación del perfil en cascada (País → Provincia → Población → Zona), operación editable y mínimos en la ficha del comprador

Fecha: 2026-10-19. Rama: `63-agregar-moes`.

## Objetivo

Que el bloque de ubicación del perfil de búsqueda se parezca al de InmoPC
(captura del usuario): **País** y **Provincia** como desplegables, **Población**
y **Zona** como listas de casillas con la opción **"Todas"**, cada nivel
filtrado por el anterior. Además: la **operación** (Venta/Alquiler) se puede
cambiar desde el perfil y actualiza la alerta; y el formulario de perfil de la
**ficha del comprador** exige los mismos mínimos que el de la alerta
("Alinealo", deuda de `PLAN_PERFIL_OBLIGATORIO.md`).

## Decisiones cerradas con el usuario (no cambiar)

1. **Provincia sin columna en propiedades**: se deduce del código postal
   (`cod_postal`, dos primeros dígitos → provincia española). Las propiedades
   sin CP válido quedan "Sin provincia" y solo aparecen al filtrar por país o
   por población/zona directamente.
2. **Operación editable en el perfil de la alerta**: al cambiarla, cambia
   `alert.business_type`, queda en la nota del seguimiento
   ("Operación: Venta → Alquiler") y las sugerencias se recalculan.
3. **Población múltiple con "Todas"**; **Zona múltiple con "Todas"** (las zonas
   mostradas son las de las poblaciones marcadas).
4. Mínimos del perfil (`PLAN_PERFIL_OBLIGATORIO.md`): tipo de inmueble, precio
   máximo y **ubicación**. Con la cascada, "ubicación" = provincia elegida
   (aunque sea con "Todas" las poblaciones) **o** al menos una población **o**
   al menos una zona. Actualizar `profile_is_complete` /
   `missing_profile_fields` en consecuencia (sigue siendo la única definición).

## Decisiones de diseño tomadas en este plan (cámbialas solo si rompen algo, y anótalo)

- El perfil guarda **país y provincia** en dos columnas nuevas de
  `buyer_search_criteria` (`country`, `province`, String nullable) para que
  "Todas las poblaciones" signifique "cualquier población de esa provincia,
  también las que entren mañana". `cities` y `zones` siguen siendo listas;
  **lista vacía = Todas**. Una migración (NO ejecutar).
- País vacío en una propiedad se trata como **"España"** en la cascada y en el
  filtro (la inmensa mayoría no lo tiene relleno).
- Tabla de provincias por prefijo de CP (01 Álava … 52 Melilla) en un módulo
  nuevo `app/core/geo.py`: `provincia_from_cp(cp) -> str | None` y
  `cp_prefix_for_provincia(nombre) -> str | None`. `Property.provincia` como
  `@property` de solo lectura que usa `cod_postal` (y `None` si el país no es
  España).
- En el **formulario de propiedad**, junto al código postal, un texto de ayuda
  de solo lectura "Provincia (según CP): Jaén" que se actualiza al escribir
  (pequeño JS; sin campo nuevo).
- La cascada se alimenta de las propiedades **no archivadas de la empresa
  activa** (igual que las sugerencias). Se calcula en servidor con una sola
  consulta `DISTINCT (pais, cod_postal, city, zona)` y se incrusta en la
  página como JSON (`<script type="application/json" id="geoData">`); el JS
  rellena los niveles. Tamaño esperado: cientos de filas, no miles.
- País con una sola opción → preseleccionado y el desplegable deshabilitado.
  Provincia vacía → se muestran todas las poblaciones del país.
- La ficha del comprador usa el mismo partial, con los mismos mínimos; allí
  la operación sí es editable como hoy y **no** registra ningún seguimiento
  (no hay alerta).
- El cambio de operación desde el perfil de la alerta solo se permite si la
  alerta está abierta; para una alerta con propiedad asociada cuya operación
  ya no coincide, se mantiene la propiedad y se muestra un aviso en Propuesta
  ("La propiedad asociada es de Venta y el comprador busca Alquiler").

## Cambios por archivo

- `app/core/geo.py` (nuevo): tabla y funciones. Tests de la tabla (52
  provincias, prefijos 01–52, CP inválidos → None).
- `app/models/property.py`: `@property provincia`.
- `app/models/buyer_search_criteria.py`: `country`, `province`.
- `alembic/versions/<nuevo>_criteria_country_province.py`: `down_revision` =
  head actual (confirmar con `python -m alembic heads`); añade las dos
  columnas; downgrade las quita.
- `app/services/buyer_matching.py`:
  - `geo_options(db, company_id) -> dict` con la estructura anidada
    `{pais: {provincia: {poblacion: [zonas]}}}` más la lista de propiedades
    sin provincia agrupadas bajo `"Sin provincia"`.
  - `apply_profile`: acepta `country`, `province`; `cities`/`zones` vacías =
    Todas.
  - `matching_properties_query`: filtra por país (`coalesce(pais,'España')`),
    por provincia (`cod_postal LIKE 'NN%'`), por `cities` y `zones` solo si
    no están vacías.
  - `criteria_parts`/`criteria_summary`: incluir provincia ("Jaén · Todas las
    poblaciones" / "Jaén · Jaén, Martos · Zona Centro").
  - `profile_is_complete` / `missing_profile_fields`: ubicación según
    decisión 4.
- `app/web/routes/alerts.py`:
  - `_property_filter_values` → usar `geo_options` (y mantener tipos).
  - `save_alert_search_profile` y `add_follow_up` (Contactado): leer
    `country`, `province`, `business_type`; si la operación cambia, actualizar
    la alerta y añadir a la nota; validar mínimos nuevos.
  - `save_search_criteria` (ficha del comprador): validar mínimos; `country`,
    `province`.
- `app/web/templates/components/search_profile_form.html`: bloque de
  ubicación nuevo (dos `select` arriba, dos listas de casillas con "Todas"
  debajo; estilo del sistema: `ui.select`, casillas como las actuales). La
  operación pasa a `select` también en la alerta (precargado con la de la
  alerta), con texto de ayuda "Si la cambias, cambia la operación de la alerta".
- `app/static/js/search-profile.js`: cascada (país → provincia → poblaciones →
  zonas), "Todas" (marca/desmarca y deshabilita las demás), precarga desde el
  perfil guardado, validación de mínimos antes de enviar (provincia o
  población o zona).
- `app/web/templates/properties/form.html`: ayuda "Provincia (según CP)".
- `alerts/_search_steps.html` (Propuesta): aviso si la propiedad asociada no
  coincide con la operación del perfil.
- Documentación: `docs/DECISIONES_ALERTAS_BUSQUEDA.md` §6 (ubicación en
  cascada, provincia derivada del CP, operación editable); nota en
  `PLAN_PERFIL_OBLIGATORIO.md` sobre el mínimo de ubicación.

## Tests (SQLite en proceso, patrón `tests/test_profile_required.py`)

- `geo.py`: tabla completa, `23004 → Jaén`, `28001 → Madrid`, `"" / None /
  "ABCDE" / "99999" → None`; `cp_prefix_for_provincia("Jaén") == "23"`.
- `geo_options`: agrupa bien; país vacío → España; propiedad sin CP → "Sin
  provincia"; solo propiedades de la empresa activa y no archivadas.
- Matching: provincia filtra por prefijo de CP; `cities` vacío = todas;
  zonas de varias poblaciones; país distinto excluye.
- Mínimos: provincia sola completa la ubicación; sin país/provincia/población/
  zona → falta ubicación.
- Operación: cambiar en el perfil de la alerta actualiza `alert.business_type`
  y la nota lleva "Operación: Venta → Alquiler"; alerta cerrada → rechazado.
- Ficha del comprador: guardar sin mínimos → error; con mínimos → OK sin
  seguimientos.
- Render del partial: dos selects, dos listas con "Todas", JSON `geoData`
  presente; precarga de un perfil con provincia y dos poblaciones.
- Migración: archivo presente, `--sql` muestra las dos columnas.
- Suite completa: el conjunto de fallos no cambia (previo conocido:
  `test_scheduler.py::test_check_automatic_reports_con_propiedad_activa`;
  errores de integración por falta de PostgreSQL).

## Verificación adicional

`python -c "import app.main"`; plantillas compilan; `node --check` del JS;
`bash backend/scripts/build_css.sh` + clases nuevas en el CSS;
`ui_lint.py` sin avisos nuevos (antes y después). Leer
`.claude/skills/moyza-ui-ux-pro/SKILL.md`, `references/components.md` y
`references/ux-rules.md` antes de tocar plantillas.

## Entrega

Sin commits. **Sin ejecutar la migración.** Informe con archivos tocados,
decisiones donde el plan dejaba margen, resultados con números, pasos de prueba
manual (agente: perfil con España → Jaén → Todas → zonas; cambiar operación;
ficha del comprador sin mínimos), recordatorio de `alembic upgrade head`,
riesgos y deuda. Marcar "Estado".

## Estado

- [x] `geo.py`, `Property.provincia`, columnas `country`/`province` + migración (`a0b1c2d3e4f5`, NO ejecutada)
- [x] `buyer_matching`: `geo_options`, matching por país/provincia, mínimos de ubicación, resumen
- [x] Partial del perfil en cascada + JS; operación editable en la alerta (actualiza alerta y nota)
- [x] Ficha del comprador con mínimos; ayuda de provincia en el formulario de propiedad
- [x] Tests, documentación, lint, CSS

Sin commits. Pendiente en producción: `alembic upgrade head` y reiniciar la app.

### Notas de implementación (2026-10-19)

Ninguna decisión cerrada ni de diseño se ha cambiado. Donde el plan dejaba margen:

- **Etiqueta del mínimo**: "zona o ciudad" pasa a **"ubicación"** en
  `missing_profile_fields` (mensajes "Falta: …"); `has_location` es el helper
  nuevo. El país solo no completa la ubicación.
- **País**: se normaliza (vacío, "españa", "Spain", "ES", "esp" → "España") en
  la cascada y en el filtro, para no tener "España" y "españa" repetidos. Con
  varios países el desplegable tiene "Todos los países"; con uno, va
  deshabilitado y se envía en un `hidden`.
- **Provincia**: CP de exactamente cinco dígitos y prefijo 01–52 (sin rellenar
  ceros de CP de cuatro cifras). El filtro SQL es `trim(cod_postal) LIKE 'NN___'`
  y además exige España. `apply_profile` solo guarda provincias de la tabla y
  con país España (si no hay país, pone España). "Sin provincia" agrupa
  poblaciones en el árbol, pero no es elegible en el desplegable: esas
  poblaciones salen con "Todas las provincias".
- **"Todas"**: marcada, las demás casillas salen marcadas y **deshabilitadas**
  (no se envían → lista vacía = Todas). Desmarcar la última casilla vuelve a
  "Todas". Las propiedades sin población no entran en la cascada (no hay dónde
  colgar su zona).
- **Estado inicial en servidor** (`buyer_matching.geo_choices`): el servidor
  pinta los cuatro niveles precargados y el JS solo reconstruye al cambiar. Un
  perfil antiguo (sin país ni provincia) abre con España y "Todas las
  provincias"; sus poblaciones/zonas que ya no existan se muestran marcadas
  para no perderlas al guardar.
- **JSON**: un `<script type="application/json" id="geoData-{prefijo}">` por
  formulario (en el detalle de la alerta hay dos: paso Perfil `sp` y modal
  `fu`), para no duplicar ids.
- **Operación**: select en todos los usos del partial; en la alerta precargado
  con la de la alerta y la ayuda "Si la cambias, cambia la operación de la
  alerta". Nota del seguimiento: nota del agente, "Operación: A → B" y resumen
  del perfil, una línea cada una. En el paso Perfil el flash añade "La alerta
  pasa a Alquiler". Operación no válida → error; alerta cerrada → paso Perfil
  rechazado ("La alerta está cerrada") y Contactado con cambio rechazado ("La
  alerta está cerrada: no se puede cambiar la operación"). País y operación no
  cuentan como "datos del perfil presentes" en Contactado (salen
  preseleccionados).
- **Aviso en Propuesta**: compara la operación de la propiedad asociada con la
  del perfil (o la de la alerta si el perfil no la tiene); sale en los dos
  estados de la Propuesta (con y sin perfil completo).
- **Resumen**: con provincia, "Jaén · Todas las poblaciones" / "Jaén · Jaén,
  Martos · Zona Centro"; sin provincia, como antes ("Centro, Jaén +1"). El país
  solo se nombra si no es España.
- **Formulario de propiedad**: la tabla de provincias llega al JS por el global
  de Jinja `geo_cp` (una sola fuente: `app/core/geo.py`); la plantilla tolera
  un proceso sin ese global (plantilla nueva con Python sin reiniciar).
