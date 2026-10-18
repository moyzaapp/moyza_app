# Plan: alertas de comprador sin referencia (búsqueda general) y asociación posterior de propiedad

Fecha: 2026-10-16. Rama: `57-cambios-de-visitas-compradores-y-otros`.

## Objetivo

Un solo punto de entrada para crear alertas: **"Agregar alerta comprador"**. La
propiedad pasa a ser **opcional**. Si llega un comprador sin una referencia
concreta, se crea la alerta "sin referencia" (búsqueda general) y se asigna al
agente. Cuando el agente la atiende: llama, toma los **criterios de búsqueda**
(ubicación, tipo de inmueble, habitaciones, baños, precio, imprescindibles;
**no** superficie), ve las **propiedades sugeridas** disponibles de la empresa
(de cualquier agente) y **asocia a esa misma alerta** la que el comprador elige.
Puede **cambiar** la propiedad después. El botón y el modal "Agregar alerta con
filtro" desaparecen.

Desde el punto de vista del agente debe ser un flujo guiado, en el móvil, de
tres pasos: **Contactar → Perfil → Propuesta**.

## Decisiones cerradas con el usuario (no cambiar)

1. **Una sola alerta.** La búsqueda es la alerta; al elegir propiedad se asocia
   a esa misma alerta (no se crea otra). Puede cambiarse de propiedad más
   adelante (presupuesto, gustos).
2. **La alerta siempre la maneja el agente que atiende al comprador**, aunque la
   propiedad asociada sea de otro agente. No cambia de dueño al asociar.
3. **Propiedades sugeridas**: todas las disponibles de la **empresa activa**,
   de cualquier agente.
4. **Guardar los criterios cuenta como seguimiento**: se registra
   automáticamente un seguimiento `CALIFICADO` con los criterios como nota.
   Desbloquea la cola y deja constancia de cuándo se tomaron los datos. El
   perfil queda guardado en el comprador (`BuyerSearchCriteria`), reutilizable.
5. **Superficie (m²) sale del perfil en toda la app** (formulario de la ficha
   del comprador incluido) y deja de usarse para filtrar. Las columnas y datos
   existentes se conservan; no se borran.
6. **Dejar documentada** la decisión y su alternativa (alerta nueva enlazada a
   la propiedad) con las implicaciones para analítica y contadores, por si en
   el futuro se cambia. Ver sección "Documentación".

## Decisiones de diseño tomadas en este plan (cámbialas solo si rompen algo, y anótalo)

- Pueden crear alertas sin referencia **admin y agentes**. El admin debe elegir
  el agente (no hay propiedad de la que deducirlo); el agente queda asignado a
  sí mismo. Los agentes siguen sin poder crear alertas **con** referencia sobre
  propiedades ajenas (regla del 2026-10-16); asociar una propiedad ajena a una
  búsqueda **sí** se permite (decisión 2).
- La alerta guarda su **origen**: `origin = 'property'` (creada con referencia)
  o `'search'` (creada sin referencia). Solo las de origen `search` pueden
  asociar/cambiar propiedad. Las de origen `property` no cambian de propiedad
  (siguen significando "interés en este inmueble").
- Asociar o cambiar propiedad registra un seguimiento **real** (cuenta como
  gestión, no avanza etapa): nuevo `FollowUpActionType.PROPIEDAD_ASOCIADA`
  ("Propiedad asociada: {título}" / "Cambio de propiedad: de {A} a {B}").
  Entra en `REPEATABLE_ACTIONS` (no mueve la etapa visible) y en `labels` /
  `stage_badge_color`. **No** entra en `SYSTEM_ACTIONS`.
- Al asociar, si el comprador ya tiene **otra alerta abierta sobre esa misma
  propiedad** (de cualquier agente), se avisa y se exige confirmación, con el
  mismo patrón de duplicados que ya existe (`alert_duplicate_service`,
  banner + botón "de todas formas"). Al confirmar, se deja nota en el mensaje.
- El perfil del comprador es **uno por comprador** (modelo actual). Al guardar
  desde la alerta, `criteria.business_type = alert.business_type` y
  `criteria.agent_id = alert.agent_id`. Si el comprador ya tenía perfil, el
  formulario sale precargado.
- "Cambiar propiedad" vuelve a mostrar el paso Propuesta con el perfil actual
  (editable) y las sugerencias; la propiedad actual aparece marcada como
  "Asociada ahora".
- Los **contadores** de `/alerts` (pendientes / en proceso / completadas) no
  cambian: una búsqueda es una alerta más. Las métricas **por agente** siguen
  usando `alert.agent_id` (se quedan con quien atiende). Las métricas **por
  propiedad** solo cuentan la alerta cuando ya tiene propiedad asociada.

## Modelo de datos (una migración, NO ejecutar)

Head actual: `x7y8z9a0b1c2`. Nueva revisión `y8z9a0b1c2d3_alert_without_property`:

- `property_alerts.property_id` → **nullable**.
- `property_alerts.company_id` INTEGER, FK `companies.id`, **NOT NULL**, con
  índice. Backfill en la migración: `UPDATE property_alerts SET company_id =
  (SELECT company_id FROM properties WHERE properties.id = property_alerts.property_id)`,
  luego `ALTER … SET NOT NULL`.
- `property_alerts.origin` VARCHAR NOT NULL **server_default 'property'**.
- `property_alerts.property_linked_at` DATETIME nullable (cuándo se asoció la
  propiedad; para búsquedas).
- Downgrade: quitar las tres columnas y volver `property_id` a NOT NULL (si hay
  filas sin propiedad, el downgrade debe fallar con mensaje claro en vez de
  borrarlas).
- Modelo `PropertyAlert`: columnas nuevas, `property` nullable, relación
  `company`. `BuyerSearchCriteria`: sin cambios de esquema (m² se deja de usar).

## Alcance: todo lo que hoy asume que una alerta tiene propiedad

Inventario hecho el 2026-10-16 (volver a hacer el grep al empezar):

- `app/services/company_scope.py`: `scope_alerts` usa
  `PropertyAlert.property.has(Property.company_id == …)` → pasar a
  `PropertyAlert.company_id == company_id`. `get_alert_in_company` igual. Esto
  simplifica y acelera las 9 llamadas existentes.
- `app/web/routes/alerts.py`: `alerts_page` hace `join(Property, …)` (→
  `outerjoin`, y el filtro por texto `Property.title.ilike` debe seguir
  funcionando con `or_`), `is_alert_locked_for_user` usa
  `alert.property.company_id` (→ `alert.company_id`), `create_alert`,
  `alert_detail`, `search_properties`, `_build_matching_properties`,
  `buyer_detail`, y los `join(Property)` de contadores/filtros.
- `app/services/alert_view.py` (cola): si usa la propiedad para la empresa,
  pasar a `company_id`.
- `app/services/alert_assignment_service.py`: `assign` / `resolve_assignee`
  (`owner_agent_id` puede ser None sin propiedad) y `_notify_assigned` (cuerpo
  con `prop.title` → "Búsqueda general · {operación}" cuando no hay propiedad).
- `app/services/buyer_reminder_service.py`, `notification_service.py`,
  `dashboard_service.py`, `performance_report_service.py`,
  `commercial_results` (servicio y ruta), `jobs/scheduler.py`: revisar cada
  `join`/acceso a la propiedad de una alerta; donde la alerta deba seguir
  apareciendo sin propiedad → `outerjoin` + texto de respaldo; donde la métrica
  sea "por propiedad" → excluir las que no tienen (y anotarlo en la
  documentación de analítica).
- `app/services/alert_duplicate_service.py`: `find_duplicate_alerts` por
  comprador+propiedad sigue igual; añadir `find_open_search_alerts(db,
  company_id, buyer_id, business_type)` para avisar al crear una segunda
  búsqueda abierta del mismo comprador y operación.
- Plantillas: `alerts/list.html`, `alerts/detail.html`, `buyers/detail.html`,
  `commercial_results/_buyers.html`, `dashboard/_agent.html` (si muestra
  propiedad), notificaciones. Sin propiedad se muestra el distintivo
  **"Búsqueda general"** (badge gris, macro `ui.badge`) y, si hay perfil, un
  resumen corto de criterios ("Piso · Jaén · 2-3 dorm · ≤ 150.000 €").

## Flujo de creación (modal "Agregar alerta comprador", `alerts/list.html`)

- Nuevo control al inicio del bloque Propiedad: dos opciones tipo segmento
  **"Con referencia"** (por defecto) / **"Sin referencia"**. Patrón visual del
  par "Comprador existente / Nuevo comprador" que ya tiene el modal.
- "Sin referencia": se oculta el buscador de propiedad y `property_id` deja de
  ser `required`. Para el **admin** aparece el selector de agente (ya existe en
  el modal para la asignación; aquí pasa a ser obligatorio) con la nota "Sin
  propiedad, elige quién atiende al comprador". Para el **agente** una nota:
  "Se te asignará a ti". Operación (Venta/Alquiler) sigue obligatoria.
- Aviso de duplicado para búsquedas: al elegir comprador existente en modo "Sin
  referencia", consultar si ya tiene una búsqueda abierta con esa operación y
  mostrar el banner con enlace a esa alerta ("Ya tiene una búsqueda de Venta
  abierta: #123, 10/10"). Endpoint nuevo
  `GET /alerts/check-search-duplicate?buyer_id=&business_type=`.
- Ruta `create_alert`: `property_id: Optional[int] = Form(None)`. Rama sin
  propiedad: `origin='search'`, `company_id` = empresa activa, agente =
  elegido por admin (obligatorio; error claro si falta) o el propio agente;
  no se comprueban disponibilidad ni propiedad del inmueble; duplicado de
  búsqueda con `confirm_duplicate`. Rama con propiedad: como hoy, más
  `company_id = property.company_id`, `origin='property'`.
- **Eliminar** el botón "Agregar alerta con filtro", el modal
  `#filterAlertModal`, su JS (`openFilterAlertModal`, `setFcBuyerMode`, el
  autocompletado `fc*`) y la ruta `POST /buyers/create-with-criteria`. Los
  tests que la usaban (`tests/test_buyer_business_type.py`,
  `tests/test_buyer_phone_routes.py`) se reescriben con el flujo nuevo o se
  eliminan si solo probaban esa ruta. En la ficha del comprador se mantiene
  "Guardar perfil y ver compatibles" (el perfil también se edita desde ahí).

## Detalle de la alerta sin referencia (`alerts/detail.html`, `alert_detail`)

Diseño para el agente, móvil primero. Leer antes
`.claude/skills/moyza-ui-ux-pro/SKILL.md`, `references/components.md`,
`references/ux-rules.md`. Una sola acción primaria por paso.

- **Cabecera**: badge "Búsqueda general" + operación, en lugar del título de
  la propiedad. Datos del interesado como hoy (teléfono con `tel:` y WhatsApp).
- **Indicador de pasos** (3 pasos, estilo tabs/subrayado del sistema):
  1. **Contactar**: estado actual, botones de llamada/WhatsApp y el formulario
     de seguimiento habitual.
  2. **Perfil de búsqueda**: formulario inline (no modal) con: Zonas y Ciudades
     (checkboxes como el formulario actual, valores de la empresa), Tipo de
     inmueble, Operación (fija, viene de la alerta, se muestra como texto),
     Dormitorios mín./máx., Baños mín., Precio mín./máx., Imprescindibles
     (textarea). **Sin m².** Botón primario "Guardar perfil y ver propiedades".
     `POST /alerts/{id}/search-profile` → upsert de `BuyerSearchCriteria` +
     seguimiento automático `CALIFICADO` con nota resumen → redirige al paso 3.
     Solo el agente asignado (o admin) y nunca si la alerta está bloqueada.
  3. **Propuesta**: tarjetas de propiedades sugeridas (reutilizar el diseño de
     tarjeta de la ficha del comprador: título, dirección, dormitorios, baños,
     precio, agente de la propiedad; sin enlace "Ver" si la propiedad es de
     otro agente, igual que hoy). Botón por tarjeta **"Asociar a esta alerta"**
     (primario). Debajo, "¿No está en la lista?": buscador por título/dirección
     entre **todas** las disponibles de la empresa (nuevo parámetro
     `alert_id` en `/alerts/search-properties`: si la alerta es una búsqueda
     del agente, se devuelven todas las de la empresa; si no, se aplica la
     regla actual). Estado vacío si no hay coincidencias: sugerir ampliar
     precio o zonas, con enlace al paso 2.
- `POST /alerts/{id}/link-property` (`property_id`, `confirm_duplicate`):
  valida origen `search`, propiedad de la empresa y disponible, duplicado de
  comprador+propiedad; asigna `property_id`, `property_linked_at`, seguimiento
  `PROPIEDAD_ASOCIADA`; **no toca `agent_id`**. Flash de éxito. Si ya tenía
  propiedad, la nota es "Cambio de propiedad: de A a B".
- Con propiedad asociada, el detalle se ve como una alerta normal (tarjeta de
  propiedad) más un enlace discreto **"Cambiar propiedad"** (solo `origin ==
  'search'`, solo abierta, solo agente asignado o admin) que muestra el paso
  3 con el perfil editable.
- El **admin** ve lo mismo, con su bloque de asignación habitual.
- La alerta bloqueada sigue sin poder abrirse (regla del plan anterior).

## Perfil de búsqueda compartido

- Mover `_build_matching_properties` a un servicio reutilizable
  (`app/services/buyer_matching.py`), sin filtros de m², y usarlo desde la
  ficha del comprador y desde el detalle de la alerta. Orden: precio
  ascendente; propiedades disponibles y no archivadas de la empresa.
- Formulario del perfil: un **partial** compartido
  (`components/search_profile_form.html` o similar) usado por la ficha del
  comprador y por el detalle de la alerta, sin los campos de m².
- La ficha del comprador deja de mostrar los chips "≥ N m²".

## Documentación (decisión 6)

Crear `docs/DECISIONES_ALERTAS_BUSQUEDA.md` con:
- La decisión tomada (una alerta, el agente que atiende la conserva, cambio de
  propiedad permitido) y la fecha.
- La alternativa descartada por ahora: alerta nueva por propiedad, enlazada a
  la búsqueda; qué ganaría (varias propiedades a la vez, agente de la
  propiedad implicado, métricas por propiedad más limpias) y qué cambiaría en
  código (tabla de enlace o `parent_alert_id`, botón "Registrar interés",
  notificación al captador).
- **Implicaciones para analítica y contadores** con la decisión actual:
  `alert.agent_id` puede no coincidir con `property.agent_id`; las métricas
  por agente se quedan con quien atiende; las métricas por propiedad solo ven
  la alerta cuando está asociada y pueden "saltar" de propiedad si se cambia;
  qué consultas del dashboard, resultados comerciales e informes de desempeño
  se tocaron en este plan y cómo tratan las alertas sin propiedad.
- Qué columnas permiten cambiar de idea después (`origin`,
  `property_linked_at`, seguimientos `PROPIEDAD_ASOCIADA` con el historial de
  propiedades).
- Referenciar este archivo desde `PLAN_ASIGNACION_ALERTAS.md` (fila nueva en
  la tabla de reglas).

## Tests

Unitarios/en proceso con SQLite (patrón `tests/test_alerts_pagination.py`,
`tests/test_alert_view.py`):
- `scope_alerts` por `company_id` (una alerta sin propiedad de MOES no aparece
  en MOYZA).
- Crear sin referencia: admin sin agente → error; admin con agente → alerta
  `origin='search'`, `company_id` correcto, agente elegido; agente → asignada
  a sí mismo; aviso de búsqueda duplicada y confirmación.
- Guardar perfil desde la alerta: upsert del perfil, seguimiento `CALIFICADO`
  con nota, desbloquea la cola, agente ajeno rechazado, alerta bloqueada
  rechazada.
- Sugerencias: sin filtro de m²; solo empresa activa; incluye propiedades de
  otros agentes.
- Asociar propiedad: `property_id` y `property_linked_at`, seguimiento
  `PROPIEDAD_ASOCIADA`, `agent_id` intacto aunque la propiedad sea de otro;
  cambio de propiedad con nota "de A a B"; duplicado comprador+propiedad
  exige confirmación; alerta de origen `property` no puede cambiar.
- Render: listado y detalle muestran "Búsqueda general" sin propiedad; el
  detalle muestra los tres pasos y el formulario sin m²; con propiedad
  asociada muestra la tarjeta y "Cambiar propiedad".
- Migración: archivo presente, `down_revision = 'x7y8z9a0b1c2'`, `alembic
  upgrade x7y8z9a0b1c2:y8z9a0b1c2d3 --sql` genera el backfill y el `SET NOT NULL`.
- Reescribir/eliminar los tests de `create-with-criteria`.
- Suite completa: el conjunto de fallos no debe cambiar (fallo previo:
  `test_scheduler.py::test_check_automatic_reports_con_propiedad_activa`;
  errores de integración por falta de PostgreSQL).

## Verificación adicional

- `python -c "import app.main"`; compilar todas las plantillas tocadas.
- `bash backend/scripts/build_css.sh` y comprobar las clases nuevas en el CSS.
- `python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates`
  sin avisos nuevos (ejecutar también antes de empezar).
- Grep final: ningún `alert.property.` sin protección frente a `None` en
  Python ni en plantillas (`alert.property and …` o `if alert.property`).

## Entrega

Sin commits. **Sin ejecutar la migración.** Informe con: archivos tocados por
área; decisiones donde el plan dejaba margen; resultados de cada verificación
con números; pasos de prueba manual en producción (admin y agente, con el
flujo completo: crear sin referencia → abrir → perfil → sugerencias → asociar
→ cambiar); riesgos y deuda; y el recordatorio de `alembic upgrade head`.
Marcar "Estado".

## Estado

- [x] Migración y modelo (`company_id`, `origin`, `property_linked_at`, `property_id` nullable)
- [x] `scope_alerts` por empresa y auditoría de todos los usos de `alert.property`
- [x] Modal de creación: con/sin referencia; ruta `create_alert`; eliminación de "con filtro"
- [x] Detalle guiado: perfil (sin m²) + sugerencias + asociar/cambiar propiedad
- [x] Servicios compartidos (`buyer_matching`, partial del perfil) y ficha del comprador sin m²
- [x] Listados, notificaciones, dashboard, métricas con "Búsqueda general"
- [x] Tests
- [x] Documentación (`docs/DECISIONES_ALERTAS_BUSQUEDA.md`), lint, CSS

Migración creada y validada en offline (`--sql`), **sin ejecutar**: en
producción hace falta `alembic upgrade head` y reiniciar la app.

### Notas de implementación (2026-10-16)

Ninguna decisión de diseño del plan se ha cambiado. Donde el plan dejaba margen:

- `company_id` se rellena solo al crear una alerta con propiedad (`@validates`
  sobre `property` y, como red de seguridad, `before_insert` por `property_id`),
  para que ningún alta existente falle por el NOT NULL.
- Alta sin referencia: no llega `property_id` ⇒ búsqueda. El agente que manda
  otro `agent_id` recibe error (`resolve_search_assignee`). El admin puede
  elegir agente de cualquier empresa (se le da acceso, §4-1 B) y recibe el
  aviso `alert_assigned` ("Búsqueda general · {operación}").
- Pasos del detalle por `?step=contact|profile|proposal` (tabs subrayadas del
  sistema). Paso por defecto: Contactar si no hay gestión desde la asignación;
  Perfil si el comprador no tiene perfil; si no, Propuesta. Con propiedad
  asociada no salen los pasos salvo al pulsar "Cambiar propiedad".
- Sugerencias: mismo filtro que la ficha del comprador (estado Activa,
  disponible y con agente captador), por precio ascendente; en la alerta se
  pintan las 30 primeras con el total ("afina el perfil para ver otras").
- Duplicado al asociar: se resuelve en servidor (redirige a
  `?step=proposal&confirm_property=ID` con banner y "Asociar de todas formas").
  El enlace a la otra alerta solo se pinta si el usuario puede abrirla.
- Asociar valida empresa, disponibilidad (`estado_inmueble`) y que no esté
  archivada; asociar la misma propiedad que ya tiene es un aviso `info`.
- La ficha del comprador usa el partial del perfil (sin m²) y la tarjeta
  compartida `components/property_card.html`; guardar el perfil ya no toca
  `min_m2` / `max_m2` (se conservan).
