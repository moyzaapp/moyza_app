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
   empresa de la alerta primero. La cesión no cambia.

## 4. Fases

- **Fase A** — la configuración manda: quitar `add_to_company` de `assign`, migración de datos
  (ficha = usuario), tests.
- **Fase B** — listas por empresa y solo activos en Alertas, historial, ventana sin gestionar y
  Resultados; "contactos" por agente sin filtrar por empresa de la alerta, distintivo en la
  lupa; docs (`MULTIEMPRESA_MOYZA_MOES.md`, `PLAN_BAJA_USUARIOS.md` §4.4,
  `PLAN_ASIGNACION_ALERTAS.md` §4-1).

## 5. Estado

En ejecución con un agente Opus 5.5 high, un commit por fase.
