# Plan: sugerencias de propiedades de ambas empresas (MOYZA y MOES), distinguibles

Fecha: 2026-10-20. Rama: `63-agregar-moes`.

## Decisión cerrada con el usuario

Las **propiedades sugeridas** por el perfil del comprador (paso Propuesta de
la alerta y pestaña "compatibles" de la ficha del comprador) salen de **las
dos empresas**, no solo de la activa, y cada tarjeta deja claro **de qué
empresa es**. El resto de la app sigue separado por empresa
(`MULTIEMPRESA_MOYZA_MOES.md`): esta es una excepción consciente, limitada a
las sugerencias y a lo que hace falta para asociar una de ellas.

## Decisiones de diseño tomadas en este plan (cámbialas solo si rompen algo, y anótalo)

- **Asociar** a la alerta una propiedad de la otra empresa: permitido.
  `alert.company_id` **no cambia** (la alerta sigue siendo de la empresa donde
  se captó al comprador); `alert.property_id` apunta a la propiedad de la otra
  empresa. El seguimiento `PROPIEDAD_ASOCIADA` incluye la empresa en la nota
  ("Propiedad asociada: Piso en Martos (MOES PREMIUM)").
- **Buscador manual** de Propuesta ("¿No está en la lista?" / "Buscar una
  propiedad"): también busca en las dos empresas, con el distintivo en cada
  resultado. El buscador del **modal de creación** de alertas con referencia
  **no cambia** (sigue siendo de la empresa activa y, para el agente, solo sus
  propiedades).
- **Cascada de ubicación** (`geo_options`) y **tipos** del perfil: se
  alimentan de las propiedades de las dos empresas, para que se pueda elegir
  una población donde solo tenga inmuebles la otra.
- **Distintivo**: en cada tarjeta de propiedad sugerida y en cada resultado
  del buscador, un badge con el nombre de la empresa y un punto con su
  `primary_color` (señal de identidad, permitida por el sistema de diseño;
  no colorear botones). En la cabecera de Propuesta, el total desglosado:
  "12 sugerencias · 8 MOYZA · 4 MOES PREMIUM".
- **Orden**: por precio ascendente, como hoy, sin agrupar por empresa (el
  badge ya distingue). Opcional y barato: un filtro de un clic "Solo
  {empresa activa}" encima de las tarjetas (enlace con `?company=active`).
- **"Ver" ficha**: solo si la propiedad es de la empresa activa **y** (admin o
  propiedad del propio agente), como hoy. Para propiedades de la otra empresa,
  texto "Cambia de empresa para ver la ficha".
- **Tarjeta de la propiedad asociada** en el detalle de la alerta y
  **columna Propiedad** en `/alerts` y en la ficha del comprador: muestran el
  badge de empresa cuando la propiedad no es de la empresa activa.
- **Duplicados** al asociar (`find_duplicate_alerts` comprador+propiedad):
  siguen siendo por empresa de la alerta; no cambia.
- Nada más cruza empresas: visitas, informes, métricas y listados siguen
  igual. La ficha de propiedad sigue dando "no encontrada" fuera de su
  empresa.

## Cambios por archivo

- `app/services/buyer_matching.py`: `matching_properties_query` y
  `matching_properties` sin `scope_properties` (parámetro `company_id`
  → pasa a opcional para "solo empresa activa"); `geo_options` sin scope;
  cargar `Property.company` con `selectinload` para pintar el badge sin N+1;
  `matching_summary_by_company(...)` para el desglose.
- `app/web/routes/alerts.py`: `_search_context` (sugerencias, desglose,
  filtro opcional `company=active`); `search_properties` en la rama con
  `alert_id` (sin scope, con `company` en el JSON); `link_property`
  (buscar la propiedad **sin** `get_property_in_company`, exigir no archivada
  y disponible; nota con la empresa); `_property_filter_values`.
- `app/web/routes/alerts.py::buyer_detail` y `_build_matching_properties`
  (o lo que use la ficha): mismas sugerencias cruzadas.
- `components/property_card.html`: parámetro `active_company_id`; badge y
  regla de "Ver".
- `alerts/_search_steps.html`, `alerts/detail.html`, `alerts/list.html`,
  `buyers/detail.html`: badge donde se muestre la propiedad asociada.
- JS del buscador de Propuesta: pintar la empresa en cada resultado.
- Documentación: `MULTIEMPRESA_MOYZA_MOES.md` (sección "Excepciones: qué
  cruza empresas"), `docs/DECISIONES_ALERTAS_BUSQUEDA.md` §8.

## Tests (patrón `tests/test_profile_location.py` / `test_alert_search.py`)

- Sugerencias incluyen propiedades de la otra empresa que cumplen el perfil
  y excluyen las archivadas / no disponibles de cualquiera.
- `geo_options` incluye poblaciones de la otra empresa.
- Asociar una propiedad de la otra empresa: OK, `alert.company_id` intacto,
  nota con la empresa; archivada → rechazada.
- Buscador con `alert_id` devuelve de las dos empresas con el campo
  `company`; el buscador del modal de creación sigue limitado.
- Render: tarjeta con badge de la otra empresa y sin "Ver"; desglose en la
  cabecera; filtro "Solo {empresa}" si se implementa.
- Los tests de aislamiento multiempresa existentes siguen pasando
  (`tests/test_company_context.py`, `tests/test_company_isolation.py` se
  salta sin app).
- Suite completa: el conjunto de fallos no cambia (previo:
  `test_scheduler.py::test_check_automatic_reports_con_propiedad_activa`;
  errores de integración por falta de PostgreSQL).

## Verificación adicional

`python -c "import app.main"`; plantillas compilan; `node --check`;
`build_css.sh` + clases nuevas; `ui_lint` sin avisos nuevos. Sin migración.
Leer `.claude/skills/moyza-ui-ux-pro/SKILL.md` y `references/tokens.md`
(marca por empresa) antes de tocar plantillas.

## Entrega

Sin commits. Informe con archivos tocados, decisiones, resultados con números,
pasos de prueba manual (alerta de MOYZA con sugerencias de MOES; asociar una;
ver el badge en detalle y listado), riesgos. Marcar "Estado".

## Estado

- [x] Sugerencias, cascada y buscador de Propuesta sin límite de empresa
- [x] Asociar propiedad de la otra empresa (nota con empresa)
- [x] Badges de empresa en tarjetas, resultados, detalle y listados
- [x] Tests, documentación, lint, CSS

Notas de la implementación (2026-10-20):

- Filtro "Solo {empresa activa}" implementado (`?company=active`); el enlace
  sale solo si hay sugerencias de más de una empresa.
- La empresa entre paréntesis en notas y avisos ("Piso MOES (MOES PREMIUM)")
  solo cuando la propiedad no es de la empresa de la alerta; las de la misma
  empresa se nombran como siempre.
- "Cambia de empresa para ver la ficha" solo cuando el rol podría ver la
  ficha (admin o propiedad del propio agente); para la propiedad de otro
  agente no sale nada, como hoy.
- Ficha del comprador: una compatible de la otra empresa no ofrece "Crear
  alerta" (el alta con referencia sigue limitada); en su lugar, "De otra
  empresa: para proponerla, asóciala desde la alerta del comprador".
- `company_id` de `matching_properties(_query)` y `geo_options` queda opcional
  (None = las dos empresas); las rutas no lo pasan salvo el filtro.
- El total del aviso al guardar el perfil ("N propiedades sugeridas") también
  cuenta las dos empresas.
- Tests: `tests/test_sugerencias_multiempresa.py` (14) y aserciones
  actualizadas en `test_alert_search.py`, `test_profile_required.py` y
  `test_profile_solo_venta.py` que fijaban el aislamiento anterior.
