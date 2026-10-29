# Plan: zonas por población, zona y dormitorios máx. obligatorios y filtro de ascensor en el perfil del comprador

Fecha: 2026-10-28 · Rama `63-agregar-moes`

## 1. Cómo funciona hoy

Formulario `components/search_profile_form.html` + `static/js/search-profile.js` + `services/buyer_matching.py`
(`geo_options`, `geo_choices`, `missing_profile_fields`, `_matching_filters`). Lo usan la ficha del comprador,
el paso "Perfil" de la alerta y el modal de seguimiento (solo Venta: en Alquiler el perfil está oculto).

| Punto | Hoy |
|---|---|
| Origen de poblaciones y zonas | Se leen de las **propiedades** de la empresa (`Property.city`, `Property.zona`, texto libre en el formulario de propiedad). Solo hay zonas si alguna propiedad las tiene escritas. |
| Población | Lista de casillas con "Todas" marcada por defecto (lista vacía = todas). |
| Zona | Lista de casillas con "Todas" marcada por defecto. **Con "Todas" las poblaciones, salen las zonas de todas las poblaciones juntas** (de ahí la mezcla de zonas de Jaén con pueblos). Al marcar poblaciones concretas se filtra a las suyas, pero sin agrupar. |
| Mínimo de ubicación | Provincia, o al menos una población o una zona. |
| Mínimos del perfil (Venta) | Tipo de inmueble, precio máximo y ubicación. Dormitorios y baños opcionales. |
| Ascensor | No existe en el perfil. En la propiedad hay `num_ascensores` (número). "Imprescindibles" es texto libre y su ejemplo menciona "ascensor". |

Dato: en la base local casi todas las propiedades están en "Jaen"/"Jaén" sin zona (solo una tiene
"Fuentezuelas"). En producción habrá más zonas. Ojo con "Jaen" y "Jaén": al ser texto libre salen como dos
poblaciones distintas (ver §4-5).

## 2. Cambio propuesto

### 2.1 Zonas por población

- La lista **Zona no aparece** hasta que el agente marca al menos una población concreta (con "Todas" las
  poblaciones no hay bloque de zonas).
- Al marcar poblaciones, salen **solo las zonas de esas poblaciones**. Con más de una población con zonas, se
  agrupan bajo un título por población ("Jaén", "Mancha Real"…). Las poblaciones sin zonas registradas no
  pintan grupo.
- **"Todas" las zonas deja de venir marcada**: el agente tiene que marcar zonas concretas o marcar "Todas" a
  propósito. Guardado: zonas concretas → lista; "Todas" → lista vacía (como hoy).
- Al editar un perfil guardado, se pinta tal cual se guardó (poblaciones marcadas, sus zonas, "Todas" si la
  lista de zonas está vacía).

### 2.2 Obligatorios nuevos

- **Población**: al menos una concreta (ver §4-1). La provincia sigue preseleccionada por el CP de las propiedades.
- **Zona**: obligatoria (al menos una zona o "Todas" marcada a propósito) **solo si alguna población marcada
  tiene zonas registradas**. Una población sin zonas no bloquea.
- **Dormitorios máx.**: obligatorio en el perfil (mínimos: tipo, precio máx., dormitorios máx. y ubicación).
  "Dormitorios mín." sigue opcional. Se valida en servidor (`missing_profile_fields`) y en el formulario
  (asterisco y `required`, siguiendo el mecanismo actual por operación: solo en Venta).
- Donde el perfil es opcional (alerta en Venta ya completa… no aplica: en Venta es obligatorio; en Alquiler
  está oculto; en la ficha del comprador es `required=True`): los nuevos mínimos entran por el mismo camino.
- Perfiles ya guardados sin dormitorios máx. o sin zona: pasan a "incompletos" y el agente los completa la
  próxima vez que registre un seguimiento (el bloqueo de etapas ya existe para perfiles incompletos). Ver §4-4.

### 2.3 Ascensor

- Campo nuevo `elevator` en `buyer_search_criteria` (migración `e4f5a6b7c8d9`): `NULL` = indiferente,
  `true` = con ascensor, `false` = sin ascensor. Selector "Ascensor: Indiferente / Con ascensor / Sin
  ascensor" (ver §4-2), opcional, por defecto Indiferente.
- Cruce con propiedades (`_matching_filters`): con ascensor → `num_ascensores >= 1`; sin ascensor →
  `num_ascensores` es 0 o NULL.
- Resumen del perfil (`criteria_parts`, se ve en la alerta y en la ficha): añade "con ascensor" / "sin ascensor".
- Se quita "ascensor" del ejemplo de "Imprescindibles".

### 2.4 Archivos

- `services/buyer_matching.py`: `geo_choices` (zonas agrupadas por población, sin "Todas" por defecto),
  `has_location` / `missing_profile_fields` (población, zona condicionada, dormitorios máx.),
  `PROFILE_MINIMUM_LABELS`, `_matching_filters`, `criteria_parts`, `apply_profile(elevator=…)`.
- `components/search_profile_form.html` + `static/js/search-profile.js`: bloque de zonas oculto hasta marcar
  población, grupos por población, validación de zona condicionada, selector de ascensor.
- `routes/alerts.py` (`PROFILE_TEXT_FIELDS`, formularios de perfil de la alerta y de la ficha del comprador).
- `models/buyer_search_criteria.py`, migración.
- Tests: `tests/test_profile_location.py`, `tests/test_profile_required.py`, `tests/test_alert_search.py` y
  uno nuevo para el ascensor.
- Docs: nota en `MULTIEMPRESA_MOYZA_MOES.md` §21 (migración).

## 3. Fases

| Fase | Contenido | Commit |
|---|---|---|
| A | Zonas por población, zona sin "Todas" por defecto, población y zona obligatorias | `feat(perfil): zonas por población, obligatorias sin marcar todas por defecto` |
| B | Dormitorios máx. obligatorio | `feat(perfil): dormitorios máximos obligatorios` |
| C | Filtro de ascensor (migración) | `feat(perfil): filtro de ascensor en el perfil del comprador` |

## 4. Decisiones (2026-10-28)

1. **Población obligatoria**: sí. Se quita la casilla "Todas" de Población: hay que marcar al menos una
   concreta. (La provincia sigue como está.) Perfiles antiguos con lista de poblaciones vacía se pintan sin
   ninguna marcada; al guardarlos de nuevo habrá que marcar alguna.
2. **Ascensor**: tres opciones "Indiferente / Con ascensor / Sin ascensor".
3. **Ascensor**: opcional, "Indiferente" por defecto.
4. **Solo perfiles nuevos**: los mínimos nuevos (población concreta, zona si la población tiene zonas,
   dormitorios máx.) se exigen a los perfiles creados a partir del despliegue. Implementación: ajuste
   `PROFILE_MINIMUMS_SINCE` (config, fecha de Madrid; por defecto 2026-10-29, se pone en `.env` si el
   despliegue es otro día) y `missing_profile_fields` aplica la regla antigua (tipo, precio máx., ubicación
   de antes) a los `BuyerSearchCriteria` con `created_at` anterior al corte. Así un perfil antiguo no pasa a
   incompleto ni bloquea etapas. El **formulario** sí exige los campos nuevos siempre que se guarde (si el
   agente edita un perfil antiguo, los rellena entonces).
5. **"Jaen" → "Jaén"**: sí. Fase D aparte: script de datos `scripts/normalize_city_names.py` (dry-run por
   defecto, `--apply` para ejecutar; unifica `properties.city` y `buyer_search_criteria.cities` con la grafía
   acentuada de una tabla corta de poblaciones de Jaén conocidas) y normalización en el formulario de
   propiedad al guardar (`geo.normalize_city`, misma tabla). No es migración: se ejecuta una vez en producción
   (`docker exec <backend> python scripts/normalize_city_names.py --apply`).

| Fase | Contenido | Commit |
|---|---|---|
| D | Unificar grafía de poblaciones | `fix(propiedades): unificar la grafía de las poblaciones (Jaén)` |
