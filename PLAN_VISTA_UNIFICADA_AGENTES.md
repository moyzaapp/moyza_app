# Plan: vista unificada para agentes (sin cambiar de empresa)

Fecha: 2026-11-12. Rama `63-agregar-moes`. Petición: que un usuario agente no tenga que usar el
selector de empresa, salvo que así se configure en su usuario; que las alertas que se le asignan
(de cualquier empresa) salgan todas en la misma vista, y que en general el agente trabaje en
una sola sección sin cambiar de empresa.

## 1. Cómo está hoy

- **Toda la app trabaja con UNA empresa activa** (cookie `active_company`, resuelta en
  `app/web/dependencies/company.py`, `request.state.company`). Cada ruta filtra con
  `scope_*` / `get_*_in_company` de `company_scope.py` y lo de la otra empresa es "no
  encontrado". Usos de la empresa activa: alertas 31, visitas 16, propiedades 7, resultados 6,
  informes 5, agentes 5, clientes 4, notificaciones 3, inicio 1.
- **Alerta de la otra empresa asignada a un agente**: hoy la alerta conserva su empresa y el
  agente solo la ve si cambia de empresa. El listado `/alerts` le pone un banner "Tienes N
  compradores asignados en MOES PREMIUM. Cambia de empresa para atenderlos" con un botón.
- **Acceso a la otra empresa** (cambiado hoy en `ee09752`, otra sesión, "medida provisional"):
  las empresas que un agente puede ver son **solo las marcadas en su usuario** (pantalla
  Usuarios); las de su ficha de agente ya no cuentan. Asignarle una alerta de la otra empresa
  añade esa empresa a su ficha (`alert_assignment_service.assign`, `add_to_company`) para que el
  admin lo vea en Rendimiento de esa empresa, pero **no** le da acceso: si el admin no marcó la
  empresa en el usuario, el agente no puede abrir esa alerta ni ve el banner.
- Lo que es por empresa y afecta al agente: listado y detalle de alertas, cola secuencial
  (`get_locked_alert_ids` por empresa), compradores, propiedades (pestañas Mis / Resto / Otra
  empresa), visitas, Inicio (`DashboardService(company_id)`: KPIs, agenda, requiere atención,
  novedades), notificaciones (`Notification.company_id`), recordatorios por email (por agente y
  empresa), Resultados Comerciales (rendimiento, objetivos y snapshots por empresa), clientes e
  informes.
- Lo que crea el agente lleva la empresa activa: propiedad, comprador, alerta sin propiedad
  (búsqueda general), visita (hoy la de la propiedad), cliente.

## 2. Diseño propuesto

### 2.1 Ámbito del agente: "todas mis empresas"

- Nuevo concepto en `request.state`: `company_ids` (lista) además de `company`. Para el
  **admin** no cambia nada: sigue con el selector y una empresa activa. Para un **usuario
  agente** en vista unificada, `company_ids` = las empresas de su usuario **más** las de su
  ficha de agente (vuelve a contar la ficha: así una alerta asignada desde la otra empresa se ve
  sin que el admin tenga que tocar el usuario), y el selector del sidebar desaparece.
- `scope_*` y `get_*_in_company` aceptan un id o una lista (`IN`). Se cambia en un sitio y las
  rutas pasan `company_ids` en vez de `company.id`.
- **Opción por usuario**: campo nuevo `company_switch_enabled` en `users` (checkbox "Puede
  cambiar de empresa (vista por empresa)" en Editar usuario). Desmarcado (por defecto): vista
  unificada. Marcado: comportamiento de hoy, con selector. El admin siempre tiene selector.
- **Empresa principal** del usuario (`primary_company_id`, select en Editar usuario; por defecto
  la primera marcada): es la empresa con la que se crea lo que no tiene empresa derivable
  (propiedad nueva, comprador nuevo, alerta sin propiedad, visita, cliente) y la marca del
  sidebar. Si el agente está en dos empresas, esos formularios muestran un select de empresa
  con la principal preseleccionada; si está en una, no se pregunta.

### 2.2 Qué cambia en cada sección para el agente

| Sección | Hoy | Vista unificada |
|---|---|---|
| Alertas / Compradores | Solo empresa activa + banner "cambia de empresa" | Todas las asignadas a él, con distintivo de empresa (`ui.company_badge`) en la fila y en el detalle; el banner desaparece. Cola secuencial: bloqueos por empresa unidos. Cesión: agentes de la empresa de la alerta (igual que hoy). Alta: propiedad → su empresa; sin propiedad → empresa principal o select. |
| Inicio | KPIs, agenda y "requiere atención" de la empresa activa | Suma de sus empresas; filas con distintivo. Objetivos: ver pregunta 3. Novedades: notificaciones de todas sus empresas. |
| Notificaciones | Por empresa activa (campana, página, contador) | Todas sus empresas en una lista, con distintivo. |
| Recordatorios por email | Un correo por agente y empresa | Sin cambio (ya son por empresa, con la marca correcta). |
| Propiedades | Mis / Resto de propiedades / Propiedades de {otra} | Mis propiedades (todas sus empresas, con distintivo) / Resto por empresa (una pestaña por empresa, como ahora). La ficha `/properties/{id}` se abre si la propiedad es de alguna de sus empresas. Alta: select de empresa si está en dos. |
| Visitas | Empresa activa | Sus visitas de todas sus empresas (se diseña junto con PLAN_VISITAS_OTRA_EMPRESA.md: `company_id` en la visita = empresa principal o la elegida). |
| Resultados Comerciales (vista del agente) | Empresa activa | Ver pregunta 3: pestaña por empresa (recomendado) o suma. |
| Clientes, Informes | Empresa activa | Todas sus empresas con distintivo; alta con select de empresa si está en dos. |
| Sidebar | Logo y nombre de la empresa activa + selector | Logo y nombre de la empresa principal; sin selector (salvo opción por usuario). |

### 2.3 Lo que no cambia

- El admin: selector, empresa activa, Rendimiento, Evolución, Cierres, ventana de sin gestionar,
  reasignación, todo por empresa como hoy.
- `alert.company_id`, `buyer.company_id`, `property.company_id`: cada cosa sigue siendo de su
  empresa. Las métricas por empresa y los snapshots no se mezclan.
- Asignar una alerta de la otra empresa a un agente sigue añadiéndolo a la ficha de esa empresa
  (así el admin lo ve en Rendimiento de esa empresa); lo que ya **no** hace falta es que abra
  el selector ni que el admin marque la empresa en el usuario. Esto sustituye la medida
  provisional de `ee09752`.

## 3. Preguntas (con recomendación)

1. **A quién aplica**: recomendado, a todos los usuarios con rol agente por defecto, con la
   casilla "Puede cambiar de empresa" en Editar usuario para los que prefieran la vista por
   empresa. El admin sigue como hoy.
2. **Empresa de lo que crea el agente** (propiedad, comprador sin propiedad, visita, cliente):
   recomendado, "Empresa principal" del usuario (select en Editar usuario) y un select de
   empresa en el formulario solo si el agente está en dos empresas. Alternativa: preguntar
   siempre.
3. **Inicio y Resultados del agente con dos empresas**: recomendado, en Inicio se suman sus
   empresas (actividad, agenda, requiere atención) y los objetivos se muestran por empresa; en
   Resultados Comerciales (su propio rendimiento) una pestaña por empresa, porque objetivos y
   snapshots son por empresa. Alternativa: sumar todo también en Resultados.
4. **Orden con las visitas a la otra empresa**: recomendado, hacer primero las fases A y B de
   este plan (ámbito, usuario y alertas) y después PLAN_VISITAS_OTRA_EMPRESA.md ya sobre la
   vista unificada, para no hacer el selector de visitas dos veces.

## 4. Fases

- **Fase A — base**: `company_ids` en `request.state`, `scope_*` con lista, campos
  `company_switch_enabled` y `primary_company_id` en `users` (migración), Editar usuario,
  sidebar sin selector para agentes, `get_allowed_companies` con ficha de agente. Tests.
- **Fase B — alertas y compradores**: listado, detalle, seguimientos, cola, cesión, buscador,
  alta con empresa, distintivos; quitar el banner "cambia de empresa".
- **Fase C — Inicio y notificaciones**: `DashboardService` por lista de empresas para el agente,
  novedades y campana unificadas.
- **Fase D — propiedades, clientes e informes**: listados, ficha, alta con select de empresa.
- **Fase E — visitas**: ejecutar PLAN_VISITAS_OTRA_EMPRESA.md sobre la base nueva.
- **Fase F — Resultados del agente**, docs (MULTIEMPRESA_MOYZA_MOES.md §2 y §16) y pruebas
  de rutas, móvil y regresión del admin.

## 5. Decisiones (respuestas del usuario, 2026-11-12: "lo recomendado")

1. Todos los usuarios con rol agente en vista unificada por defecto; casilla "Puede cambiar de
   empresa" en Editar usuario para la vista por empresa. El admin, como hoy.
2. Empresa principal del usuario para lo que crea; select de empresa en el formulario solo si
   está en dos empresas.
3. **Métricas del agente: se suma todo** (apunte del usuario: "las métricas de cada agente
   deben sumarse todo"). En Inicio y en Resultados Comerciales (vista del agente) los
   indicadores y los objetivos son la suma de sus empresas; sin pestaña por empresa. Las
   métricas del admin siguen por empresa.
4. Orden: fases A y B primero, después las visitas (PLAN_VISITAS_OTRA_EMPRESA.md) y el resto.

## 6. Estado

En ejecución con agentes Opus 5.5 high, un commit por fase.

- **Fase A — hecha** (`8eed19f`): migración `f2u3v4i5e6w7` (`users.company_switch_enabled`,
  `users.primary_company_id`), `request.state.company_ids` / `unified_view`, `scope_*` con
  lista, sidebar sin selector, Editar usuario y alta con "Puede cambiar de empresa" y
  "Empresa principal", `get_allowed_companies` con la ficha de agente.
- **Fase B — hecha** (commit "feat(alertas): listado y detalle unificados para agentes de
  varias empresas", el siguiente a `8eed19f`): listado, contadores, compradores, detalle,
  seguimientos, Propuesta, cola, cesión, buscadores, altas con empresa y distintivos; sin
  el banner "cambia de empresa" en la vista unificada.
- **Fase C — hecha** (`f55c8d5`): Inicio del agente con la suma de sus empresas
  (métricas, objetivos, agenda, compradores, cartera, tendencia) y notificaciones de todas
  (campana, contador, página, Novedades) con distintivo.
- **Fase D — hecha** (commit "feat(propiedades): listados, ficha y alta con empresa para
  agentes de varias empresas", el siguiente a `f55c8d5`): "Mis propiedades" de todas sus
  empresas, "Resto de {empresa}" por empresa, edición de las de cualquier empresa del
  agente, clientes, informes y logs de informes por lista.
- Pendiente: fases E (visitas) y F (Resultados del agente, docs de MULTIEMPRESA_MOYZA_MOES.md
  §2 y §16).

### 6.1 Decisiones de implementación (donde el plan no era explícito)

**Fase A**

- `company_ids` en la vista unificada = todas las empresas permitidas (usuario + ficha),
  también si es una sola. Con una sola no hay distintivos ni select de empresa
  (`show_company_badges` = vista unificada y más de una empresa).
- El admin ignora `company_switch_enabled` y la empresa principal: siempre selector.
- `resolve_company_for_api` sigue el mismo criterio que el middleware (en la vista
  unificada, la principal): las rutas `/api/*` y las páginas ven la misma empresa activa.
  `resolve_company_ids_for_api` da los `company_ids`.
- `/switch-company` en la vista unificada: redirige (303) con un aviso informativo "Ya ves
  todas tus empresas a la vez" y no toca la cookie.
- Empresa principal: si no se elige, se guarda la primera marcada (menor id); una que no
  esté entre las marcadas es un error del formulario. La migración rellena la de los
  usuarios existentes con la primera de `user_companies` (así un usuario solo de MOES, con
  ficha en las dos, conserva la marca MOES). Si la guardada deja de estar entre las
  permitidas, cuenta la primera permitida (MOYZA por defecto).
- En Editar usuario y en el alta, el bloque se oculta si el rol elegido es admin (sus
  valores se envían igual y no cuentan para él).

**Fase B**

- Todo lo que lee alertas y compradores usa `get_company_ids(request)` (para el admin es
  `[activa]`, así que no se distingue rol). Las acciones que derivan la empresa de la
  alerta (cola, cesión, duplicados al asociar, notificaciones) siguen con
  `alert.company_id`.
- Alta de alerta: con propiedad, la empresa de la propiedad (cualquiera de las del
  usuario); un comprador existente de otra empresa que la propiedad da error ("asóciala
  desde la Propuesta de su alerta"); comprador nuevo, a la empresa de la alerta. Sin
  propiedad: con comprador existente, la del comprador; con comprador nuevo, el select
  "Empresa" (solo visible en esa combinación, principal preseleccionada, validado contra
  `company_ids`). "Nuevo comprador" lleva el mismo select. El admin no ve el select y no
  puede crear fuera de la activa.
- Avisos de duplicado del alta (`check-duplicate`, `check-search-duplicate`): en la empresa
  del comprador. `check-buyer` busca en todas las empresas del usuario; la red de seguridad
  del servidor, en la empresa de la alerta.
- Propuesta: el filtro "Solo {empresa}", el desglose y el distintivo de las tarjetas son
  respecto a la empresa de la alerta; el "Ver" de una propiedad, si es de alguna empresa
  del usuario (`link_company_ids`); en la vista unificada no sale "Cambia de empresa para
  ver la ficha". En el listado, el distintivo de la propiedad sale si no es de la empresa
  de la alerta (para el admin es lo mismo que "no es de la activa").
- Ficha del comprador: su empresa hace de "activa" (agente responsable, distintivos,
  "Crear alerta" solo con propiedades de su empresa); "Ver" con `link_company_ids`.
- Cesión desde el listado: un grupo de agentes por cada empresa con filas cedibles; el JS
  (`AlertAssign.setCompany`) deja elegir solo los de la empresa de la fila. En el detalle,
  `assign_fields(..., company=alert.company)`.
- Contador del sidebar (`/api/alerts/unread-count`): suma de las empresas del usuario.
- Mínimo fuera de alertas: `/properties/{id}` y sus acciones de actividad e informe buscan
  la propiedad en `company_ids`, para que el "Ver" de las alertas abra la ficha de una
  propiedad de otra empresa del agente. El listado, la edición y el resto de propiedades
  siguen con la empresa activa (fase D). Inicio, notificaciones, visitas y resultados
  reciben la empresa principal y funcionan como antes (fases C, E y F).

**Fase C**

- `DashboardService(db, company_id)` acepta un id o una lista. Con varias empresas
  (`is_multi`), métricas y objetivos se calculan **por empresa** (cada una con su criterio:
  vivo o snapshot congelado) y se suman con `sum_metrics` / `sum_targets`
  (`performance_report_service`, para reutilizarlos en la fase F). Un desglose que es
  None en todas sigue None; si falta en alguna cuenta 0. Objetivo: suma de los de cada
  empresa; si solo hay en una, ese; "Sin objetivos" solo si no hay en ninguna.
- Puesto ("Puesto N de M"): entre los agentes activos de cualquiera de sus empresas, cada
  uno con sus cifras y objetivos sumados en esas empresas.
- Observaciones del admin: una por empresa en el snapshot; con varias se unen con el
  nombre de la empresa delante ("MOYZA: …").
- Agenda, "sin leer", "sin respuesta", compradores que requieren atención (una consulta
  sin empresa filtrada por las suyas), cartera y tendencia leen de todas; la cola sigue
  por empresa (unión de bloqueos). Distintivo en filas de agenda, ventana de compradores y
  propiedades sin visitas; cabecera "MOYZA y MOES PREMIUM · fecha".
- El Inicio del admin sigue con `DashboardService(db, company.id)`; `admin_home` usa
  `company_id` (una empresa). "Sin ficha de agente" mira todas las empresas del usuario.
- Notificaciones: lectura por `company_ids` (`_scoped` con `company_match`); las `/api/*`
  con `resolve_user_company_scope`. Distintivo (`serialize(with_company=True)`, relación
  `Notification.company`) solo si vista unificada con más de una empresa; la campana lo
  pinta en JS con el mismo HTML que `ui.company_badge`. Crear notificaciones no cambia.

**Fase D**

- Pestañas de Propiedades del agente unificado en MOYZA y MOES: "Mis propiedades" (las
  suyas de las dos, distintivo en la fila) / "Resto de MOYZA" / "Resto de MOES PREMIUM" /
  "Consultar teléfono". Sin "Propiedades de {otra empresa}": las dos son suyas, así que
  su inventario sale como "Resto" (con calle, sin propietario, como el resto de su
  empresa) y no se repite. "Propiedades de {X}" queda solo para empresas fuera de sus
  `company_ids` (el admin y la vista por empresa: igual que antes). URL
  `?tab=others&company_id=N`; sin empresa, la primera. Con una sola empresa, "Resto de
  propiedades" como siempre.
- "Consultar teléfono" busca en todas sus empresas (el texto ya decía "MOYZA y MOES
  PREMIUM" y cada resultado lleva su distintivo).
- Edición: la propiedad se busca en `company_ids` (antes fallaba la de la empresa que no
  es la principal); cliente y captador se validan contra la **empresa de la propiedad**
  (editar no cambia de empresa). El formulario carga clientes y agentes de todas sus
  empresas con `data-companies` y, al editar, `filterCompanyOptions(companyId)` (del
  `data-company-id` del botón Editar) solo deja elegir los de esa empresa.
- **Alta**: crear propiedades y clientes es solo del admin (`deny_if_not_admin`, desde
  antes de este plan), que sigue con la empresa activa. Por eso no hay select de empresa
  en esos formularios: un agente no llega a verlos. Si algún día se abre el alta a
  agentes, hará falta el select (principal preseleccionada, validado contra
  `company_ids`) y filtrar cliente y captador por la empresa elegida con
  `filterCompanyOptions`.
- Clientes: listado por `company_ids` (solo los clientes de sus propiedades), distintivo
  junto a cada inmueble. Editar y quitar, del admin en la activa.
- Informes (`/reports`, subir, descargar, borrar, enviar) y logs de informes (página y
  `/api/*`) por `company_ids`; el informe hereda la empresa de su propiedad. Distintivo
  en el listado y empresa en el select de subir.
- `routes/agents.py` es del admin salvo editar el propio perfil y la firma: esos dos
  buscan la ficha en `company_ids` (antes, en la principal; fallaba si la ficha no
  estaba en ella). El listado sigue igual.
- `test_other_company_address.py::test_agente_de_las_dos_empresas_ve_la_calle` pasa a
  mirar "Resto de MOES PREMIUM" (consecuencia directa de las pestañas nuevas).
- Visitas sin tocar (fase E): `/visits` funciona (empresa principal), pero "Registrar
  visita" desde la ficha de una propiedad de la empresa que no es la principal redirige a
  `/properties`.
