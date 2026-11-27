# Plan: compradores compatibles con una propiedad nueva (aviso al agente y mensaje al comprador)

Fecha: 2026-11-24. Rama: `63-agregar-moes`. Ejecuta: Opus 5.5 (high), **después** de
`PLAN_REVISION_PROPIEDADES_NUEVAS.md` (se dispara con su OK).
Relacionado: `PLAN_ENVIO_PROPIEDAD_COMPRADOR.md` (mensaje y registro `PROPIEDAD_ENVIADA`),
`PLAN_SUGERENCIAS_MULTIEMPRESA.md` (las sugerencias cruzan empresas y agentes),
`PLAN_RUIDO_CAMPANA.md` (un aviso por agente, no por comprador).

## 1. Objetivo

Cuando el captador (o el admin) marca una propiedad nueva como **correcta**, la app busca
**todos** los compradores cuyo perfil de búsqueda encaja con ella, sean del agente que sea y de
la empresa que sea, avisa a cada agente de cuáles de sus compradores encajan y hace llegar al
comprador el enlace del inmueble. Objetivo: que el comprador que lleva tiempo esperando «algo
así» lo sepa el mismo día que entra.

## 2. Cómo está hoy (comprobado 2026-11-24)

- El cruce perfil → propiedades existe en una sola dirección:
  `buyer_matching._matching_filters` (SQL sobre `Property`: activa, con captador, país /
  provincia por CP / poblaciones / zonas, tipos, operación, precio, dormitorios, baños,
  ascensor, garaje; de las DOS empresas). No hay «propiedad → perfiles».
- Perfil completo: `buyer_matching.profile_is_complete` (única definición).
- Envío al comprador: `routes/alerts.py::_send_property` abre el WhatsApp **del agente** con
  el texto de `property_link.share_message` y registra `PROPIEDAD_ENVIADA` (informativo, no
  cuenta como gestión). Decisión del 2026-11-12: nada de Evolution API para esto.
- Envío automático sí existe para la **ficha de visita**: `services/whatsapp.py` (Evolution,
  `sendMedia` + `sendPresence`, `human_delay`), con `visit_whatsapp_logs` y flag
  `VISIT_SHEET_WHATSAPP_ENABLED` (pausado). No hay endpoint de **texto** (`sendText`) en el
  servicio.
- La propiedad lleva el enlace público en `properties.public_url` (lo trae la ETL; vacío = sin
  enlace y sin botón de enviar).
- Alertas abiertas: `status` `PENDING` / `IN_PROGRESS`; `buyer_id` + `buyer.search_criteria`
  (uno por comprador, `BuyerSearchCriteria`).

## 3. Decisiones

Cerradas por el usuario (2026-11-24):

- D1. Se avisa a los agentes de **todos** los compradores compatibles, suyos o no, de cualquier
  empresa.
- D2. Dos cosas: notificación al agente + mensaje al comprador con el enlace del inmueble.
- D3. Se dispara al marcar la propiedad como correcta (plan 1), no al entrar la propiedad.
- D4. «Reserva de compradores» **no** se implementa ahora; este plan deja el gancho (§6).

Confirmadas por el usuario el 2026-11-24 (ver §9):

- P1. **Un aviso por agente y propiedad** («3 de tus compradores encajan con …»), no uno por
  comprador. La lista completa está en una página nueva.
- P2. Candidatos: alertas **abiertas** (`PENDING` + `IN_PROGRESS`) con comprador y **perfil
  completo**, de todos los agentes activos y las dos empresas. La propiedad tiene que seguir
  activa y con captador (mismas condiciones que las sugerencias).
- P3. Mensaje al comprador: **un clic del agente**. En la página de compatibles cada comprador
  lleva el botón «Enviar por WhatsApp» de `PLAN_ENVIO_PROPIEDAD_COMPRADOR.md` (abre el
  WhatsApp del agente con el texto prellenado y registra `PROPIEDAD_ENVIADA`). **Descartado**
  el envío automático desde el número de la empresa (Evolution API): el comprador respondería
  a ese número y no al agente. No se añade `send_text`, ni flag, ni job de envíos.
- P4. El mensaje es el de `share_message` (sin cambios), con el agente del comprador y la
  empresa de la propiedad.
- P5. Nunca se añade la propiedad sola a la lista de interés de la alerta ni se crea
  seguimiento de gestión: asociar es decisión del agente (como hasta ahora).
- P6. La ETL trae el enlace web con la propiedad, así que al dar el OK ya hay enlace. Si por lo
  que sea falta, la fila de la página lo dice («Sin enlace web») y no hay botón, como en la
  tarjeta de sugerencias.

## 4. Diseño

### 4.1 Cruce propiedad → perfiles (`app/services/buyer_matching.py`)

- `criteria_matches_property(criteria, prop) -> bool`: réplica **en Python** de
  `_matching_filters`, condición por condición, con la misma normalización (país con
  `geo.normalize_country` / alias de España, provincia por prefijo del CP recortado, `city` y
  `zona` por igualdad exacta, tipos con `profile_types`, ascensor/garaje con NULL = sin). Es la
  ÚNICA segunda implementación del cruce y se documenta como tal: si cambia `_matching_filters`
  hay que cambiar esta y el test cruzado lo detecta.
- Test cruzado: para un conjunto de perfiles y propiedades en la BD de pruebas, `prop in
  matching_properties(criteria)` ⇔ `criteria_matches_property(criteria, prop)`.

### 4.2 Modelo y migración

Tabla `property_buyer_matches` (`app/models/property_buyer_match.py`):

| Columna | Notas |
|---|---|
| `id` | PK |
| `property_id` | FK `properties.id` ON DELETE CASCADE |
| `alert_id` | FK `property_alerts.id` ON DELETE CASCADE |
| `agent_id` | FK `agents.id` SET NULL: agente de la alerta al cruzar |
| `company_id` | FK `companies.id`: empresa de la alerta (donde el agente ve el aviso) |
| `created_at` | cuándo se cruzó |
| `notified_at` | aviso al agente (nulo si el agente no tiene usuario) |

Unique `(property_id, alert_id)`; índices por `property_id` y `agent_id`. El estado del envío
no se guarda aquí: «Enviada el …» sale de los seguimientos `PROPIEDAD_ENVIADA` con
`property_id` (`routes/alerts.py::sent_dates`), como en las tarjetas de sugerencias.
Migración propia (`down_revision` = la del plan 1).

### 4.3 Servicio `app/services/property_match_service.py`

- `candidate_alerts(db, prop) -> list[PropertyAlert]`: alertas abiertas con comprador y perfil,
  agente activo, perfil completo, de todas las empresas; prefiltro SQL por operación y precio
  máximo (`max_price >= prop.price`) para no evaluar todo en Python; luego
  `criteria_matches_property`. **Gancho para «Reserva»** (§6): esta función es el único sitio
  que decide qué alertas entran.
- `match_property(db, prop, now, actor=None) -> list[PropertyBuyerMatch]`: si la propiedad no
  está activa o no tiene captador → `[]`. Inserta filas nuevas (ignora las ya existentes),
  agrupa por agente y crea **una** notificación `property_match` por agente y empresa de la
  alerta (un agente con alertas compatibles en las dos empresas recibe una por empresa, con su
  distintivo en la vista unificada). `actor` = quien dio el OK (nunca se avisa a sí mismo si
  es también agente de alguna alerta: `notify` ya lo excluye; en ese caso marcar `notified_at`
  igualmente). Commit propio; nunca lanza (lo llama `mark_ok` del plan 1).
- `matches_for_property(db, prop, agent_id=None)` (con alerta, comprador, perfil y agente
  cargados en una tanda) y `matches_count_for_property(db, prop)` para la página y el detalle.

### 4.4 Notificación al agente

`NotificationKind.PROPERTY_MATCH = "property_match"` → `("users", "violet")`. Título «{N}
{comprador encaja / compradores encajan} con una propiedad nueva · {title}»; cuerpo «{tipo} en
{zona/población} · {precio} · {hasta 3 nombres}…»; url `/properties/{id}/matches`; entidad
`("property", prop.id)`. Dedupe de `notify` (24 h) suficiente.

### 4.5 Página «Compradores compatibles» `GET /properties/{id}/matches`

En `routes/properties.py` (o `alerts.py` si encaja mejor con `_send_property`). Acceso: admin
de alguna empresa de trabajo = empresa de la propiedad; agente con al menos una fila de cruce
propia (la propiedad puede ser de otra empresa: la página no es la ficha, no enseña
propietario ni dirección completa).

- Cabecera: `page_header` con el título de la propiedad, tipo · población · dormitorios ·
  precio, distintivo de empresa, enlace «Ver en la web» (`prop | public_url`), badge de la
  revisión («Revisada»).
- Lista (agente: solo sus compradores; admin: todos agrupados por agente): nombre del comprador,
  teléfono (`phone_display` + `tel_href`), `criteria_summary` del perfil, etapa/estado de la
  alerta, botón «Ver comprador» (`/alerts/{id}`), botón «Enviar por WhatsApp» (formulario POST a
  `/alerts/{alert_id}/send-property` con `property_id`, `target="_blank"`, como en
  `property_card`, con la misma regla: sin enlace o sin teléfono válido no hay botón y se
  dice por qué) y línea «Enviada el …» si ya se envió (`sent_dates`). El admin ve el botón de
  enviar solo en las alertas que puede gestionar (misma regla que `/alerts/{id}/send-property`).
- Admin además: «N agentes avisados», y en el **detalle de la propiedad** un bloque
  «Compradores compatibles: N · Ver» (solo si hay cruces).
- Vacío: «Ningún comprador encaja con esta propiedad».

### 4.6 Configuración y jobs

Ninguno nuevo: el cruce se hace en la petición del OK (síncrono, la consulta es pequeña) y el
envío lo hace el agente. Si en el futuro se activa el envío automático, entraría aquí como job.

## 5. Archivos

- Nuevos: `app/models/property_buyer_match.py`, `app/services/property_match_service.py`,
  `alembic/versions/<id>_property_buyer_matches.py`, `templates/properties/matches.html`,
  `tests/test_criteria_matches_property.py`, `tests/test_property_match_service.py`,
  `tests/test_property_matches_page.py`.
- Tocados: `app/db/base.py`, `app/services/buyer_matching.py`,
  `app/services/notification_service.py`, `app/services/property_review_service.py` (llamada
  desde `mark_ok`), `app/web/routes/properties.py` (o `alerts.py`), `properties/detail.html`,
  `dashboard/components/icons.html` (si hace falta otro icono), `activity_log_view.py`,
  `MULTIEMPRESA_MOYZA_MOES.md` (migración).

## 6. Relación con «Reserva de compradores» (no se implementa ahora)

El requisito futuro: compradores solventes a los que hoy no se les puede ofrecer nada; un
estado nuevo (p. ej. `RESERVED`, pestaña «En reserva» en Compradores) para que, cuando entre
una oferta que encaje, se les retome. Este plan es el motor que lo hace posible:

- `candidate_alerts` es el único punto donde se decide qué alertas entran al cruce: añadir
  `RESERVED` a los estados (y, si se quiere, avisar con otro `kind` «Comprador en reserva:
  hay una propiedad nueva que encaja») es un cambio local.
- `property_buyer_matches` ya guarda el historial de cruces por comprador: la pestaña «En
  reserva» puede enseñar «N propiedades nuevas compatibles desde que está en reserva».
- Lo que faltaría entonces: el estado y su transición (cerrar como «en reserva» en vez de «sin
  interés»), la pestaña, que la reserva no cuente como alerta parada en los avisos R1/R3 y la
  regla de «despertar» la alerta (volver a `IN_PROGRESS`) al asociar la propiedad.

## 7. Tests

- `test_criteria_matches_property.py`: cada filtro por separado (país vacío = España, provincia
  por CP, poblaciones, zonas vacías = todas, tipos múltiples y `property_type` antiguo,
  operación, rangos de precio y dormitorios, baños, ascensor sí/no/indiferente, garaje) y el
  **test cruzado** contra `matching_properties` con la BD.
- `test_property_match_service.py`: candidatos (abiertas sí, cerradas no, perfil incompleto no,
  sin comprador no, agente inactivo no, las dos empresas sí); idempotencia (segundo cruce no
  duplica ni vuelve a avisar); un aviso por agente y empresa con el conteo correcto; no se
  avisa al actor; propiedad no activa o sin captador → nada; `mark_ok` del plan 1 produce los
  cruces y, si `match_property` falla, el OK se guarda igual.
- `test_property_matches_page.py`: acceso (admin de la empresa, agente con cruces, agente sin
  cruces → 404/redirección), render con botón de enviar, «Enviada el», «Sin enlace web» y «Sin
  teléfono válido»; el POST de envío desde la página registra `PROPIEDAD_ENVIADA` y la alerta
  sigue «sin gestionar»; bloque en el detalle.

## 8. Verificación

1. `import app.main`; `alembic upgrade head` / `downgrade -1` / `upgrade head`.
2. Suite completa sin fallos nuevos.
3. `build_css.sh` + clases nuevas en el CSS; `ui_lint.py` sin avisos nuevos.
4. Móvil 375 px: página de compatibles (filas con dos botones) y bloque del detalle.
5. Prueba en local con el seed (`scripts/seed_demo_data.py`): crear una propiedad que encaje
   con dos compradores de agentes distintos, darle el OK desde la revisión → un aviso por
   agente → página de compatibles → «Enviar por WhatsApp» (303 a `wa.me`) → «Enviada el» en la
   página y seguimiento en la alerta.

## 9. Respuestas del usuario (2026-11-24)

1. Mensaje al comprador: **un clic del agente** desde su WhatsApp. Envío automático descartado (P3).
2. Candidatos: **alertas abiertas** (`PENDING` + `IN_PROGRESS`) con perfil completo (P2).
3. Un aviso por agente y propiedad (P1): sin objeción.
4. La ETL trae el enlace web en la misma carga que la propiedad (P6).

## 10. Entrega

Sin commits. Informe con archivos tocados, resultado numérico de cada verificación, decisiones
tomadas donde el plan dejaba margen y la sección «Estado» al final de este archivo.

## Estado (2026-11-24)

**Implementado entero** (§4.1–§4.5, §6 solo el gancho, §7, §8). Sin commits.

Hecho:
- §4.1 `buyer_matching.criteria_matches_property`: réplica en Python de `_matching_filters`,
  condición por condición (trim de PostgreSQL = solo espacios, NULL nunca cumple salvo «sin
  ascensor»), documentada como la ÚNICA segunda implementación.
- §4.2 modelo `PropertyBuyerMatch` (`app/models/property_buyer_match.py`, en `db/base.py`) y
  migración `s5t6u7v8w9x0` sobre `r4s5t6u7v8w9`: unique `(property_id, alert_id)`, índices por
  `property_id` y `agent_id`, sin backfill.
- §4.3 `app/services/property_match_service.py`: `candidate_alerts` (con el comentario del gancho de
  «Reserva» y `CANDIDATE_STATUSES`), `match_property(db, prop, now, actor=None)` (firma que ya
  esperaba `mark_ok`; `mark_ok` no se ha tocado), `matches_for_property`,
  `matches_count_for_property`, `notified_agents_count`.
- §4.4 `NotificationKind.PROPERTY_MATCH = "property_match"` → `("users", "violet")`; título y cuerpo
  del plan, url `/properties/{id}/matches`, entidad `("property", id)`.
- §4.5 `GET /properties/{id}/matches` en `routes/properties.py` + `templates/properties/matches.html`;
  bloque «Compradores compatibles: N · Ver compradores» en `properties/detail.html`; `next` en
  `POST /alerts/{id}/send-property` para que los errores vuelvan a la página; coletilla del flash
  del OK; regla en `activity_log_view.py`; `property_buyer_matches` en `reset()` del seed;
  `MULTIEMPRESA_MOYZA_MOES.md` §25.

Verificación (§8):
1. `import app.main`: OK. Migración: la base local tiene la fila ajena `q3c4p5t6a7b8` (Captaciones)
   y `alembic upgrade head` se niega; sin tocar esa fila, se aplicó el SQL que genera alembic en
   modo offline (`alembic upgrade r4s5t6u7v8w9:head --sql | psql`, que solo cambia la fila
   `r4s5t6u7v8w9`): upgrade → downgrade (`s5t6u7v8w9x0:r4s5t6u7v8w9 --sql`) → upgrade sin errores.
   `alembic_version` queda con `s5t6u7v8w9x0` y `q3c4p5t6a7b8`.
2. Tests: antes **1476 passed / 3 failed**; después **1549 passed / 3 failed** (los mismos 3 previos).
   Nuevos (+73): 51 en `test_criteria_matches_property.py` (incluye el test cruzado con 16 perfiles
   × todas las propiedades de la base y otro con los 17 perfiles reales), 10 en
   `test_property_match_service.py` y 12 en `test_property_matches_page.py`.
3. `build_css.sh`: clases nuevas en el CSS (`md:flex-row`, `md:items-center`, `md:shrink-0`,
   `sm:min-h-0`, `sm:max-w-[14rem]`; las `violet-*` ya estaban). `ui_lint.py`: 170 avisos antes y
   170 después, ninguno en `matches.html` ni en las líneas nuevas de `detail.html`.
4. 375 px por CDP: página de compatibles como admin (dos filas, dos botones cada una) y como
   agente, y detalle con el bloque: `scrollWidth` = 375, ningún elemento desbordado, botones de 42 px.
5. Prueba manual con el seed: propiedad «Piso Centro Jaén» insertada por SQL (captadora Marta,
   185.000 €, 3 dorm.) → job `register_property_reviews` → `pending` → «Todo correcto» de Marta
   (303) → 2 cruces (Alberto de Lucía, Beatriz de Carlos) y **un aviso por agente** (Lucía y Carlos,
   violet, en su campana y en /notifications) → página de compatibles 200 para Lucía (solo
   Alberto; sin botón: «Gestiona antes los compradores anteriores de tu cola», su cola real está
   bloqueada), Carlos (Beatriz, con botón) y admin («2 agentes avisados») → «Enviar por WhatsApp»
   de Carlos: **303 a `https://wa.me/34655010110?text=Hola Beatriz, soy Carlos Ruiz Molina…`** →
   «Enviada el 24/11/2026» en la página y `PROPIEDAD_ENVIADA` en la alerta (visible en su
   historial) → detalle del admin con el bloque. Datos borrados después (propiedad, revisión,
   cruces, avisos, seguimiento y registros de actividad de la prueba).

Decisiones donde el plan dejaba margen:
- Candidatos: además de P2, se excluyen las alertas de **Alquiler** (`profile_applies`): en Alquiler
  el perfil no se muestra ni sugiere propiedades, así que tampoco cruza. Prefiltro SQL por operación
  del perfil y `max_price >= price`.
- Notificación: cuenta y nombra solo las alertas **nuevas** de ese cruce; cuerpo «…· Ana, Luis,
  Marta y 2 más». Dedupe de `notify` (24 h) tal cual.
- `match_property` nunca lanza: captura todo, deshace y devuelve `[]` (además del `try` de `mark_ok`).
- El agente ve en la página los cruces de las alertas que **lleva hoy** (`PropertyAlert.agent_id`):
  si una alerta se reasigna, la ve el nuevo agente; `property_buyer_matches.agent_id` guarda a quién
  se avisó. Agente sin cruces → 302 a `/alerts` con flash; admin de otra empresa → 302 a `/properties`.
- Filas sin botón dicen por qué: «Alerta cerrada», «Comprador de {empresa}: cambia de empresa para
  enviarla» (admin, alerta de la otra empresa), «Gestiona antes los compradores anteriores de tu
  cola» (agente con la alerta bloqueada; tampoco «Ver comprador»), «Sin enlace web», «Sin teléfono
  válido». El teléfono es `alert.lead_phone`, el mismo que usa el envío.
- «Ver ficha» en la cabecera: admin, o el agente si es el captador (la ficha enseña propietario).
- El bloque del detalle lo ve también el **agente** con sus cruces (no solo el admin): el captador
  que da el OK no recibe aviso de sus propios compradores (`notify` excluye al actor), así que el
  bloque y el flash del OK («. 2 de tus compradores encajan con ella»; admin: «. N compradores
  encajan con ella: se ha avisado a sus agentes») se lo dicen.
- El envío desde la página manda `next=/properties/{id}/matches` (validado con una regex exacta):
  los errores vuelven a la página en vez de a la Propuesta de la alerta.

Riesgos y pendientes:
- Un comprador con dos alertas abiertas de Venta (dos agentes) sale dos veces, una por alerta.
- El cruce es síncrono en la petición del OK: con muchos perfiles abiertos convendría vigilar el
  tiempo (hoy el prefiltro SQL lo deja en pocas filas).
- «Reserva de compradores» (§6) no implementada: solo el gancho en `candidate_alerts`.

## 11. Seguimiento para el admin (2026-11-27, solo lectura)

Tras el despliegue en producción el equipo dijo que, al confirmar propiedades nuevas, no llegaron
avisos de compradores. Para saber qué pasó sin tocar nada se añadió una pantalla de diagnóstico,
solo para el admin y que NO escribe (ni cruza, ni avisa, ni cambia estados):

- `GET /properties/seguimiento-nuevas` (filtros: últimos N días, estado de la revisión, empresa
  activa o todas las del admin). Resumen por estado, «embudo» de compradores que pueden entrar hoy
  al cruce (abiertas con comprador → agente activo → Venta → con perfil → completo → agente con
  usuario) y una fila por propiedad nueva: datos que usa el cruce, captador (con/sin usuario),
  revisión con fechas y quién, compradores registrados al dar el OK (agentes, con aviso),
  compradores que ENCAJAN HOY (simulación con los datos actuales), avisos creados/leídos y un
  diagnóstico en texto con la causa más probable.
- `GET /properties/seguimiento-nuevas/{id}`: detalle con todos los datos de la propiedad (vacíos
  marcados), revisión paso a paso, avisos al captador y a los agentes (leído / sin leer), y TODAS
  las alertas abiertas con comprador evaluadas: registradas, encajan hoy, fuera del cruce (cerrada,
  sin perfil, incompleto, agente inactivo, Alquiler) y no encajan con TODAS las condiciones que
  fallan y sus valores («Población: «Jaen» no está en Jaén (solo difiere en acentos…)»,
  «Dormitorios: sin dato y el perfil pide como máximo 3»). También las cerradas en los últimos 90
  días que sí encajarían.
- Servicio `app/services/property_review_audit_service.py`: `reasons_not_matching` es otra
  réplica de `criteria_matches_property` (lista vacía ⇔ encaja; test cruzado sobre perfiles
  reales), `explain_alert` sigue el orden de `candidate_alerts`, `audit_rows` / `audit_detail`.
- Router propio `routes/property_review_audit.py`, incluido ANTES que `properties` en `main.py`
  (si no, `/properties/{property_id}` captura la ruta). Acceso desde el botón «Seguimiento nuevas»
  del listado de Propiedades (solo admin). Las `skipped` de la migración (todas con el mismo
  `created_at`) solo entran al periodo por su `market_entry_date`.
- Tests: `tests/test_property_review_audit.py`.

Causas que la pantalla hace visibles (las que puede haber en producción): propiedad omitida como
histórica (`market_entry_date` > 15 días) o sin captador; OK dado por el único agente con
compradores compatibles (nunca se avisa a sí mismo); agentes sin usuario activo; perfiles
incompletos (falta población o dormitorios máximos con la regla nueva); población/zona/tipo con
texto distinto al de la propiedad (acentos); dato vacío en la propiedad (dormitorios, CP);
precio por encima del máximo; alertas cerradas.
