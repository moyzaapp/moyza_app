# Plan: al dar de baja, reasignar a agentes de cualquier empresa

Fecha: 2026-11-24. Continuación de `PLAN_BAJA_USUARIOS.md` y de
`PLAN_LISTAS_AGENTES_POR_EMPRESA.md` (§3-4).

## 1. Problema

Al dar de baja a un usuario (modal de Usuarios) o repartir sus compradores
(`/agents/{id}/handover`), la lista de destino por empresa sale de
`offboarding_service._targets`, que solo devuelve agentes activos **de esa
empresa** (`scope_active_agents`). La confirmación (`deactivate` y
`handover_reassign`) vuelve a exigir lo mismo y rechaza cualquier otro agente
con «no es un agente activo de esa empresa».

El «Reasignar» normal de Compradores usa desde el 2026-11-18 la lista de
todos los agentes activos de las empresas activas agrupados por empresa
(`alert_assignment_service.assignable_agents` → `visit_agents.companion_agent_groups`),
con los de la empresa de la alerta primero, y valida con
`get_agent_in_any_company`. La baja se quedó con la regla antigua.

## 2. Decisiones (usuario, 2026-11-24)

- **D1** La baja usa la misma lista que «Reasignar»: todos los agentes activos
  con alguna empresa activa, agrupados «MOYZA» / «MOES PREMIUM» /
  «MOYZA, MOES PREMIUM», primero los grupos que incluyen la empresa de las
  alertas, sin el agente que se va. Vale para el modal de Usuarios y para
  «Repartir compradores».
- **D2** La validación del servidor acepta cualquier agente activo con alguna
  empresa activa distinto del saliente (`get_agent_in_any_company`). La alerta
  conserva su `company_id`; asignar no amplía las empresas del agente.
- **D3** En «Repartir compradores», el nº de abiertos junto a cada agente es
  su total de alertas abiertas **en todas las empresas** (carga real).
- **D4** Textos: el error pasa a «El agente elegido no existe o está dado de
  baja»; la ayuda bajo el select de reparto pasa a «Junto a cada agente, los
  compradores abiertos que ya tiene (todas las empresas)».

## 3. Diseño

### 3.1 Servicio (`app/services/offboarding_service.py`)

- `_targets(db, company_id, agent_id)` → `_target_groups(db, company_id, agent_id) -> list[dict]`:
  `companion_agent_groups(db, company_id)` (de `app.services.visit_agents`)
  quitando `agent_id` de cada grupo y descartando grupos vacíos. Formato
  `[{"label": str, "agents": [Agent, ...]}, ...]`.
- `CompanyPending.targets: list[dict]` (grupos). `summary_to_dict` serializa
  `"targets": [{"label": ..., "agents": [{"id", "name"}, ...]}, ...]`.
- `HandoverGroup.targets: list[dict]` con `{"label", "agents": [HandoverTarget, ...]}`;
  la carga `load` se calcula sin filtrar por `company_id` (D3), con los ids de
  todos los grupos.
- Validación en `deactivate` y `handover_reassign`: sustituir la consulta
  `scope_active_agents(...).filter(Agent.id == target_id, Agent.id != leaving.id)`
  por `visit_agents.get_agent_in_any_company(db, target_id)` y comprobar
  `target.id != leaving.id`; mensaje D4. Mantener el resto (todo o nada,
  `validate_reassignment`, `assign`, flash).
- Comentarios/docstrings de `CompanyPending`, `HandoverGroup` y §4.2 del
  código que digan «activos de esa empresa» se actualizan.

### 3.2 Modal de baja (`app/web/templates/components/deactivate_modal.html`)

El JS (≈líneas 132–175) recorre `company.targets` como lista plana. Pasa a
recorrer grupos y crear `<optgroup label=...>` con sus `<option>`. Si en total
solo hay un agente, se preselecciona como hoy. Si no hay ninguno, el mensaje
actual de «sin destino» se mantiene.

### 3.3 Repartir compradores (`app/web/templates/agents/handover.html`)

Select con `<optgroup>` por grupo (≈línea 152); opción
`Nombre · N abiertos` como hoy. Texto de ayuda según D4. Sin JS nuevo
(`data-handover-submit` sigue habilitándose igual).

### 3.4 Tests

- `tests/test_offboarding_service.py`:
  - `test_destino_ausente_inactivo_otra_empresa_o_el_propio`: ahora un agente
    de MOES **sí** está entre los destinos de MOYZA y la baja con
    `{moyza: ok_moes.id}` reasigna; siguen rechazados el inactivo, el propio,
    un id inexistente y el ausente. Renombrar a lo que describa.
  - `test_summary_to_dict`: nuevo formato de `targets` (grupos con `label` y
    `agents`), agente saliente fuera, grupo de la empresa primero.
  - Nuevo: `_target_groups` excluye al saliente y no devuelve grupos vacíos.
- `tests/test_offboarding_handover.py`: la carga por agente suma todas las
  empresas (un destino con una alerta abierta en MOES aparece con 1 en el
  grupo de MOYZA); reasignar a un agente de otra empresa funciona y la alerta
  conserva su empresa.
- `tests/test_offboarding_routes.py` (≈línea 272): adaptar la lectura de
  `targets` al formato por grupos; el HTML de `/agents/{id}/handover` tiene
  `<optgroup label="MOES PREMIUM">` cuando hay agentes de MOES.

### 3.5 Documentación

- `PLAN_BAJA_USUARIOS.md`: nota en «Estado» (o §4.2) remitiendo aquí: los
  destinos ya no se limitan a la empresa.
- `PLAN_LISTAS_AGENTES_POR_EMPRESA.md` §3-4: añadir «y la baja (2026-11-24)».

## 4. Fases

1. Servicio + dos plantillas + tests + docs (un agente).
2. Revisión del diff, suite completa y smoke (modal de baja y reparto con
   los datos demo).

### Estado

- [x] Fase 1 (2026-11-24): `_target_groups` + `_get_target` en el servicio, `<optgroup>` en
  modal y reparto, tests y notas de §3.5. Desviaciones: el error de `deactivate` conserva la
  empresa («El agente elegido para MOYZA no existe o está dado de baja»; en el reparto, el
  texto exacto de D4); el aviso «sin destino» ya no nombra la empresa («No hay ningún otro
  agente activo que pueda recibir sus compradores…»), porque mira todas.
- [x] Fase 2 (2026-11-24): revisión sin defectos (validación con `get_agent_in_any_company` en
      los dos caminos, todo o nada intacto, formato JSON/JS coincidente, «Reasignar» y cesión sin
      cambios). Suite completa 1419 pasan (dos fallos ajenos deseleccionados). Smoke con datos
      demo como admin: baja de Carlos Ruiz (MOYZA) lista los otros 10 agentes en tres grupos,
      él excluido, y el reparto muestra la carga total de cada uno.

## 5. Fuera de alcance

- Cambiar las empresas del agente al recibir alertas (sigue sin ampliarse).
- La cesión entre agentes (sigue limitada a la empresa de la alerta).
