# Plan: visitas a propiedades de la otra empresa

Fecha: 2026-11-12. Rama `63-agregar-moes`. Petición: que un agente pueda registrar visitas a
cualquier propiedad, sea de MOYZA o de MOES PREMIUM, independientemente de su empresa.

## 1. Cómo está hoy

- **No se puede.** El selector de propiedad de la visita (`/visits/select-property`) y el alta
  (`/visits/new/{id}`, `/visits/create/{id}`) usan `scope_properties` / `get_property_in_company`
  con la **empresa activa**: una propiedad de la otra empresa es "no encontrada".
- La pestaña "Propiedades de {otra empresa}" en Propiedades es solo lectura: sin enlace al
  detalle y sin botón "Registrar visita" (MULTIEMPRESA_MOYZA_MOES.md §2 y §16: visitas no cruzan).
- Un agente que está **en las dos empresas** sí puede: cambia de empresa con el selector y
  registra la visita como visita de esa empresa. Un agente que solo está en una (en el entorno
  local, 3 de los 4 agentes activos) no tiene forma.
- La visita no tiene empresa propia: hereda la de la propiedad (`scope_visits`). De eso dependen
  el listado `/visits`, la vista previa, la firma, la edición, el borrado, las notas, la métrica
  "Hojas de visita" (`_visits_query`: visitas a propiedades de la empresa activa) y el acceso por
  `get_visit_in_company`.
- La ficha PDF y la vista previa usan la marca de la **empresa de la propiedad**
  (`branding_for(property.company)`): logo, razón social, "en calidad de representante de la
  agencia inmobiliaria {marca}", RGPD y responsable del tratamiento.
- Agentes de la visita (`visit_agents.py`): el principal debe ser de la empresa activa (para un
  usuario agente es él mismo); el acompañante ya puede ser de cualquier empresa.

## 2. Diseño propuesto

- **Empresa de la visita**: nueva columna `company_id` en `property_visits` = empresa activa
  desde la que se registra (la del agente). Backfill: la empresa de la propiedad. Así la visita
  "es" de la agencia del agente aunque la propiedad sea de la otra, y `scope_visits` pasa a
  filtrar por esa columna.
- **Selector de propiedad**: a las secciones "Mis propiedades" y "Otras propiedades de la
  empresa" se añade "Propiedades de {otra empresa}" (inventario activo y disponible, mismo
  criterio que la pestaña de Propiedades), con el distintivo de empresa (`ui.company_badge`).
  La búsqueda del selector incluye la nueva sección.
- **Alta y flujo legal**: `new_visit` / `create_visit` aceptan una propiedad disponible de
  cualquier empresa activa. Vista previa, firma, completar, descarga, edición, borrado y notas
  cargan la visita por su `company_id` (la activa), no por la empresa de la propiedad.
- **Agente principal**: para el admin el select sigue siendo el de la empresa activa (es quien
  registra en su empresa); un usuario agente sigue siendo él mismo. No cambia.
- **Ficha PDF y vista previa**: marca de la **empresa de la visita** (la agencia del agente que
  acompaña y firma), y en los datos del inmueble se indica "Inmueble comercializado por {otra
  empresa}" cuando la propiedad no es de esa marca. Ver pregunta 1.
- **Quién ve la visita**:
  - Empresa del agente: en `/visits`, Inicio, métrica "Hojas de visita" y lupa (con el
    distintivo de la empresa de la propiedad en la lupa y en el listado).
  - Empresa de la propiedad: en el historial de visitas de la ficha de la propiedad (es por
    `property_id`, sale solo) y en `/visits` del admin de esa empresa como "visita de
    {otra empresa}", en solo lectura. El captador sigue recibiendo el aviso in-app
    (`notify_visit_created`). Ver pregunta 2.
- **Métrica "Hojas de visita"**: cuenta para el agente en su empresa (la de la visita), sea de
  quien sea la propiedad. El texto de la lupa cambia a "visitas realizadas por {nombre} como
  principal o acompañante, a propiedades de cualquier empresa". Los snapshots congelados no
  cambian (misma cifra por agente que hoy, porque hoy no hay visitas cruzadas).
- **Direcciones**: la propiedad de la otra empresa muestra la calle en el selector y en la ficha
  de visita solo si el usuario pertenece a esa empresa o es admin, igual que en la pestaña de
  Propiedades (PLAN_CIERRES_MANUALES_Y_DIRECCIONES.md §2.2). Ver pregunta 3.

## 3. Preguntas (con recomendación)

1. **Marca de la ficha de visita** cuando un agente de MOYZA visita una propiedad de MOES.
   Recomendado: marca de la agencia del agente (MOYZA), que es quien acompaña, firma y
   responde del tratamiento de datos, con una línea "Inmueble comercializado por MOES PREMIUM".
   Alternativa: marca de la empresa de la propiedad, como hoy (el agente firmaría como
   representante de MOES sin serlo).
2. **Visibilidad para la empresa de la propiedad.** Recomendado: el admin de MOES ve la visita
   en el historial de la propiedad y en `/visits` marcada como "de MOYZA", solo lectura. El
   captador recibe el aviso como hoy.
3. **Calle de la propiedad ajena** en el selector y en la ficha. Recomendado: misma regla que
   en Propiedades (solo si pertenece a esa empresa o es admin). Para la ficha PDF la dirección
   completa es necesaria para el documento legal: se imprime siempre. Si prefieres, se puede
   ocultar también en el selector y en el formulario y mostrarla solo en el PDF.
4. **Propiedades de la otra empresa en el selector**: ¿todo el inventario activo y disponible
   (recomendado, como la pestaña de Propiedades) o solo las captadas por agentes que estén en
   las dos empresas?

## 4. Fases

- **Fase A — modelo**: `company_id` en `property_visits` con backfill, `scope_visits` por la
  columna, `get_visit_in_company` y tests.
- **Fase B — alta cruzada**: selector con la sección de la otra empresa, `new_visit` /
  `create_visit` con propiedad de cualquier empresa, aviso en el formulario, agentes.
- **Fase C — documento y visibilidad**: marca de la ficha, línea "comercializado por",
  listado `/visits` y lupa con distintivo, solo lectura para la otra empresa, Inicio.
- **Fase D — métrica, docs y tests**: explicación de la lupa, MULTIEMPRESA_MOYZA_MOES.md §16,
  tests de ruta y móvil.

## 5. Decisiones (respuestas del usuario, 2026-11-12)

1. Marca de la ficha: la agencia del agente, con "Inmueble comercializado por {otra empresa}".
2. Visibilidad para la empresa de la propiedad: lo recomendado (ficha de la propiedad y
   `/visits` del admin, solo lectura, marcada como "de {empresa}").
3. Calle: lo recomendado (regla de Propiedades en selector y formulario; siempre en el PDF).
4. Selector: todo el inventario activo y disponible **de todas las empresas**, no solo la activa
   y "la otra": una sección por empresa.

## 6. Estado

**Hecho** (2026-11-12), como fase E de PLAN_VISTA_UNIFICADA_AGENTES.md, sobre la vista
unificada (el selector y el listado ya son de "todas mis empresas"). Un commit por fase:

- **Fase A — modelo** (`b4cdaf2`): migración `g3v4i5s6c7o8` (`property_visits.company_id`,
  backfill = empresa de la propiedad, NOT NULL, índice; el downgrade se detiene si hay visitas
  cruzadas), relación `company`, `is_cross_company`, relleno `before_insert`, `scope_visits` /
  `get_visit_in_company` por la columna, `scope_visible_visits` / `get_visible_visit`, select
  "Empresa de la visita" y validación del principal contra la empresa de la visita.
- **Fase B — alta cruzada** (`7bea969`): selector con una sección por empresa,
  `get_visitable_property`, aviso en el formulario, calle con la regla de Propiedades y
  "Registrar visita" en las tablas de solo lectura de Propiedades.
- **Fase C — documento y visibilidad** (`d7bb384`): marca de la visita en PDF y vista previa
  con "Inmueble comercializado por …", solo lectura para la empresa de la propiedad (ficha de
  la propiedad, `/visits`, descarga), avisos e Inicio con distintivo.
- **Fase D — métrica, docs y tests** (el commit siguiente a `d7bb384`, "feat(visitas): hojas de
  visita de cualquier propiedad, docs y tests"): Inicio/equipo/tendencia por
  `PropertyVisit.company_id`, regla y distintivo de la lupa, logs de envío de la ficha por la
  empresa de la visita, MULTIEMPRESA_MOYZA_MOES.md §1, §2, §6, §16 y §22, tests de ruta.

### 6.1 Decisiones de implementación (donde el plan no era explícito)

- **Empresa preseleccionada** en el select "Empresa de la visita" (agente en dos empresas):
  la principal, como el resto de altas sin empresa derivable, aunque la propiedad sea de su
  otra empresa (entonces sale el aviso y la visita sería cruzada si no la cambia). El select
  solo aparece en la vista unificada con más de una empresa; el admin y la vista por empresa
  registran en la activa sin preguntar.
- **Validación del principal**: mensaje "El agente de la visita no pertenece a {empresa de la
  visita}" (antes "a la empresa activa").
- **Inventario del selector**: de las empresas del usuario, como antes (no archivada y
  disponible); de las demás, activa y disponible (criterio de la pestaña "Propiedades de
  {otra}"). Títulos: "Mis propiedades", "Otras propiedades de {empresa}" (suyas) y
  "Propiedades de {empresa}" (las demás, con el texto "La visita se registra en {empresa}");
  el admin ve "Propiedades de {activa}" y "Propiedades de {otra}". `new_visit` / `create_visit`
  aplican el mismo criterio (una propiedad archivada de su empresa ya no admite visitas).
- **Calle en el formulario**: el formulario no mostraba la dirección; ahora muestra bajo el
  título calle · población (o población · zona si no se puede ver la calle). "Volver" y los
  errores llevan al selector si la ficha de la propiedad no es accesible para el usuario.
- **Botón en Propiedades**: "Registrar visita" como icono junto al título (al lado de "Abrir en
  la web") en la tabla de solo lectura, compartida por "Resto de …" y "Propiedades de {otra}":
  no añade columna (la tabla ya tiene `min-w-[800px]` y scroll) y las filas ya son solo activas
  y disponibles.
- **Solo lectura**: se decide por fila con `visit.company_id in company_ids`. Sin editar, borrar,
  generar ni enviar la ficha; sí descargarla (`get_visible_visit`) y ver las observaciones
  internas. También el agente ve en `/visits`, en solo lectura, las visitas que otra empresa
  hizo a sus propiedades (mismo filtro de siempre: participó o es el captador).
- **Distintivos en `/visits`**: "Visita de {empresa}" en las de solo lectura; el de la empresa
  de la propiedad cuando no coincide con la de la visita y la propiedad no es de sus empresas
  (o se ven varias). El título de la propiedad solo enlaza a su ficha si es de sus empresas.
- **Avisos in-app**: el del captador en la empresa de la propiedad (como hoy, con su ficha); el
  del acompañante, "ficha firmada" y "envío fallido", en la empresa de la visita, con enlace a
  la ficha de la propiedad si es de esa empresa y a `/visits` si no.
- **Inicio del admin**: la actividad reciente incluye las visitas (y fichas firmadas) de su
  empresa y las que otra empresa registró a sus propiedades, con distintivo ("Propiedad de X"
  o "Visita registrada en X") y enlace a `/visits` si la ficha no se abre. Contadores (visitas
  del equipo, última actividad, envíos fallidos de WhatsApp) por la empresa de la visita.
- **Logs de envío de la ficha** (`/report-logs`): por la empresa de la visita.
- **Salidas del flujo legal** (commit posterior a la fase D, "fix(visitas): volver a Visitas
  …"): tras finalizar, en "Volver a la propiedad" de la página final y en las redirecciones
  de "ya procesada" / "ya finalizada" / archivo inexistente, si la ficha de la propiedad no es
  accesible (visita cruzada) se vuelve a `/visits`.
- **Lupa**: la fila lleva `property_company` si la propiedad es de otra empresa (distintivo, sin
  enlace). El CSV no cambia.
- Tests existentes cambiados: `test_visit_agent_signatures.py` (la API resuelve `company_ids`
  con `resolve_company_ids_for_api`) y `test_company_isolation.py` (el alta de visita a una
  propiedad de la otra empresa ya no redirige; la no disponible sí).
