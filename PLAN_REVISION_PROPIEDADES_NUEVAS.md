# Plan: revisión obligatoria de las propiedades nuevas por el captador

Fecha: 2026-11-24. Rama: `63-agregar-moes`. Ejecuta: Opus 5.5 (high).
Relacionado: `PLAN_COMPRADORES_COMPATIBLES_PROPIEDAD_NUEVA.md` (se dispara cuando esta revisión
termina en «Correcta»), `PLAN_DASHBOARD_INICIO.md` §4 (notificaciones), `PLAN_RUIDO_CAMPANA.md`.
No mezclar con la rama `90-agregar-pestaña-de-captaciones` (Captaciones tiene un flujo de
estados parecido pero es otro módulo y el usuario no quiere unirlos todavía).

## 1. Objetivo

Cuando entra una propiedad nueva (la carga la ETL del CRM directamente en `properties`, o la
crea el admin desde Propiedades), el captador tiene que **leer la ficha** y decir si está
correcta. Si no lo está, lo dice con un comentario, el admin la corrige y el captador vuelve a
dar el OK. Hasta que da el OK la propiedad le aparece como pendiente en varios sitios
(campana, Inicio, aviso fijo) con un color propio para que no se confunda con el resto de avisos.

## 2. Cómo está hoy (comprobado 2026-11-24)

- `properties` no tiene `created_at`, ni origen (`source`), ni hook de inserción: la ETL
  escribe en la tabla desde fuera de la app (`docs/DISENO_SINCRONIZACION_CRM.md` es solo un
  diseño; no hay código de sync en `app/`). Lo único que hoy detecta «hay algo nuevo» es
  `GET /api/properties/last-update` con `max(market_entry_date)`.
- Solo el admin crea propiedades en la app (`POST /properties/create`,
  `routes/properties.py:598`); el captador es `agent_id`.
- Notificaciones in-app: tabla `notifications`, `services/notification_service.py`
  (`notify`, `safe_notify`, `users_for_agent`, dedupe 24 h por `kind` + entidad), campana solo
  para agentes (`navbar.html`, `static/js/notifications.js`), bloque «Novedades» del Inicio
  del agente y página `/notifications`. El admin no tiene campana (decisión §6-3): ve
  «Requiere atención» en su Inicio (`DashboardService.attention`).
- Tonos disponibles en campana/Inicio: `blue`, `green`, `amber`, `red`, `gray`
  (`NotificationKind.STYLES`, `icons.html::_icon_tones`, `notifications.js::TONES`). La
  paleta del skill (`tokens.md`) no tiene un color para «revisión»: hay que añadirlo primero
  ahí.
- Jobs: APScheduler solo en el worker maestro (`jobs/scheduler.py`); patrón de job con `now`
  inyectable y `SessionLocal`.

## 3. Decisiones

Cerradas por el usuario (2026-11-24):

- D1. El captador debe revisar y marcar **«Correcta»** o **«Revisar»** (con comentario). Lo que
  marca «Revisar» lo corrige el admin y vuelve al captador para el OK definitivo.
- D2. Avisos en la **campana y en el Inicio**, en una sección propia y con color distinto.
- D3. Al dar el OK se dispara el plan de compradores compatibles (otro plan).

Confirmadas por el usuario el 2026-11-24 (ver §9):

- P1. **Detección por tabla de revisiones, no por fechas**: una propiedad sin fila en
  `property_reviews` es nueva. La migración crea una fila `skipped` para todas las existentes,
  así nada anterior al despliegue pide revisión. No depende de que la ETL rellene
  `market_entry_date`.
- P2. Para «obligar a leer»: **ventana al entrar** (modal que se abre al iniciar sesión, como
  la de «Compradores que requieren atención») con las propiedades por revisar, más el bloque
  propio en el Inicio y la notificación en la campana. Si el agente también tiene compradores
  pendientes, primero sale la de propiedades y, al cerrarla, la de compradores. Sin aviso fijo
  en todas las páginas.
- P3. Solo piden revisión las propiedades **activas** (`status = Activa`) con captador. Las que
  entran ya vendidas/archivadas quedan `skipped`; las activas sin captador no se registran hasta
  tenerlo (la ETL trae el captador y el enlace web en la misma carga, así que será raro).
- P4. El **admin puede marcar «Correcta»** en cualquier momento (captador sin usuario en la
  app, o decisión del admin). Queda registrado quién la marcó.
- P5. Recordatorio: **un solo aviso más** al captador a las 48 h hábiles sin revisar
  (configurable), y el admin lo ve en «Requiere atención». Nada de repetir cada día
  (`PLAN_RUIDO_CAMPANA.md`).
- P6. Color nuevo en la paleta: **`violet`** = «propiedades nuevas» (revisión y compradores
  compatibles). Se añade a `tokens.md` con sus tonos (badge, banner, icono de KPI) antes de
  usarlo.
- P7 (pedido por el usuario, 2026-11-24). **`market_entry_date` se combina con la tabla**: la
  tabla detecta que la propiedad es nueva para la app; `market_entry_date` (fecha de alta en el
  CRM) decide si es nueva de verdad. Si al detectarla tiene más de
  `PROPERTY_REVIEW_MAX_AGE_DAYS` (15) días, se registra `skipped` sin avisar (carga histórica).
  Sin fecha se trata como nueva. Es también la fecha «En el mercado desde …» que se muestra en
  la ventana, el Inicio y la caja de revisión (sin ella, «Detectada el …» con `created_at`).
  Por qué no una marca de agua sobre la fecha sola: la ETL corre cada ~3 h y el CRM puede
  cargar inmuebles con fecha atrasada, que quedarían sin aviso; y la tabla hace falta igual
  para el estado y los comentarios.

## 4. Diseño

### 4.1 Modelo y migración

Tabla `property_reviews` (modelo `app/models/property_review.py`, registrar en `db/base.py`):

| Columna | Tipo | Notas |
|---|---|---|
| `id` | PK | |
| `property_id` | FK `properties.id` ON DELETE CASCADE, **unique** | una revisión por propiedad |
| `agent_id` | FK `agents.id` ON DELETE SET NULL, nullable | captador al que se pidió la revisión |
| `status` | String, not null | `pending` · `issues` · `fixed` · `ok` · `skipped` |
| `agent_comment` | Text, nullable | lo que el captador pidió revisar (obligatorio al marcar «Revisar») |
| `admin_comment` | Text, nullable | qué corrigió el admin (opcional) |
| `rounds` | SmallInteger, default 0 | veces que se marcó «Revisar» |
| `created_at` | DateTime | cuándo la app vio la propiedad |
| `notified_at` | DateTime, nullable | primer aviso al captador |
| `reminded_at` | DateTime, nullable | recordatorio (solo uno) |
| `flagged_at` | DateTime, nullable | último «Revisar» |
| `fixed_at`, `fixed_by` | DateTime / FK users SET NULL | última corrección del admin |
| `ok_at`, `ok_by` | DateTime / FK users SET NULL | OK definitivo |

Índice `(status, agent_id)`. Relación `Property.review` (`uselist=False`).

Estados y transiciones (`PropertyReviewStatus` en `core/constants.py`, con etiquetas y color):

| De | A | Quién | Qué pasa |
|---|---|---|---|
| `pending` | `ok` | captador o admin | `ok_at/ok_by`; dispara compradores compatibles |
| `pending` | `issues` | captador | comentario obligatorio; `rounds += 1`; admin lo ve en «Requiere atención» |
| `issues` | `fixed` | admin | comentario opcional; aviso al captador «confirma que está correcta» |
| `issues` | `ok` | admin | atajo del admin (P4); dispara compradores compatibles |
| `fixed` | `ok` | captador o admin | igual que pending → ok |
| `fixed` | `issues` | captador | segunda vuelta |

Migración Alembic (`down_revision = 'q3x4y5z6a7b8'`, cabeza actual; comprobar con
`alembic heads`): crea la tabla y **backfill** `INSERT … SELECT id, agent_id, 'skipped', now()
FROM properties`. Downgrade: drop table.

### 4.2 Servicio `app/services/property_review_service.py`

- `register_new_properties(db, now) -> list[PropertyReview]`: propiedades sin fila (LEFT OUTER
  JOIN). Crea `pending` si `status == Activa` y `agent_id` no es nulo; `skipped` si no está
  activa; **no crea nada** si está activa sin captador (se recoge cuando lo tenga).
- `notify_pending(db, now) -> int`: filas `pending` con `notified_at` nulo → notificación
  `property_review_pending` a `users_for_agent(review.agent)` (empresa = la de la propiedad,
  url `/properties/{id}#revision`, entidad `("property_review", review.id)`). Marca
  `notified_at` aunque el captador no tenga usuario (se registra en el log); el admin lo verá
  en «Requiere atención» si pasa el plazo.
- `remind_overdue(db, now) -> int`: `pending`/`fixed` con más de
  `settings.PROPERTY_REVIEW_REMINDER_BUSINESS_HOURS` (48) horas hábiles desde `notified_at`
  (o `fixed_at`) y `reminded_at` nulo → segundo aviso, mismo `kind`, título «Sigue pendiente:
  revisa la propiedad …». Una sola vez.
- `mark_ok(db, review, user, now)`, `flag_issues(db, review, user, comment, now)`,
  `mark_fixed(db, review, user, comment, now)`: aplican la tabla de transiciones, lanzan
  `ValueError` si no procede, confirman y, en `mark_ok`, llaman a
  `property_match_service.match_property(...)` (plan 2) dentro de un `try` que nunca rompe el OK.
- `pending_for_agent(db, agent_id) -> list` (pending + fixed, con la propiedad cargada) para el
  Inicio, el aviso fijo y el badge; `counts_for_admin(db, company_ids, now)` → `{"issues": n,
  "overdue": n}` para «Requiere atención»; `pending_count_for_user(db, user)` para el aviso fijo.
- `review_for_property(db, property_id)` y `can_review(review, user, agent, is_admin)` → qué
  botones se pintan (captador: Correcta / Revisar; admin: Corregida / Correcta).
- Hook inmediato: `POST /properties/create` llama a `register_new_properties` +
  `notify_pending` tras el commit (`safe_*`, nunca rompe el alta). La ETL la cubre el job.

### 4.3 Notificaciones

`NotificationKind`:

- `PROPERTY_REVIEW_PENDING = "property_review_pending"` → `("clipboard", "violet")`. Título
  «Propiedad nueva: revisa la ficha · {title}»; cuerpo «{tipo} en {zona/población} · {precio}
  · Marca si está correcta o qué hay que revisar».
- `PROPERTY_REVIEW_FIXED = "property_review_fixed"` → `("clipboard", "violet")`. «Propiedad
  corregida: confirma que está correcta · {title}»; cuerpo = `admin_comment` si lo hay.

Nunca al actor (`notify` ya lo hace). Añadir el icono `clipboard` (Heroicon
`clipboard-document-check`) y el tono `violet` en `icons.html` (`_icon_paths`, `_icon_tones`)
y en `notifications.js` (`ICONS`, `TONES`). `serialize` no cambia.

### 4.4 Interfaz (leer antes `.claude/skills/moyza-ui-ux-pro/SKILL.md`, `tokens.md`, `components.md`)

Paleta: añadir en `tokens.md` la fila «Propiedades nuevas (revisión y compradores compatibles)
| `violet`» y los tonos (`bg-violet-100 text-violet-800` badge, `bg-violet-50 border-violet-200
text-violet-900` banner, `bg-violet-100 text-violet-600` icono). Extender los mapas de
`ui_macros.html` (`badge`, `banner`) y `status_badge` con el dominio `review`:

| `review` | `pending` | Por revisar | violet |
| | `issues` | Con observaciones | amber |
| | `fixed` | Corregida · pendiente de OK | violet |
| | `ok` | Revisada | green |

1. **Ventana al entrar** (agente, `dashboard/_agent.html`): modal `pendingReviewsModal`
   («Propiedades nuevas por revisar», `ui.modal`, `data-auto-open-on-login`) con una fila por
   propiedad pendiente (`title`, tipo · población · precio, «desde {fecha}», badge del estado,
   distintivo de empresa si `show_company_badges`) y botón «Revisar ficha»
   (`/properties/{id}#revision`); pie «Lo reviso después». Solo existe si hay pendientes.
   `static/js/dashboard.js`: al iniciar sesión abre los modales marcados **en orden** (primero
   el de propiedades, después el de compradores): abre el primero y, al cerrarse (evento de
   `ui.js` o `MutationObserver` sobre `hidden`), abre el siguiente. Si solo hay uno, como hoy.
   Hay que comprobar cómo cierra `window.UI.openModal` / `closeModal` para engancharse sin
   duplicar lógica.
2. **Inicio del agente** (`dashboard/_agent.html`): sección nueva **«Propiedades nuevas por
   revisar»** encima de «Mis resultados», tarjeta con borde/fondo `violet`, las mismas filas que
   la ventana y botón «Revisar ficha». Solo se pinta si hay alguna; el botón «Ver pendientes»
   de la cabecera reabre la ventana a mano. `DashboardService.agent_home` añade `home.reviews`.
3. **Detalle de la propiedad** (`properties/detail.html`, ancla `#revision`, encima del
   bloque de cabecera): caja de revisión según estado y rol.
   - Captador con `pending`/`fixed`: «Revisa esta ficha» (lista corta de lo que debe comprobar:
     dirección, precio, tipo, dormitorios, m², enlace web) + si `fixed`, el `admin_comment`;
     botones **«Todo correcto»** (POST ok) y **«Hay que revisar»** (abre modal con textarea
     obligatoria, POST issues).
   - Admin con `issues`: «El captador pide revisar: {agent_comment}» + aviso «Edita la propiedad
     con *Editar* y después márcala como corregida»; botones **«Marcar como corregida»** (modal
     con comentario opcional, POST fixed) y **«Marcar correcta»** (POST ok, confirm).
   - Admin con `pending`/`fixed`: «Pendiente de que {captador} la revise desde {fecha}» +
     «Marcar correcta» (P4).
   - Cualquiera con `ok`: línea discreta «Revisada por {nombre} el {fecha}». `skipped`: nada.
4. **Listado de Propiedades** (`properties/home.html` + `table.html`): tarjeta-filtro nueva
   «Por revisar · N» (violet; admin: `pending + issues + fixed` de la empresa activa; agente:
   las suyas `pending + fixed`) que activa `filtro=revision`; badge del estado junto al título
   en la tabla cuando no es `ok`/`skipped`. Comprobar cómo funciona hoy el parámetro `filtro`
   (`activas`, …) y seguir el patrón.
5. **Inicio del admin** (`DashboardService.attention`): dos elementos nuevos, tono `amber`:
   «N propiedades con observaciones del captador» (→ `/properties?filtro=revision`) y «N
   propiedades nuevas sin revisar desde hace más de 48 h hábiles» (→ igual). Icono `clipboard`.
6. Campana: nada que cambiar aparte de icono/tono; el enlace abre y marca leída como siempre.

### 4.5 Rutas (`routes/properties.py`)

- `POST /properties/{id}/review/ok` → captador (ficha de agente del usuario == `agent_id`) o
  admin de la empresa de la propiedad.
- `POST /properties/{id}/review/issues` (`comment` obligatorio, máx. 1000) → solo el captador.
- `POST /properties/{id}/review/fixed` (`comment` opcional) → solo admin.
- Todas: flash + redirección a `/properties/{id}#revision`; errores de transición → flash de
  error. Registrar etiquetas en `services/activity_log_view.py` («Revisó propiedad nueva»…).

### 4.6 Jobs y configuración

`core/config.py`: `PROPERTY_REVIEW_ENABLED` (true), `PROPERTY_REVIEW_POLL_MINUTES` (10),
`PROPERTY_REVIEW_REMINDER_BUSINESS_HOURS` (48). `.env.example` y guía de despliegue.

`jobs/scheduler.py`:
- `register_property_reviews(now=None)`: cada `POLL_MINUTES` (`interval`), `register_new_properties`
  + `notify_pending`. Idempotente (la fila única lo garantiza).
- `remind_property_reviews(now=None)`: 08:10 Madrid, lunes a viernes, `remind_overdue`.

## 5. Archivos

- Nuevos: `app/models/property_review.py`, `app/services/property_review_service.py`,
  `alembic/versions/<id>_property_reviews.py`, `tests/test_property_review_service.py`,
  `tests/test_property_review_routes.py`.
- Tocados: `app/db/base.py`, `app/models/property.py` (relación), `app/core/constants.py`,
  `app/core/config.py`, `app/services/notification_service.py`,
  `app/services/dashboard_service.py`, `app/services/activity_log_view.py`,
  `app/jobs/scheduler.py`, `app/web/routes/properties.py`,
  `dashboard/_agent.html`, `dashboard/components/icons.html`,
  `properties/detail.html`, `properties/home.html`, `properties/table.html`,
  `components/ui_macros.html`, `static/js/notifications.js`, `static/js/dashboard.js`,
  `.claude/skills/moyza-ui-ux-pro/references/tokens.md`, `.env.example`, `MULTIEMPRESA_MOYZA_MOES.md`
  (despliegue: migración + variables).

## 6. Tests

`test_property_review_service.py` (fixture de BD con transacción externa, como
`test_notification_service.py`):
- Backfill: tras la migración ninguna propiedad existente es `pending` (simular con filas `skipped`).
- `register_new_properties`: activa con captador → `pending`; vendida → `skipped`; activa sin
  captador → sin fila, y al asignarle captador en la siguiente pasada → `pending`.
- `notify_pending`: una notificación por usuario del captador, `violet`, url con `#revision`,
  `notified_at` marcado; segunda pasada no repite; captador sin usuario → `notified_at` marcado y 0 avisos.
- Transiciones válidas e inválidas (tabla de §4.1), comentario obligatorio en `issues`,
  `rounds`, quién puede qué.
- `mark_ok` llama a `match_property` y, si este falla, el OK se guarda igual.
- `remind_overdue`: a las 48 h hábiles un aviso y solo uno; `fixed` cuenta desde `fixed_at`.
- `counts_for_admin` y `pending_for_agent` por empresa.

`test_property_review_routes.py` (patrón `test_alert_search.py` / `test_send_property.py`):
- Permisos de las tres rutas (captador, otro agente, admin de otra empresa).
- `POST /properties/create` deja la propiedad `pending` y avisa al captador (no al admin que la creó).
- Render del detalle en cada estado y rol; ventana y bloque del Inicio solo con pendientes;
  tarjeta y filtro del listado; `attention` del admin.

## 7. Verificación

1. `docker exec moyza_backend python -c "import app.main"`.
2. `alembic upgrade head` → `downgrade -1` → `upgrade head` en local; comprobar que las 34
   propiedades locales quedan `skipped`.
3. `python -m pytest -q tests` sin fallos nuevos (fallos previos conocidos:
   `test_check_automatic_reports_con_propiedad_activa`, `test_alert_assignment_routes.py` ×2,
   `test_dashboard_service` kpis).
4. `bash backend/scripts/build_css.sh` y grep de las clases `violet` nuevas en el CSS compilado
   (también las que solo están en `notifications.js`: comprobar que `tailwind.config.js` cubre
   `static/js`).
5. `python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates` sin
   avisos nuevos.
6. Móvil 375 px por CDP (memoria `probar-movil-chromium-headless`): ventana al entrar, bloque
   del Inicio, caja de revisión y modal de «Hay que revisar». Comprobar en el navegador la
   cadena de dos ventanas (propiedades → compradores) con la cookie `moyza_welcome`.
7. Prueba en local: insertar una propiedad con SQL (como haría la ETL) → job → campana del
   captador (`123456` del seed) → «Hay que revisar» → admin la edita y marca corregida →
   captador «Todo correcto» → entrada en el historial de actividad y, si el plan 2 está, los
   compradores compatibles.

## 8. Fuera de alcance

- Sincronización CRM dentro de la app (`docs/DISENO_SINCRONIZACION_CRM.md`).
- Hilo de comentarios con adjuntos (eso es Captaciones). Aquí un comentario por vuelta.
- Email o WhatsApp al captador: solo in-app (`PLAN_DASHBOARD_INICIO.md`, principio 1).
- Bloquear otras acciones del agente hasta que revise.
- Revisión de los cambios posteriores que haga la ETL sobre una propiedad ya revisada.

## 9. Respuestas del usuario (2026-11-24)

1. Para obligar a leer: **ventana al entrar** (no el aviso fijo). Recogido en P2 y §4.4-1.
2. Las propiedades existentes al desplegar no piden revisión (P1): sin objeción.
3. El admin puede dar el OK por el captador (P4): sin objeción.
4. La ETL trae el captador y el enlace web **en la misma carga** que crea la propiedad.

## 10. Entrega

Sin commits. Informe con archivos tocados, resultado numérico de cada verificación, decisiones
tomadas donde el plan dejaba margen y la sección «Estado» al final de este archivo.

## Estado (2026-11-24)

**Implementado entero** (§4.1–§4.6, §6, §7) más el ajuste P7 (`market_entry_date`). Sin commits.

Hecho:
- Modelo `PropertyReview` (+ `Property.review`), `PropertyReviewStatus` (etiquetas y tono),
  migración `r4s5t6u7v8w9` sobre `q3x4y5z6a7b8` con backfill `skipped`.
- `property_review_service`: registro (P1, P3, **P7**: `market_entry_date` de hace más de
  `PROPERTY_REVIEW_MAX_AGE_DAYS`=15 días → `skipped` sin avisar; sin fecha → nueva), avisos,
  recordatorio único, transiciones, `can_review`, lecturas por empresa y gancho protegido a
  `property_match_service.match_property(db, prop, now, actor=...)` (si no existe o falla, el OK
  se guarda igual).
- Notificaciones `property_review_pending` / `property_review_fixed` (`clipboard`, `violet`).
- Interfaz: `violet` en `tokens.md` (paleta, tonos y dominio `review`), `ui_macros.html`
  (`badge`, `banner` con icono propio, `kpi`, `status_badge("review", …)`), `icons.html`,
  `notifications.js`; ventana `pendingReviewsModal` + bloque del Inicio del agente
  (`dashboard/components/review_item.html`), caja de revisión del detalle
  (`properties/_review_box.html`, con los datos a comprobar), tarjeta «Por revisar» y
  `filtro=revision` en Propiedades, badge del estado en la tabla, dos avisos en «Requiere
  atención» del admin. La fecha mostrada es «En el mercado desde …» (`market_entry_date`) o
  «Detectada el …» (`created_at` de la revisión).
- Cadena de ventanas al entrar: `ui.js` emite `ui:modal-closed` al cerrar; `dashboard.js` abre
  los `[data-auto-open-on-login="N"]` en orden (1 propiedades, 2 compradores).
- Rutas `POST /properties/{id}/review/{ok,issues,fixed}`, hook en el alta del admin, etiquetas
  en el registro de actividad, jobs `register_property_reviews` (cada 10 min) y
  `remind_property_reviews` (08:10 L-V, salta festivos), variables en `config.py`,
  `.env.example` y `MULTIEMPRESA_MOYZA_MOES.md` §24.

Verificación (§7):
1. `import app.main`: OK.
2. Migración en local: upgrade → downgrade → upgrade sin errores; las **34** propiedades locales
   quedan `skipped`, 0 sin fila. (La base local estaba en `q3c4p5t6a7b8` de Captaciones, que esta
   rama no conoce: se puso `q3x4y5z6a7b8` para poder migrar y al final `alembic_version` queda con
   las dos cabezas, `r4s5t6u7v8w9` y `q3c4p5t6a7b8`; al fusionar ramas, `alembic merge`.)
3. Tests: antes 1443 passed / 3 failed; después **1476 passed / 3 failed** (los mismos 3
   previos: `test_check_automatic_reports_con_propiedad_activa`,
   `test_agente_no_puede_elegir_agente`, kpis de `test_admin_home_kpis_equipo_cumplimiento_y_atencion`).
   Nuevos: 19 en `test_property_review_service.py` (uno por rama de P7) y 14 en `test_property_review_routes.py`.
4. `build_css.sh`: las 10 clases `violet` nuevas (`bg-violet-50/100/500`, `text-violet-600/800/900`,
   `border-violet-200/500`, `ring-violet-100`, `hover:border-violet-300`) están en el CSS;
   `tailwind.config.js` ya cubre `app/static/js/**/*.js`.
5. `ui_lint.py`: 170 avisos antes y 170 después, ninguno en los archivos nuevos o tocados.
6. 375 px por CDP: Inicio con la ventana, bloque, detalle (caja en `fixed`), modal «Hay que
   revisar» y listado filtrado con `scrollWidth` = 375 y ningún elemento desbordado. Cadena con
   `moyza_welcome`: se abre la de propiedades; al cerrarla, la de compradores; al volver al
   Inicio sin la cookie no se abre ninguna.
7. Prueba manual: dos propiedades insertadas por SQL (activa del día anterior y otra de hace 40
   días) → job: 2 registradas (1 `pending`, 1 `skipped` por P7) y 1 aviso violet en la campana
   de Lucía (`123456`) → «Hay que revisar» → admin la ve en «Requiere atención» y en
   `filtro=revision`, la edita y la marca corregida → aviso «Propiedad corregida…» → «Todo
   correcto» → `ok`, 0 avisos sin leer, tres entradas en Actividad Usuarios. El plan 2 aún no
   existe: sin compradores compatibles. Datos de la prueba borrados después.

Decisiones donde el plan dejaba margen:
- El captador es el **actual** de la propiedad (`Property.agent_id`) para listas y permisos;
  `review.agent_id` guarda a quién se avisó.
- Listas, contadores y recordatorio solo cuentan propiedades que **siguen activas** (una vendida
  o archivada antes de revisarse deja de pedirlo).
- `mark_fixed` reinicia `reminded_at`: el recordatorio único vale por cada espera del captador
  (desde `fixed_at`), no una vez en toda la vida de la revisión.
- Al resolverse (OK, «Revisar», corregida, recordatorio) los avisos sin leer de esa revisión se
  marcan leídos, como hacen los de compradores.
- Recordatorio de `fixed` con el tipo `property_review_fixed` y su texto («confirma que está
  correcta»); el de `pending`, con `property_review_pending`.
- Tarjeta «Por revisar» solo si hay alguna (o es el filtro activo); el agente ve sus
  `pending`+`fixed`, el admin `pending`+`issues`+`fixed` de la empresa activa.
- «Edita la propiedad con Editar»: el detalle no tiene botón Editar, así que la caja del admin
  enlaza a `/properties?filtro=revision`, donde la fila tiene «Editar».
- `pending_count_for_user` existe pero no se usa (P2 descartó el aviso fijo).
- El seed borra también `property_reviews` en `reset()`; no crea filas: las demo recientes
  quedarán `pending` en la siguiente pasada del job y las de más de 15 días, `skipped`.

Riesgos y pendientes:
- Si la ETL cambia el captador de una propiedad ya avisada, el nuevo captador la ve en el Inicio
  y en la ventana pero no recibe aviso en la campana.
- `remind_overdue` calcula «vencida» en Python sobre las abiertas (pocas filas; si crecen, pasar
  a SQL).
- Importar `app.jobs.scheduler` suelto (sin `app.db.base` antes) da una importación circular
  previa a este cambio; la app y los tests no se ven afectados.
- `.claude/skills/moyza-ui-ux-pro/assets/ui_macros.html` ya estaba desfasado respecto al del
  proyecto y no se ha tocado.

### Ajustes tras la prueba del usuario (2026-11-25)

- **Inicio del agente**: los avisos de propiedades nuevas (`property_review_pending`,
  `property_review_fixed`, `property_match` = `NotificationKind.PROPERTY_KINDS`) salen en su
  propio cuadro violet «Propiedades nuevas» encima de «Novedades», que ya no los mezcla ni los
  cuenta. `notification_service.recent` / `unread_count` aceptan `kinds` / `exclude_kinds`;
  la ruta del Inicio pasa `property_news` y `property_news_unread`. El cuadro solo sale si hay
  alguno. Test `test_inicio_del_agente_cuadro_propiedades_nuevas_separado` y
  `test_recent_y_unread_por_tipo`.
- **Inicio del admin**: ventana al entrar `reviewIssuesModal` («Propiedades por corregir»,
  `data-auto-open-on-login="1"`, antes que «Compradores sin gestionar», que pasa a `"2"`) y
  bloque del mismo nombre arriba del todo, con las revisiones `issues` de la empresa activa
  (`property_review_service.issues_for_admin`, `admin_home["review_issues"]`,
  componente `dashboard/components/review_issue_item.html`: título, comentario del captador,
  quién y cuándo, botón «Corregir» a `/properties/{id}#revision`). «Requiere atención» sigue
  igual. Tests `test_inicio_del_admin_ventana_y_bloque_por_corregir` e `issues_for_admin` en
  el test de contadores.
- Verificado: suite 1545 en verde + los 3 fallos conocidos; CSS recompilado; `ui_lint` 170
  avisos (sin cambios); 375 px sin desbordes en los dos Inicios y en la ventana del admin.
