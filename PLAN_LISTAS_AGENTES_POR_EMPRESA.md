# Plan: listas de agentes por empresa y sin dados de baja

Fecha: 2026-11-18. Rama `63-agregar-moes`. Petición del admin: en el filtro de agentes de
Alertas y en Resultados Comerciales solo deben salir los agentes de la empresa activa; los dados
de baja no deben salir en ninguna lista; la lista "Agente asignado" del alta de alerta agrupa
"MOYZA" / "MOYZA, MOES PREMIUM" / "MOES PREMIUM" y debería seguir la configuración del usuario;
al reasignar deben salir todos los agentes de las dos empresas.

## 1. Cómo está hoy y por qué pasa

- **Dos pertenencias distintas.** El usuario tiene sus empresas en la pantalla Usuarios
  (`user_companies`) y la ficha de agente tiene las suyas (`agent_companies`). Al guardar el
  usuario, la ficha copia las del usuario. Pero **asignar o reasignar una alerta de la otra
  empresa añade esa empresa a la ficha** (`alert_assignment_service.assign` →
  `add_to_company`, decisión §4-1 B de PLAN_ASIGNACION_ALERTAS.md) sin tocar al usuario.
- En el entorno local se ve el efecto: "Administracion Moyza Agente" (ficha MOYZA + MOES,
  usuario solo MOYZA) y "Agente Moes" (ficha MOES + MOYZA, usuario solo MOES).
- Consecuencias:
  - **Resultados Comerciales de MOES** lista a un agente de MOYZA (y al revés), porque las
    pestañas usan las empresas de la ficha (`scope_agents` / `scope_active_agents`).
  - **"Agente asignado" del alta** (`assignable_agents` → `companion_agent_groups`) agrupa por
    el conjunto de empresas de la ficha: por eso aparece el grupo "MOYZA, MOES PREMIUM" con
    agentes cuyo usuario está en una sola empresa.
  - El filtro de agentes de Alertas sí es de la empresa activa, pero por la misma razón incluye
    a quien fue añadido a la ficha por una asignación.
- **Dados de baja.** Por decisión de PLAN_BAJA_USUARIOS.md §4.4, los filtros e historiales
  muestran a los inactivos con "(baja)" para poder ver sus alertas cerradas; solo los selectores
  que dan trabajo nuevo los ocultan. Hoy salen con "(baja)" o badge "Baja" en: filtro de agentes
  de Alertas, filtro del historial de asignaciones, Resultados (Compradores, Rendimiento,
  select de Evolución) y la pestaña Cierres (en los registros).
- **Reasignar** ya ofrece todos los agentes activos de las dos empresas (`assignable_agents`),
  agrupados por empresas de la ficha.

## 2. Diseño propuesto

1. **La configuración del usuario manda.** Asignar una alerta de la otra empresa deja de añadir
   la empresa a la ficha del agente (se quita `add_to_company` de `assign`; la vista unificada
   ya le enseña la alerta sin eso). Migración de datos: para cada ficha con usuario, las
   empresas de la ficha pasan a ser exactamente las del usuario; las fichas sin usuario no se
   tocan. Con eso, las listas por empresa y la agrupación del alta quedan bien solas.
2. **Listas por empresa, solo activos** (empresa activa del admin): filtro de agentes de
   Alertas, filtro del historial de asignaciones, Resultados Comerciales (Compradores,
   Rendimiento, Evolución, Cierres: select del alta ya es de activos) y selector de agente de la
   ventana "sin gestionar". La pantalla Agentes conserva su botón "Ver dados de baja" para
   poder reactivar.
3. **Alta de alerta y reasignación**: todos los agentes activos de las dos empresas, agrupados
   "MOYZA" / "MOES PREMIUM" / "MOYZA, MOES PREMIUM" (este último solo con usuarios
   configurados en ambas), con los de la empresa de la alerta primero. Igual para cesión no
   cambia (agentes de la empresa de la alerta).

## 3. Decisiones (usuario, 2026-11-18)

Principio del usuario: "un agente puede recibir alertas de cualquier propiedad, y eso solo
afecta al rendimiento del agente; las listas de agentes muestran lo que manda la configuración
del usuario".

1. **Las listas de agentes salen de la configuración del usuario** (pantalla Usuarios), en
   todas las pantallas del admin. La ficha de agente se iguala a su usuario (migración de datos
   dentro de `alembic upgrade head`, con log de las fichas que cambian) y asignar una alerta
   deja de ampliarla.
2. **Una alerta de cualquier empresa cuenta para el agente que la lleva, bajo su empresa.** El
   indicador "contactos" (y cualquier otro que salga de alertas o seguimientos) se calcula por
   agente **sin filtrar por la empresa de la alerta**: en Rendimiento y Evolución de MOYZA, un
   agente de MOYZA suma también lo que gestione en alertas de MOES, y el total del equipo
   también. La lupa muestra la alerta con el distintivo de su empresa cuando no es la activa.
   Captaciones y bajadas siguen por empresa de la propiedad; cierres por empresa del cierre;
   hojas de visita por empresa de la visita (ya es así). Los snapshots congelados no se
   recalculan (si un período congelado se refresca, lleva la regla nueva).
   Pestaña Compradores de Resultados: filas por agente de la empresa; los totales de alertas
   de la empresa incluyen todas las alertas, también las asignadas a agentes de fuera.
3. **Dados de baja: fuera de todos los filtros y selects.** Filtro de agentes de Alertas, filtro
   del historial de asignaciones, Evolución, ventana "sin gestionar", Rendimiento. En un período
   congelado, la fila histórica de un agente de baja se mantiene con el badge "Baja" (dato
   cerrado). La pantalla Agentes conserva "Ver dados de baja" para reactivar. Las alertas
   cerradas de un agente de baja se encuentran por texto o desde el comprador.
4. **Alta y reasignación**: todos los agentes activos de las dos empresas agrupados "MOYZA" /
   "MOES PREMIUM" / "MOYZA, MOES PREMIUM" (solo usuarios configurados en ambas), con los de la
   empresa de la alerta primero. La cesión no cambia. Vale también para la baja (2026-11-24,
   `PLAN_BAJA_DESTINOS_TODAS_EMPRESAS.md`): modal de baja y "Repartir compradores".

## 4. Fases

- **Fase A** — la configuración manda: quitar `add_to_company` de `assign`, migración de datos
  (ficha = usuario), tests.
- **Fase B** — listas por empresa y solo activos en Alertas, historial, ventana sin gestionar y
  Resultados; "contactos" por agente sin filtrar por empresa de la alerta, distintivo en la
  lupa; docs (`MULTIEMPRESA_MOYZA_MOES.md`, `PLAN_BAJA_USUARIOS.md` §4.4,
  `PLAN_ASIGNACION_ALERTAS.md` §4-1).

## 5. Estado

Terminado (2026-11-18), con un agente Opus 5.5 high, un commit por fase.

- **Fase A — hecha** (`2947674`, "feat(agentes): la ficha de agente sigue a su usuario;
  asignar una alerta ya no amplía sus empresas"): `assign` sin `add_to_company` ni
  `granted_company`; flashes y aviso del formulario sin "acceso"; migración de datos
  `l8s9x0y1z2a3_agent_companies_follow_user` (solo SQL, función `sync_agent_companies(conn)`
  probada cargando el módulo de la migración, como `b1c2d3e4f5a6`); downgrade no-op.
  En local cambió las fichas 6 (solo el texto `company`), 12 (MOYZA + MOES → MOYZA), 15
  (MOYZA + MOES → MOES PREMIUM) y la de demostración 26569; la 1 (sin usuario), intacta.
- **Fase B — hecha** (el commit siguiente a `2947674`, "feat(listas): agentes de la empresa
  según su usuario, sin dados de baja; contactos por agente sin filtrar por empresa de la
  alerta"): listas, contactos por agente, migración `m9t0y1z2a3b4`, docs y tests.

Decisiones de implementación (donde el plan no era explícito):

1. **Ver la alerta sin ampliar la ficha.** El plan daba por hecho que la vista unificada ya
   enseñaba al agente una alerta de otra empresa, pero `company_ids` salía de usuario +
   ficha: sin la ampliación, un agente de MOES con una alerta de MOYZA dejaba de verla (en
   local, la ficha 12 tenía alertas abiertas de MOES). `get_allowed_companies` suma ahora
   las empresas de las alertas que lleva (todas, abiertas o cerradas, como hacía la ficha).
   Es el mismo acceso que daba la ampliación, sin tocar la ficha ni las listas.
2. **Contactos una sola vez en el Inicio del agente.** "Contactos" es el único indicador
   que sale de alertas (`AGENT_WIDE_INDICATORS`); en vivo ya no filtra por empresa, así
   que calcular por empresa y sumar lo duplicaba. `team_metrics` con varias empresas usa
   `sum_company_metrics`: suma todo salvo los contactos, que se toman una vez. Para los
   snapshots, que no se recalculan, la columna `agent_performance_reports.contacts_all_companies`
   (False en los existentes, True al congelar desde ahora) dice si ya traen los de todas
   las empresas: si alguna parte es un snapshot nuevo, manda (el mayor); si no, el vivo;
   si todas son antiguas, se suman como antes. La tendencia semanal es una sola consulta
   por agente (sin duplicar). Cubierto en `tests/test_agent_lists_by_company.py`.
3. **Rendimiento en un período pasado**: activos de la empresa más los dados de baja de la
   empresa con snapshot congelado **o** con algún dato de ese período (un agente dado de
   baja a mitad de mes no tiene snapshot y su actividad desaparecería). Período en curso:
   solo activos. Evolución: solo activos (el plan la lista entre los selects sin bajas).
4. **Agente fuera del select**: un `agent_id` de un dado de baja o de un agente de otra
   empresa sigue filtrando en Alertas y en el historial y se ve como chip quitable con
   "· dado de baja" o "· de {empresas}"; enviar el formulario de filtros lo quita.
5. **Ventana "sin gestionar"**: lista alertas de la empresa por agente; un agente activo de
   otra empresa con alertas de esta sale con su nombre y "Agente de {empresas}" (antes,
   "Sin agente"), porque las alertas son de la empresa y hay que poder reasignarlas; los
   dados de baja, fuera. La reasignación ofrece todos los activos de las dos empresas.
6. **"Última actividad"** del Inicio del admin (aviso de agentes sin actividad): los
   seguimientos y lecturas cuentan en sus alertas de cualquier empresa; las visitas, por
   empresa de la visita.
7. **Lupa de contactos**: una alerta de otra empresa lleva `ui.company_badge` ("Alerta de
   {empresa}") y no enlaza (no se abre desde la empresa activa); su propiedad tampoco. CSV
   con la columna "Empresa" en todas las filas.
8. **Compradores** muestra las filas de agentes activos de la empresa; un agente de otra
   empresa con alertas de esta suma en los totales, no en las filas. Cierres no cambia
   (su select ya era de activos; los registros conservan "(de baja)").

Pendiente o fuera de alcance: la pantalla Agentes sigue permitiendo marcar empresas en la
ficha a mano (puede volver a separarse del usuario hasta que se guarde el usuario); el
filtro de agentes de los logs de informes (`routes/report_logs.py`) sigue con todos.
