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
