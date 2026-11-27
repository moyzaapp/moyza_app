# Plan: cierres con agentes de cualquiera de las dos inmobiliarias

Fecha: 2026-11-27. Rama `63-agregar-moes`. Continuación de `PLAN_CIERRES_DOS_AGENTES.md`.

## 1. Problema

En Resultados Comerciales → Cierres, «Registrar cierre» solo ofrece los agentes activos de la
empresa activa (`closings_context`, `closing_agents = scope_active_agents(...)`) y
`closing_service.create_closing` rechaza cualquier otro («Elige un agente activo de la
empresa»). No se puede registrar un cierre entre un comercial de MOYZA y uno de MOES PREMIUM.

Abrir solo el select no basta: cada registro de `closings` lleva `company_id` (hoy siempre la
empresa activa) y la métrica, Rendimiento, la pestaña Cierres, la lupa, los snapshots y la
actividad del Inicio filtran por esa empresa. Un agente que solo está en MOES con un registro
de empresa MOYZA no cuenta en ningún sitio (no está en los agentes de MOYZA y el filtro de
MOES no ve el registro).

## 2. Decisiones (usuario, 2026-11-27: «lo recomendado»)

- **D1** Los dos selects (Agente 1 y Agente 2) ofrecen los agentes activos de todas las
  empresas activas, agrupados por empresa como el acompañante de visitas
  (`visit_agents.companion_agent_groups`).
- **D2** Cada registro se guarda con la **empresa de su agente**: la activa si el agente
  pertenece a ella; si no, la empresa activa (`Company.is_active`) del agente con menor id.
  Así cada agente suma 1 cierre en su empresa y lo ve en su Inicio; el equipo de cada empresa
  suma los suyos.
- **D3** Un cierre compartido entre empresas aparece en la pestaña Cierres de **las dos**
  empresas, cada una con su registro como fila «compartida» y «con {Nombre}» del otro (ya
  resuelve el nombre por `shared_with_agent`). Se indica la empresa del otro agente cuando no
  es la activa: «con Nombre (MOES PREMIUM)».
- **D4** Borrar desde cualquiera de las dos pestañas elimina los dos registros (la pareja se
  busca por `pair_key` sin filtrar por empresa; la autorización es sobre el registro pulsado,
  que debe ser de la empresa activa).
- **D5** La propiedad opcional sigue siendo de la empresa activa. El enlace a la propiedad en
  la pestaña de la otra empresa: comprobar que el admin la abre (es admin de las dos); si no,
  mostrar solo el texto.
- Sin migración: el modelo no cambia. Los cierres existentes no se tocan.

## 3. Diseño

### 3.1 Servicio (`app/services/closing_service.py`)

- `create_closing(db, company_id, agent_ids, ...)`:
  - Validar los agentes con `visit_agents.get_agent_in_any_company` (activos, de alguna
    empresa activa) en lugar de `scope_active_agents(company_id)`. Mensaje de error: «Elige un
    agente activo».
  - `company_for(agent)` (D2): `company_id` si `company_id in {c.id for c in agent.companies}`,
    si no la empresa activa del agente con menor id. Cada `Closing` lleva la suya.
  - `_refresh_snapshots`: un `PerformanceReportService(db, row.company_id)` por registro.
- `delete_closing(db, company_id, closing_id)`: el registro pulsado debe ser de `company_id`;
  la pareja por `pair_key` **sin** filtro de empresa (D4); refrescar snapshots con la empresa
  de cada registro.

### 3.2 Ruta y pestaña (`app/web/routes/commercial_results.py`)

- `closings_context`: `closing_agent_groups = companion_agent_groups(db, company_id)` (lista de
  `{"label", "agents"}`), en lugar de `closing_agents`. Mantener `closing_agents` solo si lo usa
  algo más (comprobar); si no, retirarlo. Aviso de «No hay agentes activos» solo si no hay
  ningún grupo.
- `closing_operations` / contexto: para cada operación, `partner_company` = nombre de la
  empresa del otro agente si no pertenece a la activa (para D3). Los nombres de empresa:
  `Company` activas (una consulta).
- Mensajes de error de la ruta: «Elige un agente activo» (sin «de la empresa»).
- `metric_detail` (lupa) no cambia: la lupa de un agente es dentro de su empresa.

### 3.3 Plantilla (`commercial_results/_closings.html`)

- Los dos selects con `<optgroup label="{{ group.label }}">` como `visits/agents_fields.html`.
  El JS que evita repetir el mismo agente ya recorre `options` (funciona con optgroups).
- Texto de ayuda de Agente 2: «Puede ser un agente de cualquier empresa». Lo mismo, breve, en
  Agente 1 o en la cabecera del modal.
- Fila del listado: «con {Nombre} ({empresa})» cuando `partner_company` no es la activa.
- Usar el skill `moyza-ui-ux-pro` para clases y componentes (Tailwind compilado: solo clases
  existentes en `static/css/tailwind.css`).

### 3.4 Inicio (`dashboard_service`, actividad reciente)

- Ya filtra por `Closing.company_id == self.company_id` y agrupa por `pair_key`: cada empresa
  ve su registro; el evento muestra «Ana y Bea» por `agent`/`shared_with_agent`. Comprobar que
  con una sola mitad visible el texto sigue saliendo bien (nombre del otro por
  `shared_with_agent`). Sin cambios salvo que falle.

### 3.5 Tests

- `tests/test_closing_service.py`: `[ana, mia]` (MOYZA + MOES) ya **no** se rechaza; crea dos
  registros con `company_id` distintos (D2), mismo `pair_key`; agente en las dos empresas →
  la activa; borrar desde MOYZA quita el de MOES y viceversa; snapshots de cada uno con su
  empresa. Sigue rechazando: inactivo, inexistente, repetido, tres.
- `tests/test_closings_routes.py`: el modal ofrece los agentes de MOES agrupados (ajustar las
  aserciones que hoy afirman lo contrario); alta MOYZA+MOES → flash con los dos nombres; la
  pestaña de MOYZA muestra la fila «con Mía (MOES PREMIUM)» y la de MOES «con Ana (MOYZA)»;
  borrar desde MOES elimina las dos.
- `tests/test_closings_metric.py`: el cierre cuenta 1 para Ana en MOYZA y 1 para Mía en MOES;
  no cuenta 2 en ninguna.
- Móvil: modal y fila a 375 px sin desbordamiento (Chromium headless por CDP, ver memoria
  «probar-movil-chromium-headless»).

### 3.6 Documentación

- Nota en `PLAN_CIERRES_DOS_AGENTES.md` «Estado» remitiendo aquí; `MULTIEMPRESA_MOYZA_MOES.md`
  §15 (sin migración; reinicio).

## 4. Fases

1. Servicio + ruta + plantilla + tests (un agente).
2. Revisión del diff, suite completa y comprobación a 375 px.

### Estado

- [x] Fase 1 (2026-11-27)
- [x] Fase 2 (2026-11-27): diff revisado sin defectos (servicio, ruta, plantilla y tests). Suite completa en verde (ver `PLAN_ALERTA_AGENTE_SIN_COLA.md`, misma ejecución). Pendiente de decidir: si los dos agentes son de la otra empresa, el cierre se guarda entero allí y no sale en la pestaña activa aunque el flash diga «registrado» (consecuencia de D2).

Fase 1, hecha el 2026-11-27:

- Servicio (`closing_service.py`): agentes validados con `visit_agents.get_agent_in_any_company`
  («Elige un agente activo»); nueva `company_for(agent, company_id)` (D2: la activa si el agente
  pertenece a ella; si no, su empresa activa de menor id); `_refresh_snapshots(db, affected)`
  recibe `(company_id, agent_id, closed_on)` y usa un `PerformanceReportService` por empresa;
  `delete_closing` busca la pareja por `pair_key` sin filtro de empresa (D4) y refresca cada
  snapshot con la empresa de su registro.
- Ruta (`commercial_results.py`): `closing_agent_groups = companion_agent_groups(...)`;
  `closing_agents` retirado (no lo usaba nada más). `closing_operations(closings, company_id,
  company_names)` añade `partner_company` (empresas activas del otro agente, unidas por «, »,
  solo si no pertenece a la activa). Contexto con `closings_company_id`. Errores «Elige un agente
  activo» y «… como Agente 2».
- Plantilla: optgroups en los dos selects; ayuda en Agente 1 («De cualquier empresa: el cierre
  cuenta en la suya») y en Agente 2 («… Puede ser un agente de cualquier empresa.»); fila «con
  Nombre (EMPRESA)»; aviso sin agentes sin «en {empresa}»; nota al pie «…para cada uno, en su
  empresa». Sin clases Tailwind nuevas.
- D5 comprobado: `/properties/{id}` del admin solo abre propiedades de la empresa activa, así que
  en la pestaña de la otra empresa la propiedad sale como texto sin enlace
  (`c.property.company_id == closings_company_id`).
- §3.4 Inicio: sin cambios; cada empresa ve su mitad con «Agente de la empresa y el otro»
  (comprobado en `test_closings_metric.py`).
- Tests: `test_closing_service.py` (19), `test_closings_routes.py` (7, nuevo
  `test_cierre_entre_empresas`), `test_closings_metric.py` (7, nuevo de métrica 1 + 1 y feed),
  y el resto de la lista: 126 pasan (1 deseleccionado conocido de `test_dashboard_service.py`).
- Móvil 375 px (Chromium headless por CDP, cierre de prueba entre empresas con nombres largos):
  pestaña y modal en MOYZA y MOES sin desbordamiento (`scrollWidth` 375); datos de prueba borrados.
- Desviaciones: el caso «agente de otra empresa» de los tests de rechazo se sustituye por uno
  inexistente. Si los dos agentes son solo de la otra empresa, el cierre se registra entero en
  ella y no aparece en la pestaña de la activa (consecuencia directa de D2; el flash dice
  «registrado» igual).
