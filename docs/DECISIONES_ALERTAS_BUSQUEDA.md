# Decisiones: alertas sin referencia (búsqueda general)

Fecha: 2026-10-16. Plan de implementación: `PLAN_ALERTA_SIN_REFERENCIA.md`.
Migración: `y8z9a0b1c2d3_alert_without_property`.

## 1. Decisión tomada

Un comprador que llama sin una referencia concreta genera **una sola alerta**
("sin referencia", `origin = 'search'`) sin propiedad. El agente que la atiende:

1. **Contacta** al comprador (seguimientos habituales).
2. Toma su **perfil de búsqueda** (zonas, ciudades, tipo, dormitorios, baños,
   precio, imprescindibles; sin m²). Guardarlo registra un seguimiento
   automático `CALIFICADO` con el resumen y deja el perfil en el comprador
   (`BuyerSearchCriteria`, uno por comprador).
3. Ve las **propiedades sugeridas** (todas las disponibles de la empresa
   activa, de cualquier agente) y **asocia a esa misma alerta** la que elige
   el comprador. Puede **cambiarla** después (presupuesto, gustos).

Reglas:

- La alerta la **conserva el agente que atiende** al comprador aunque la
  propiedad asociada sea de otro agente: `alert.agent_id` no cambia al asociar.
- Solo las alertas de origen `search` pueden asociar o cambiar de propiedad.
  Las de origen `property` (creadas con referencia) siguen significando
  "interés en este inmueble" y no cambian.
- Asociar o cambiar registra un seguimiento real `PROPIEDAD_ASOCIADA`
  ("Propiedad asociada: X" / "Cambio de propiedad: de A a B"): cuenta como
  gestión (desbloquea la cola, permite cerrar) pero no avanza la etapa.
- Si el comprador ya tiene otra alerta abierta sobre esa propiedad, se pide
  confirmación y se anota en el mensaje de la alerta.
- La superficie (m²) sale del perfil en toda la app. Las columnas
  `min_m2` / `max_m2` se conservan con sus datos, pero no se editan ni filtran.
- El flujo "Agregar alerta con filtro" (`/buyers/create-with-criteria`) se
  eliminó: un único punto de entrada, "Agregar alerta comprador", con el
  selector "Con referencia / Sin referencia".

## 2. Alternativa descartada por ahora: una alerta nueva por propiedad

En lugar de asociar la propiedad a la misma alerta, crear una **alerta nueva
por cada propiedad** que interese al comprador, enlazada a la búsqueda.

Qué ganaría:

- Varias propiedades a la vez para el mismo comprador (hoy, una por búsqueda).
- El agente captador de cada propiedad quedaría implicado (su alerta, su cola).
- Métricas por propiedad más limpias: cada alerta apunta a un único inmueble
  desde su creación y nunca "salta".

Qué cambiaría en código:

- Tabla de enlace búsqueda ↔ alertas, o columna `parent_alert_id` en
  `property_alerts`.
- En el paso "Propuesta", un botón "Registrar interés" que crea la alerta
  hija (con referencia) en vez de "Asociar a esta alerta".
- Notificación al captador de la propiedad (`alert_assigned` o un aviso nuevo).
- Reglas de cola y cierre: qué pasa con la búsqueda padre cuando se cierran
  las hijas, y si la búsqueda cuenta como contacto además de las hijas.

## 3. Implicaciones para analítica y contadores (decisión actual)

- `alert.agent_id` **puede no coincidir** con `property.agent_id` en una
  búsqueda con propiedad asociada de otro agente.
- **Métricas por agente** (se quedan con quien atiende, `alert.agent_id`) y
  cuentan también las búsquedas sin propiedad. La empresa es la columna
  propia `property_alerts.company_id`, no la de la propiedad:
  - `services/performance_report_service.py`: indicador **contactos**
    (`select_from(PropertyAlert)`, sin JOIN) y **cierres** (`OUTER JOIN` a la
    propiedad solo para el tipo de respaldo; una búsqueda sin propiedad y sin
    tipo cuenta como "otros"). Captaciones y bajadas siguen siendo de la
    propiedad.
  - `services/dashboard_service.py`: agenda y "sin respuesta" del agente,
    tendencia semanal de contactos, compradores pendientes y abandonados,
    última actividad del agente y cierres del feed: todos por
    `PropertyAlert.company_id`.
  - `services/buyer_reminder_service.py` (recordatorio 48 h) y
    `services/notification_service.py` (seguimiento vencido): agrupan por la
    empresa de la alerta; ya no cargan la propiedad.
  - Resultados Comerciales, pestaña Compradores
    (`routes/commercial_results.py`): usa `scope_alerts` (empresa de la
    alerta); las búsquedas sin propiedad aparecen como "Búsqueda general".
- Los **contadores de `/alerts`** (pendientes / en proceso / completadas) no
  cambian: una búsqueda es una alerta más.
- **Métricas por propiedad**: solo ven la alerta cuando ya tiene propiedad
  asociada (consultas por `property_id`, p. ej. duplicados comprador +
  propiedad). Hoy no hay ningún informe "por propiedad" que cuente alertas;
  si se crea, tendrá que decidir qué hacer con las búsquedas: la propiedad
  asociada **puede cambiar** ("saltar" de un inmueble a otro) y el historial
  está en los seguimientos `PROPIEDAD_ASOCIADA`.
- El texto libre del listado sigue buscando por título de propiedad con
  `OUTER JOIN` (una búsqueda sin propiedad se encuentra por comprador o
  teléfono).

## 4. Qué permite cambiar de idea después

- `property_alerts.origin` (`property` / `search`): distingue las alertas
  creadas sin referencia, aunque ya tengan propiedad.
- `property_alerts.property_linked_at`: cuándo se asoció (o cambió) la
  propiedad de la búsqueda.
- Seguimientos `PROPIEDAD_ASOCIADA`: historial completo de propiedades por
  las que pasó cada búsqueda (con fecha y usuario). Con esto se pueden
  reconstruir alertas hijas por propiedad si se adopta la alternativa del §2.
- `property_alerts.company_id`: la alerta ya no depende de la propiedad para
  saber su empresa.

## 5. 2026-10-19: perfil y propuesta en todas las alertas; perfil obligatorio al contactar

Plan: `PLAN_PERFIL_OBLIGATORIO.md`. Motivo: un comprador entra por una
propiedad concreta y después hay que ofrecerle otras que se ajusten a lo que
puede, y el perfil no se estaba tomando de forma sistemática.

Decisiones cerradas con el usuario:

1. **Perfil, Propuesta y "Cambiar propiedad" en todas las alertas**, también
   en las creadas con referencia. El agente que atiende conserva la alerta
   aunque cambie a una propiedad de otro agente (como en las búsquedas).
2. **El perfil es obligatorio y se toma al contactar.** El seguimiento
   **Contactado** lleva dentro los campos del perfil. Sin perfil completo no
   se puede registrar **Visita programada**, **Oferta** ni **Cerrado (éxito)**
   (`FollowUpActionType.PROFILE_REQUIRED_STAGES`), ni usar la Propuesta ni
   "Cambiar propiedad".
3. **Se registran sin perfil**: Sin respuesta y los cierres negativos (Sin
   interés, Sin solvencia económica, No apto para el propietario).
4. **Perfil mínimo completo** = tipo de inmueble + precio máximo + al menos
   una zona o una ciudad. Una sola definición:
   `buyer_matching.profile_is_complete` / `missing_profile_fields` (rutas,
   plantillas y tests). Dormitorios, baños, precio mínimo e imprescindibles
   son opcionales; la operación viene de la alerta.
5. **Perfil = Contactado**: la primera vez que el perfil del comprador queda
   completo (paso Perfil o seguimiento Contactado) se registra **un**
   seguimiento `CONTACTADO` con el resumen del perfil como nota (avanza la
   etapa). Las ediciones posteriores registran `PERFIL_GUARDADO` (no mueven la
   etapa). Contactado con perfil no crea además un `PERFIL_GUARDADO`.
6. **Aplica a las alertas existentes**: una alerta antigua sin perfil lo pide
   la próxima vez que el agente quiera avanzar de etapa.

Qué significa ahora `origin`: **solo un dato** de cómo entró el comprador
(`property` = con referencia, `search` = búsqueda general). Se usa en
etiquetas ("Búsqueda general" / "Con referencia"), en el aviso de búsqueda
duplicada al **crear** (`find_open_search_alerts`) y para analítica. Ya no
decide qué pasos ni acciones tiene una alerta. `property_linked_at` vale
también para las alertas con referencia: si no es NULL, la propiedad se
cambió desde la Propuesta (y el historial está en `PROPIEDAD_ASOCIADA`).

Implicaciones para analítica:

- Una alerta **con referencia** también puede "saltar" de propiedad; las
  métricas por propiedad (si se crean) deben leer `PROPIEDAD_ASOCIADA` para
  saber por qué inmuebles pasó.
- `CONTACTADO` puede aparecer sin un "Contactado" explícito del formulario:
  lo crea el primer guardado del perfil desde el paso Perfil. Los conteos de
  "contactados" siguen siendo correctos (antes ese guardado no movía la etapa).
- Alertas antiguas **sin comprador** (anteriores a la tabla de compradores):
  no tienen dónde guardar el perfil y quedan fuera del requisito (pueden
  seguir avanzando y cerrarse).

## 6. 2026-10-19: ubicación del perfil en cascada, provincia por CP y operación editable

Plan: `PLAN_PERFIL_UBICACION.md`. Motivo: que la ubicación del perfil se tome
como en InmoPC (País → Provincia → Población → Zona) y que la operación se
pueda corregir al hablar con el comprador.

Decisiones cerradas con el usuario:

1. **Provincia sin columna en `properties`**: se deduce del código postal
   (dos primeros dígitos, tabla 01 Álava … 52 Melilla en `app/core/geo.py`;
   `Property.provincia` es de solo lectura). Una propiedad sin CP válido (o de
   otro país) queda "Sin provincia": solo aparece al filtrar por país o por
   población/zona directamente.
2. **Operación editable en el perfil de la alerta**: al cambiarla cambia
   `alert.business_type`, queda en la nota del **mismo** seguimiento que
   guarda el perfil (`CONTACTADO` o `PERFIL_GUARDADO`: "Operación: Venta →
   Alquiler") y las sugerencias se recalculan (el perfil guarda la nueva). Solo
   con la alerta abierta. Si la alerta tiene propiedad de la otra operación, se
   **mantiene** y la Propuesta avisa ("La propiedad asociada es de Venta y el
   comprador busca Alquiler").
3. **Población y Zona múltiples con "Todas"**; las zonas que se ofrecen son
   las de las poblaciones marcadas.
4. **Mínimo de ubicación** = provincia elegida (aunque sea con "Todas" las
   poblaciones) **o** al menos una población **o** al menos una zona. El país
   solo no basta. Sigue siendo una sola definición
   (`buyer_matching.profile_is_complete` / `missing_profile_fields`; la etiqueta
   del mínimo pasa de "zona o ciudad" a "ubicación"). La **ficha del
   comprador** exige ahora los mismos mínimos (allí la operación se edita como
   siempre y no se registra ningún seguimiento).

Modelo: `buyer_search_criteria.country` y `province` (String, nullable;
migración `a0b1c2d3e4f5`). `cities` y `zones` siguen siendo listas: **vacía =
Todas**. "Todas las poblaciones" de una provincia incluye las que entren
después (filtro `cod_postal LIKE 'NN___'`). País vacío (o variante de España)
en una propiedad = "España", en la cascada y en el filtro. Los perfiles
anteriores (sin país ni provincia) siguen filtrando por sus poblaciones y
zonas como hasta ahora y se abren con España preseleccionada.

Cascada: `buyer_matching.geo_options` (una consulta `DISTINCT (pais,
cod_postal, city, zona)` de las propiedades no archivadas de la empresa
activa) → JSON en la página (`<script type="application/json"
id="geoData-{prefijo}">`, una copia por formulario) → `static/js/search-profile.js`
rellena los niveles. El servidor pinta el estado inicial
(`buyer_matching.geo_choices`). En el formulario de propiedad, junto al CP,
una ayuda de solo lectura "Provincia (según CP)".

Implicaciones para analítica: `alert.business_type` puede cambiar después de
crear la alerta; el historial del cambio está en la nota del seguimiento
("Operación: … → …"). Las métricas por operación leen el valor actual.

## 7. 2026-10-20: perfil obligatorio solo en Venta (opcional en Alquiler)

Plan: `PLAN_PERFIL_SOLO_VENTA.md`. Matiza las §5 y §6: el perfil de búsqueda
(con los mínimos de la §6) es **obligatorio solo cuando la operación de la
alerta es Venta**. En **Alquiler** es **opcional**: se puede registrar y, si
existe completo, sugiere propiedades, pero no bloquea nada.

Una sola fuente de verdad: `buyer_matching.profile_required(alert)` (Venta y
con comprador; Alquiler, vacío o cualquier otro valor → opcional; sin
comprador, nunca). La comparación con Venta vive solo en
`buyer_matching.profile_required_for_business_type`, que también usa la ficha
del comprador; el JS recibe la lista de operaciones obligatorias del servidor
(`profile_required_operations`). `profile_is_complete` /
`missing_profile_fields` no cambian (dicen si el perfil está completo, no si
hace falta).

| Punto | Venta (como antes) | Alquiler |
|---|---|---|
| Contactado | perfil obligatorio la 1.ª vez | campos opcionales; si se rellenan, con los mínimos y se registra el perfil (1 solo `CONTACTADO`) |
| Visita programada / Oferta / Cerrado | bloqueados sin perfil | no se bloquean |
| Paso Perfil | obligatorio | opcional; mínimos solo si se envía algún dato |
| Propuesta | sin perfil: ni sugerencias ni buscador | sin perfil: buscador manual y asociar; con perfil, sugerencias |
| Asociar / cambiar propiedad | exige perfil | no lo exige |
| Aviso | banner "Perfil pendiente" | línea discreta "Perfil opcional en alquiler" con enlace al paso Perfil |
| Chip "Sin perfil" (`/alerts`, admin) | sí | no |
| Ficha del comprador | mínimos obligatorios | sin mínimos |

Cambio de operación desde el perfil de la alerta (§6, decisión 2): la
obligatoriedad se evalúa con la operación **pedida** en la misma petición.
Venta → Alquiler deja de bloquear (aunque no se envíe ningún dato: se registra
el cambio de operación en la nota); Alquiler → Venta con el perfil incompleto
se rechaza con el error de mínimos y la alerta no cambia.

Detalles de implementación: en Alquiler, el paso Perfil sin ningún dato ni
cambio de operación no guarda nada (aviso "No se ha guardado nada: el perfil …
está vacío y es opcional en alquiler"); si solo cambia la operación se
registra `PERFIL_GUARDADO` con la línea "Operación: Venta → Alquiler" (el
perfil no se toca, salvo su operación si ya existía). Tras la primera gestión,
una alerta de Alquiler sin perfil abre por defecto en Propuesta (no en
Perfil).

Implicaciones para analítica: en Alquiler puede haber `CONTACTADO`, visitas y
cierres sin perfil guardado; los informes que cuenten "perfiles registrados"
no deben tomarlos como alertas incompletas.

## 8. 2026-10-20: sugerencias de las dos empresas (MOYZA y MOES PREMIUM)

Plan: `PLAN_SUGERENCIAS_MULTIEMPRESA.md` (resumen operativo en
`MULTIEMPRESA_MOYZA_MOES.md` §16). Las propiedades sugeridas por el perfil
del comprador (paso Propuesta y ficha del comprador) salen de **las dos
empresas**, con el distintivo de empresa en cada tarjeta y en cada resultado
del buscador manual de la Propuesta. Orden por precio ascendente, sin agrupar;
la cabecera desglosa el total por empresa y ofrece "Solo {empresa activa}"
(`?company=active`) cuando hay de más de una. La cascada de ubicación y los
tipos del perfil también se alimentan de las dos.

Asociar a la alerta una propiedad de la otra empresa está permitido:
`alert.company_id` no cambia, `alert.property_id` apunta a la de la otra
empresa y la nota del seguimiento la nombra con su empresa.

Implicaciones para analítica: los indicadores de alertas (contactos, cierres)
cuentan por `property_alerts.company_id`, no por la empresa de la propiedad,
así que una alerta de MOYZA con una propiedad de MOES cuenta en MOYZA. Un
informe que agrupe por la empresa de la **propiedad** de las alertas verá
alertas de la otra empresa: para "dónde se captó al comprador" usar siempre
`property_alerts.company_id`. Las alertas con propiedad ya no cumplen siempre
`alert.company_id == property.company_id`.
