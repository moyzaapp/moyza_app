# Plan: visitas a propiedades de otros agentes y visitas con dos agentes

Fecha: 2026-10-08 · Rama de trabajo: `63-agregar-moes` (o rama nueva a partir de esta)

## 1. Cómo funciona hoy

### 1.1 Atribución de la visita

La visita (`property_visits`) **no tiene agente propio**. Se atribuye de forma indirecta por dos vías
que no coinciden entre sí:

| Dónde | Cómo decide "de quién es la visita" | Archivo |
|---|---|---|
| Listado `/visits` (agente) | Filtra por `Property.agent_id == agente del usuario` (agente captador) | `backend/app/web/routes/visits.py:55-64` |
| Selector de propiedad | Solo muestra propiedades con `Property.agent_id == agente` | `backend/app/web/routes/visits.py:96-102` |
| Columna "Agente" de la tabla | Muestra `visit.creator.full_name` (el **usuario** que creó, no un `Agent`) y si no, el agente de la propiedad | `backend/app/web/templates/visits/table.html:62-70` |
| PDF y preview ("emitido por el asesor inmobiliario X" + firma del agente) | Siempre `property_item.agent` (captador) | `visit_sheet_generator.py:300,366`, `routes/visits.py:455,673,779`, `api/v1/endpoints/visits.py:237` |
| Informe de desempeño `hojas_visita` | Cuenta visitas por `Property.agent_id` (captador) | `backend/app/services/performance_report_service.py:129-138` |
| Detalle de propiedad "Historial de visitas" | Todas las visitas de la propiedad, sin columna de agente | `templates/properties/detail.html:628-740` |

Solo existe `created_by` (FK a `users.id`). El vínculo usuario → agente se hace por email
(`get_agent_from_user`), no hay FK.

### 1.2 Qué pasa hoy si un agente visita una propiedad que no es suya

- **No la puede elegir** en `/visits/select-property` (filtrada a sus propiedades).
- Pero `/visits/new/{id}` y `/visits/create/{id}` **no comprueban** que la propiedad sea del agente:
  solo que sea de la empresa activa y esté disponible. Si llega por URL (por ejemplo desde el
  detalle de la propiedad, que sí es visible para cualquier agente de la empresa), la visita se crea.
- Esa visita después **no aparece en su listado** `/visits` (va al listado del captador), **no le
  cuenta** en su informe de desempeño, y el PDF sale **a nombre y con la firma del captador**,
  aunque quien acompañó al cliente fue otro.

Conclusión: el bloqueo actual es solo de UI y la atribución es incorrecta cuando pasa. Hay que hacer
explícito quién realizó la visita.

### 1.3 Flujo legal actual (no cambia)

`/visits/new` → POST `/visits/create` (estado `draft`) → `/visits/preview` → API `accept-terms` →
`/visits/signature` → API `save-signature` → `/visits/complete` → API `finalize` (PDF + WhatsApp,
estado `completed`). Edición en `/visits/edit` regenera el PDF si existía.

---

## 2. Diseño propuesto

### 2.1 Modelo de datos

Añadir a `property_visits` dos columnas (migración Alembic nueva, `down_revision = 'r1s2t3u4v5w6'`):

```python
# Agente que realizó la visita (acompañó al cliente). Obligatorio tras el backfill.
agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
# Segundo agente cuando la visita se hizo entre dos. Opcional.
companion_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)

agent = relationship("Agent", foreign_keys=[agent_id])
companion_agent = relationship("Agent", foreign_keys=[companion_agent_id])
```

Reglas:
- `agent_id` es el agente **principal** (figura en el PDF y firma). `companion_agent_id` es el
  acompañante. Un agente no puede ser su propio acompañante.
- Helper en el modelo: `participating_agent_ids` → `{agent_id, companion_agent_id}` sin `None`.
- Helper de consulta en `company_scope.py` o en un nuevo `visit_scope.py`:
  `visits_for_agent(query, agent_id)` → `or_(PropertyVisit.agent_id == X, PropertyVisit.companion_agent_id == X)`.
  Se usa en listado, informe de desempeño y cualquier futuro conteo.
- Backfill en la migración (SQL puro, sin importar modelos):
  1. `agent_id` = agente cuyo `email` coincide con el `email` del usuario `created_by`.
  2. Si no hay coincidencia, `agent_id` = `properties.agent_id` de la propiedad.
  3. Lo que quede en NULL se deja NULL (visitas huérfanas, el PDF sigue cayendo en el agente de la propiedad).

> Alternativa descartada por ahora: tabla N:M `visit_agents` (N agentes por visita). Más flexible,
> pero el requisito es "solo o con otro agente" y dos columnas simplifican formularios, PDF y conteos.
> Si en el futuro se necesitan 3+ agentes se migra a N:M; el helper `visits_for_agent` aísla ese cambio.

### 2.2 Proceso: visitar una propiedad que no es del agente

Decisión por defecto (ver preguntas abiertas en §4): **cualquier agente de la empresa activa puede
registrar visita en cualquier propiedad disponible de esa empresa, sin aprobación previa.** La
trazabilidad sustituye a la autorización: queda registrado quién la hizo, el captador la ve en su
listado y en el detalle de la propiedad, y se audita.

Cambios:
1. **Selector de propiedad** (`/visits/select-property`): dos bloques para agentes:
   - "Mis propiedades" (como hoy).
   - "Otras propiedades de la empresa" (resto de disponibles de la empresa activa), con buscador
     por título/dirección y chip con el nombre del agente captador en cada tarjeta.
   - Admin sigue viendo todo en un solo bloque (añadir el chip del captador también).
2. **Formulario de nueva visita** (`/visits/new/{id}`): aviso informativo cuando la propiedad no es
   del agente logueado ("Propiedad captada por X. La visita se registrará a tu nombre").
3. **Backend `create_visit`**: ya no depende de que la propiedad sea del agente; valida que esté en la
   empresa activa y disponible (como hoy) y asigna `agent_id` según §2.3.
4. **Listado `/visits` para agente**: muestra visitas donde participó (principal o acompañante)
   **o** cuya propiedad es suya (para que el captador vea las visitas que otros hacen a sus inmuebles).
   Añadir indicador visual cuando la visita la hizo otro agente sobre una propiedad propia.
5. **Detalle de propiedad**: nueva columna "Agente" en el historial de visitas
   (`agent.name` + " · con {companion}" cuando aplique).

### 2.3 Formulario: solo o con otro agente

En `properties/visit_form.html` (alta) y `visits/edit_form.html` (edición), nueva sección
"Agentes de la visita" antes de observaciones:

- **Usuario agente**: "Realizada por: {su nombre}" fijo (hidden `agent_id` = su id, validado en backend,
  no se acepta otro valor). Radio `visit_mode`: `solo` (default) / `acompañado`. Al elegir
  `acompañado` aparece `<select name="companion_agent_id">` con los agentes de la empresa activa
  menos él mismo (`scope_agents`).
- **Usuario admin**: `<select name="agent_id">` con los agentes de la empresa activa, preseleccionado
  el agente de la propiedad; mismo radio y select de acompañante.
- **Validación backend** (`create_visit` y `update_visit`):
  - `agent_id` obligatorio y perteneciente a la empresa activa (`get_agent_in_company`).
  - Si el usuario es agente, `agent_id` se fuerza a su propio agente (ignorar lo que venga en el form).
  - `companion_agent_id` opcional, en la empresa activa, distinto de `agent_id`.
  - Errores → redirect al formulario con flash, como el resto de validaciones.
- Auditoría: `draft_created` y una nueva entrada `agents_updated` (en edición) incluyen
  `agent_id` y `companion_agent_id` en `event_data`.

"Se agrega la visita a los dos agentes" se cumple por consulta, no por duplicar filas: una sola
visita, dos agentes vinculados, ambos la ven en su listado y a ambos les cuenta.

### 2.4 PDF, preview y firma

- `generate_visit_sheet(..., agent=...)` recibe `visit.agent or property_item.agent` en los 4 puntos
  que hoy pasan `property_item.agent` (`routes/visits.py` update/generate-pdf, `api/.../finalize`).
  Centralizar en un helper `visit.signing_agent` (property) con ese fallback.
- Texto legal (PDF y `preview.html`): "emitido por el asesor inmobiliario **{principal}**". Si hay
  acompañante, la frase "acompañado por el agente de la inmobiliaria" pasa a
  "acompañado por los agentes de la inmobiliaria **{principal}** y **{acompañante}**".
- Firma: la del agente principal (`agent.signature_filepath`). El acompañante no firma.
- Preview (`routes/visits.py:455`): `agent_name` del principal, misma lógica que el PDF.

### 2.5 Informe de desempeño

`performance_report_service.calculate_metrics`: `hojas_visita` pasa de contar por
`Property.agent_id` a `visits_for_agent(agent_id)` (principal **o** acompañante). Cada agente
suma 1 por visita en la que participó; el captador que no estuvo no suma.

Los informes ya congelados (`is_locked`) no se recalculan.

### 2.6 Multiempresa

- Agentes seleccionables = `scope_agents(db.query(Agent), empresa_activa)`.
- `get_agent_in_company` en la validación de ambos campos.
- Las visitas siguen heredando empresa de la propiedad (`scope_visits`); no cambia.
- Un agente que pertenece a las dos empresas solo puede acompañar visitas de la empresa activa.

---

## 3. Pasos de implementación

Cada fase termina con la app levantada y un commit propio. Orden pensado para que nada quede roto
entre fases.

### Fase 1 · Modelo y migración
- [ ] `backend/app/models/property_visit.py`: columnas `agent_id`, `companion_agent_id`,
      relaciones `agent` / `companion_agent`, properties `signing_agent` y `participating_agent_ids`.
- [ ] `backend/app/models/agent.py`: relaciones inversas opcionales (`visits_as_agent`, `visits_as_companion`)
      con `foreign_keys` explícitos para evitar ambigüedad.
- [ ] Migración `backend/alembic/versions/s2t3u4v5w6x7_add_agents_to_property_visits.py`
      con el backfill de §2.1 y `downgrade` que elimina columnas e índices.
- [ ] Helper `visits_for_agent(query, agent_id)` en `backend/app/services/company_scope.py`
      (misma filosofía de filtro reutilizable).
- [ ] Verificar: `alembic upgrade head` en local, consulta rápida de cuántas visitas quedaron con `agent_id` NULL.

### Fase 2 · Alta y edición con agentes
- [ ] `routes/visits.py::new_visit`: pasar `agents` (empresa activa), `current_agent`, `is_admin`
      y `is_foreign_property` al template.
- [ ] `templates/properties/visit_form.html`: sección "Agentes de la visita" (§2.3) + aviso de
      propiedad ajena + JS para mostrar/ocultar el select de acompañante.
- [ ] `routes/visits.py::create_visit`: parsear y validar `agent_id` / `companion_agent_id`,
      asignar en el `PropertyVisit`, incluir en `event_data` de `draft_created`.
- [ ] `routes/visits.py::edit_visit` + `templates/visits/edit_form.html`: mismos campos con valores actuales
      solo si la visita está en `draft`/`preview`; si está `signed`/`completed`, bloque de solo lectura (decisión 9).
- [ ] `routes/visits.py::update_visit`: misma validación; si la visita está firmada/completada se ignoran
      los campos de agentes; registrar `agents_updated` en auditoría si cambian.
- [ ] Extraer la validación común a una función `parse_visit_agents(form, request, db, property_item)`
      para no duplicarla.

### Fase 3 · Selección de propiedad y listados
- [ ] `routes/visits.py::select_property`: para agentes, devolver `own_properties` y `other_properties`;
      para admin, todas. Cargar `agent` con `joinedload` para el chip.
- [ ] `templates/visits/select_property.html`: dos bloques + buscador cliente (filtro JS por texto) + chip captador.
- [ ] `routes/visits.py::visits_page`: filtro de agente = `visits_for_agent OR Property.agent_id == agente`.
- [ ] `templates/visits/table.html`: columna "Agente" muestra `visit.agent.name` (+ acompañante);
      badge "Propiedad propia · visita de otro agente" cuando aplique. Mantener fallback a
      `creator.full_name` solo si `agent` es NULL.
- [ ] `templates/properties/detail.html`: columna "Agente" en historial de visitas.

### Fase 4 · PDF, preview y firma
- [ ] `services/visit_sheet_generator.py`: aceptar `companion_agent` (kwarg opcional) y ajustar
      texto legal; firma del principal.
- [ ] Sustituir `property_item.agent` por `visit.signing_agent` en `routes/visits.py` (update, generate-pdf),
      `api/v1/endpoints/visits.py::finalize_visit` y en `preview_visit` (`agent_name`).
- [ ] `templates/visits/preview.html`: mismo texto que el PDF (tiene que coincidir con lo que se firma).

### Fase 5 · Informe de desempeño
- [ ] `services/performance_report_service.py::calculate_metrics`: `hojas_visita` con `visits_for_agent`.
- [ ] Revisar `routes/performance_reports.py` y `routes/alerts.py:1497` por si muestran el origen del dato (solo lectura).

### Fase 6 · Tests y documentación
- [ ] `backend/tests/test_visit_agents.py` (unitarios, misma convención que `test_company_context.py`):
      - `visits_for_agent` devuelve visitas como principal y como acompañante.
      - `parse_visit_agents`: agente no puede suplantar `agent_id`; acompañante ≠ principal;
        acompañante fuera de la empresa → error.
      - `signing_agent` cae al agente de la propiedad si `agent_id` es NULL.
      - `calculate_metrics.hojas_visita` cuenta a ambos agentes y no al captador ausente.
- [ ] Integración (patrón `test_company_isolation.py`, se omite si la app no responde):
      agente registra visita en propiedad ajena → aparece en su `/visits` y en el del captador.
- [ ] Añadir a `MULTIEMPRESA_MOYZA_MOES.md` o a este archivo la nota de despliegue:
      `alembic upgrade head` + `docker restart moyza_backend`.
- [ ] Ejecutar `pytest` dentro del contenedor (`docker exec moyza_backend pip install pytest` si falta)
      y `pyflakes` sobre los archivos tocados.

### Criterios de aceptación
1. Un agente puede elegir cualquier propiedad disponible de su empresa activa y registrar la visita;
   la visita queda con `agent_id` = él.
2. Un agente no puede, manipulando el form, registrar una visita a nombre de otro agente.
3. Con acompañante, la visita aparece en `/visits` de los dos y suma 1 a `hojas_visita` de los dos.
4. El captador ve en `/visits` y en el detalle de la propiedad las visitas que otros hicieron a su inmueble.
5. PDF y preview nombran al agente principal (y al acompañante en el texto) y llevan la firma del principal.
6. Las visitas antiguas conservan su atribución tras el backfill y sus PDFs se regeneran sin error.
7. Nada de otra empresa es seleccionable ni visible (agentes, propiedades, visitas).

---

## 4. Decisiones tomadas (2026-10-08)

| # | Pregunta | Decisión |
|---|---|---|
| 1 | ¿Visitar propiedades ajenas requiere aprobación? | **No.** Basta con registrar y que se vea (listado, detalle de propiedad y, más adelante, la sección de inicio/Dashboard). |
| 2 | ¿Notificar al captador (email/WhatsApp)? | **No**, nada de spam. Se mostrará en la sección de inicio que se planea en `PLAN_DASHBOARD_INICIO.md`. Este plan no envía nada. |
| 3 | ¿Quién figura y firma en el PDF? | **El agente que realiza la visita** (principal). Acompañante solo en el texto legal. |
| 4 | ¿El captador ve en `/visits` las visitas de otros a su propiedad? | **Sí** (pendiente de confirmar por el usuario; se asume que sí). |
| 5 | ¿`hojas_visita` cuenta para principal y acompañante? | **Sí**, 1 a cada uno. El captador ausente no suma. |
| 6 | Backfill por usuario creador y luego por agente de la propiedad | **Sí.** |
| 7 | ¿Máximo dos agentes por visita? | **Sí**, por ahora. |
| 8 | ¿Admin puede registrar a nombre de cualquier agente? | **Sí.** |
| 9 | ¿Se puede cambiar el agente en una visita firmada/completada? | **No.** Los agentes quedan fijos al firmar: en `/visits/edit` de una visita con estado `signed` o `completed` los campos de agentes se muestran solo lectura (sin inputs) y el backend ignora cualquier valor que llegue para ellos. En `draft`/`preview` sí se pueden cambiar. |
| 10 | ¿Buscador en el selector de propiedad? | **Sí**, filtro JS simple. |

Ajuste derivado de la decisión 9 en la Fase 2: `parse_visit_agents` recibe `locked: bool`
(`visit.visit_status in ('signed', 'completed')`) y, si está bloqueado, devuelve los valores actuales
sin leer el form. El template de edición muestra "Realizada por: X · con Y" como texto fijo con un
candado y la nota "Fijado al firmar la ficha".

---

## 5. Brief para el agente ejecutor

Cuando se aprueben las respuestas de §4, lanzar un agente (Opus 5.5, high) con este encargo:

> Implementa `PLAN_VISITAS_AGENTES.md` fase por fase en la rama actual, un commit por fase con
> mensaje `feat(visitas): fase N - …` y la línea de co-autoría indicada en el repo. Lee primero
> `backend/app/web/routes/visits.py`, `backend/app/api/v1/endpoints/visits.py`,
> `backend/app/models/property_visit.py`, `backend/app/services/company_scope.py`,
> `backend/app/services/visit_sheet_generator.py` y `backend/app/services/performance_report_service.py`.
> Respeta las decisiones de §4 (tabla con respuestas). No toques el flujo legal
> (preview → firma → finalize) más allá de cambiar qué agente se usa. Las reglas multiempresa de
> `MULTIEMPRESA_MOYZA_MOES.md` aplican a todo lo nuevo. Al terminar ejecuta los tests dentro del
> contenedor y reporta qué pasó y qué no.
