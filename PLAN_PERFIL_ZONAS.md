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
| A | Zonas por población, zona sin "Todas" por defecto, población y zona obligatorias — **IMPLEMENTADO** | `feat(perfil): zonas por población, obligatorias sin marcar todas por defecto` |
| B | Dormitorios máx. obligatorio — **IMPLEMENTADO** | `feat(perfil): dormitorios máximos obligatorios` |
| C | Filtro de ascensor (migración) — **IMPLEMENTADO** | `feat(perfil): filtro de ascensor en el perfil del comprador` |

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

## 5. Notas de implementación (2026-10-29)

Las decisiones de §4 no se han cambiado. Donde el plan dejaba margen:

### Fase A

- **Dos reglas de mínimos** en `buyer_matching.missing_profile_fields` (documentado en el docstring del
  módulo): `uses_new_minimums(criteria)` es True sin perfil, con un perfil temporal sin `created_at` (las
  rutas validan lo que llega del formulario sobre un `BuyerSearchCriteria()` nuevo, así el formulario exige
  siempre los mínimos nuevos, también al editar un perfil antiguo), sin corte o con `created_at` en el corte
  o después. El corte (`settings.PROFILE_MINIMUMS_SINCE`, por defecto 2026-10-29) es a las 00:00 de Madrid
  en UTC naive (`minimums_since`, como `buyer_attention_service.attention_since`); vacío o inválido en el
  `.env` = sin corte (todos con la regla nueva).
- **Etiquetas**: "ubicación" se desglosa en **"población"** y **"zona"** en la regla nueva
  (`PROFILE_MINIMUM_LABELS` + `ZONE_LABEL`); la antigua conserva "ubicación"
  (`LEGACY_PROFILE_MINIMUM_LABELS`). Orden de los mensajes: tipo, precio máximo, población, zona.
- **Zona obligatoria solo al guardar**: con la lista vacía guardada no se distingue "Todas" de "sin
  elegir", así que la zona se comprueba solo al validar el formulario, con el árbol de `geo_options` y el
  campo nuevo `zones_all` (la casilla "Todas" de Zona ahora tiene `name="zones_all" value="1"`). Un perfil
  ya guardado con poblaciones y sin zonas se lee como "Todas" (completo). Basta una zona de cualquiera de
  las poblaciones marcadas (no se exige una por población). Las zonas de cada población salen del país y
  la provincia del perfil (`buyer_matching.city_zones`, mismo criterio que `cityZones()` del JS).
- **"Todas" en Zona al editar** (`geo_choices["zones_all"]`): marcada solo si el perfil está guardado,
  tiene poblaciones, la lista de zonas está vacía y las poblaciones tienen zonas. No depende de la fecha de
  corte: con poblaciones marcadas, la lista vacía solo puede venir de "Todas" (regla nueva) o del "Todas"
  por defecto de antes (regla antigua), y en los dos casos significa lo mismo. Un perfil antiguo con la
  lista de poblaciones vacía abre sin ninguna marcada y sin bloque de zonas (§4-1).
- **Formulario**: Población sin "Todas", con asterisco (`data-profile-mark`) y aviso propio "Marca al
  menos una población"; Zona es un `<fieldset data-geo-zones>` oculto **y deshabilitado** sin poblaciones
  marcadas (no envía nada), con un grupo por población que tenga zonas (`role="group"`, título pequeño
  solo si hay más de un grupo), "Todas" solo visible si hay zonas, asterisco (`data-zone-mark`) solo si
  hay zonas que elegir, y aviso "Elige al menos una zona o marca Todas". "Todas" ya no se marca sola al
  desmarcar la última zona. Una zona con el mismo nombre en dos poblaciones sale en los dos grupos: las
  dos casillas van a la par y `apply_profile` guarda las listas sin repetir. Las zonas guardadas que ya
  no salen en las propiedades van en un grupo "Otras zonas guardadas" (para no perderlas al guardar).
- **Textos**: "Datos mínimos: tipo, precio máximo, población y zona (si la población tiene zonas)" en el
  paso Perfil, el modal de seguimiento y la ficha del comprador.
- **Tests**: `_complete_profile` y `CONTACT_PROFILE` (tests/test_alert_search.py) llevan ahora población
  (Jaen) además de la zona, para cumplir las dos reglas sea cual sea el día. Los tests de mínimos fijan el
  corte con el fixture `cutoff` (tests/test_profile_required.py) y `created_at` explícito.

### Fase B

- **Dormitorios máx.** entra en la regla nueva con la etiqueta "dormitorios máximos" (orden de los
  mensajes: tipo, precio máximo, dormitorios máximos, población, zona). **0 vale** (estudio); solo falta si
  está vacío. Los perfiles anteriores al corte no lo exigen (§4-4).
- Formulario: `required` + asterisco + `data-profile-min` (el JS lo pone y quita con la operación, como tipo
  y precio máximo). Textos "Datos mínimos: tipo, precio máximo, dormitorios máximos, población y zona (si la
  población tiene zonas)" y el estado vacío de la Propuesta ("tipo, precio, dormitorios y ubicación").
- **Cruce sin cambios**: `_matching_filters` ya filtraba `num_dormitorios <= max_bedrooms`, así que una
  propiedad **sin dormitorios registrados** (NULL: locales, garajes, terrenos o fichas incompletas) no sale
  en las sugerencias de un perfil nuevo. No se ha tocado porque el plan no lo pide; si se quiere, el cambio
  es tratar NULL como compatible en ese filtro.
- `tests/test_buyer_business_type.py::test_edicion_de_criterios_exige_operacion` (pega a la app levantada)
  se actualiza aquí a los mínimos nuevos: con la fase A ya fallaba tras reiniciar el contenedor (antes de
  reiniciar, la app seguía con el código anterior).

### Fase C

- Migración `e4f5a6b7c8d9_criteria_elevator` (aplicada en local; probado downgrade y upgrade). Columna
  `buyer_search_criteria.elevator` Boolean nullable; los perfiles existentes quedan en NULL (indiferente).
- Opciones del select en `app/core/constants.py` (`ElevatorPreference`: "" Indiferente / "yes" Con ascensor /
  "no" Sin ascensor), global de Jinja `ElevatorPreference` (no se puede importar `buyer_matching` desde
  `template_env` por el ciclo de imports). `buyer_matching.parse_elevator` / `elevator_value` traducen a
  NULL / True / False; cualquier otro valor = indiferente.
- El select va junto a "Baños mín." (misma celda, dos columnas), opcional y sin asterisco. "Con ascensor" o
  "Sin ascensor" cuentan como dato del perfil (`PROFILE_TEXT_FIELDS` y `VALUE_NAMES` del JS): en un perfil
  opcional, o al editar uno completo desde «Contactado», enviar solo el ascensor exige los mínimos.
- Cruce: con ascensor `num_ascensores >= 1`; sin ascensor `num_ascensores` 0 o NULL (una propiedad sin el
  dato cuenta como "sin ascensor"). Resumen: "con ascensor" / "sin ascensor" detrás de los baños.
- Nota de despliegue en `MULTIEMPRESA_MOYZA_MOES.md` §21 (migración, `PROFILE_MINIMUMS_SINCE` y script de
  la fase D).
