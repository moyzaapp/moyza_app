# Plan: firma de los dos agentes en visitas conjuntas

Fecha: 2026-10-16 · Rama `63-agregar-moes` · Depende de `PLAN_VISITAS_AGENTES.md` (hecho)

## 1. Cómo funciona hoy la firma en la ficha de visita

| Quién | Cómo firma | Dónde queda | Archivo |
|---|---|---|---|
| **Cliente** | Dibuja en el canvas de `/visits/signature/{id}` durante la visita, tras aceptar el RGPD. Se valida que no esté vacía. | `property_visits.signature_filepath`, `signature_captured_at`, `signature_ip` + evento de auditoría `signature_captured`. Estado pasa a `signed`. | `api/v1/endpoints/visits.py::save_signature`, `templates/visits/signature.html` |
| **Agente principal** | **No firma la visita.** Dibuja su firma **una sola vez** desde su ficha de agente ("Se incluirá en todos los informes de visita") y el PDF la estampa automáticamente. | `agents.signature_filepath`, `signature_uploaded_at`. En el PDF: "Firmado digitalmente el {fecha de registro de la firma}". | `routes/agents.py::upload_agent_signature` (el agente solo la suya; el admin cualquiera), `templates/agents/signature_modal.html`, `visit_sheet_generator.py:365-390` |
| **Acompañante** | **No firma.** Solo aparece en el texto legal: "acompañado por los agentes X e Y". | | `visit_sheet_generator.py:58, 307` |

El PDF tiene una tabla de firmas de **dos columnas**: COMPRADOR y AGENTE INMOBILIARIO. El preview HTML
(`visits/preview.html`) no muestra la sección de firmas. El flujo es
`draft → preview → (RGPD) → signature (cliente) → signed → complete → finalize (PDF + WhatsApp) → completed`.
Desde `signed` los agentes de la visita están fijados (decisión 9 del plan de visitas).

Los endpoints `/api/v1/visits/*` (`accept-terms`, `save-signature`, `finalize`) **no comprueban sesión ni
empresa** (problema previo detectado el 2026-10-08).

---

## 2. Decisiones tomadas (2026-10-16)

| # | Pregunta | Decisión |
|---|---|---|
| 1 | Modalidad | **A**: se estampa la firma registrada de **ambos** agentes. La firma dibujada por visita (modalidad B) queda para más adelante; el diseño no debe estorbarla. |
| 2 | Visitas individuales | **Siguen como hoy** (firma registrada del principal, sin paso extra). |
| 3 | Confirmación | **Sí, un paso breve para los agentes**: tras la firma del cliente, una pantalla donde el agente que lleva la visita confirma con un texto corto que la ficha se firma con las firmas registradas de los dos agentes (las ve en miniatura). Queda registrado quién, cuándo y desde qué IP. |
| 4 | Acompañante que no puede firmar | **Permitir "Quitar acompañante"** en ese paso, antes de confirmar. Explicación: como la firma es la registrada, el único bloqueo real es que el acompañante **no tenga firma registrada**; en ese caso, o la registra (él o el admin desde Agentes) o se quita de la visita para poder finalizar. |
| 5 | Orden | **Cliente primero**, luego la confirmación de los agentes. |
| 6 | Proteger endpoints existentes | **Sí**: `accept-terms`, `save-signature` y `finalize` pasan a exigir sesión y empresa, igual que el nuevo. |
| 7 | Preview | **Sí**: muestra los recuadros de firma con los nombres de quienes firmarán. |
| 8 | Cambiar acompañante | **Sin cambios**: permitido en `draft`/`preview`, bloqueado desde `signed` (salvo "Quitar acompañante" del punto 4). |

---

## 3. Diseño

### 3.1 Modelo de datos

Columnas nuevas en `property_visits` (migración `w6x7y8z9a0b1`, `down_revision = 'v5w6x7y8z9a0'`, sin backfill):

```python
agent_signatures_confirmed_at = Column(DateTime, nullable=True)
agent_signatures_confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
agent_signatures_confirmed_ip = Column(String, nullable=True)
```

Propiedades en el modelo:
- `requires_agent_confirmation` → `companion_agent_id is not None`.
- `agents_missing_signature` → lista de agentes de la visita (principal y acompañante) sin `signature_filepath`
  existente en disco.
- `agent_signatures_confirmed` → `agent_signatures_confirmed_at is not None`.
- `can_finalize_agents` → no requiere confirmación, o está confirmada.

Las visitas antiguas con acompañante ya completadas no se ven afectadas (`completed` no vuelve a pasar por el
flujo). Si una visita antigua está en `signed` con acompañante, al retomarla pasará por la confirmación.

### 3.2 Flujo

```
draft → preview → RGPD → signature (cliente) → signed
      → [NUEVO, solo si hay acompañante] /visits/agent-signatures/{id}   (confirmación)
      → complete → finalize → completed
```

- `save_signature` (cliente) devuelve `redirect_url = /visits/agent-signatures/{id}` cuando hay acompañante;
  si no, `/visits/complete/{id}` como hoy.
- **Pantalla `/visits/agent-signatures/{id}`** ("Firmas de los agentes"), con el progreso Datos · Vista previa ·
  Firma cliente · **Firmas agentes** · Finalizado:
  - Dos tarjetas, principal y acompañante: nombre, empresa, miniatura de la firma registrada y "Registrada el
    {fecha}". Si falta la firma: tarjeta en ámbar "Sin firma registrada" con enlace a su ficha en `/agents`
    (si el usuario logueado es ese agente o es admin) o el texto "Pídele que la registre en Agentes".
  - Texto de confirmación: "Confirmo que la ficha de visita se firma con las firmas registradas de
    **{principal}** y **{acompañante}**, tal y como constan en la sección Agentes." Checkbox obligatorio +
    botón primario "Confirmar y continuar", deshabilitado hasta marcar y mientras falte alguna firma registrada.
  - Botón secundario "Quitar acompañante" (confirmación en modal): la visita pasa a individual
    (`companion_agent_id = NULL`), auditoría `companion_removed_before_confirmation` con el id quitado, y
    redirección a `/visits/complete/{id}`. Disponible solo antes de confirmar.
  - Si ya está confirmada: resumen "Confirmado por {usuario} el {fecha}" y botón "Continuar".
- Quién confirma: el usuario logueado en la tablet (el principal o el admin). No se exige que sea el acompañante,
  porque no está logueado.
- `GET /visits/complete/{id}` y `POST finalize`: si `requires_agent_confirmation` y no está confirmada,
  redirigen al paso con aviso. Si falta firma registrada de algún agente, `finalize` responde 400 con el
  nombre del agente.
- **Visitas individuales**: sin cambios.

### 3.3 Rutas y API

- `GET /visits/agent-signatures/{visit_id}` (web, sesión y empresa como el resto de `routes/visits.py`).
- `POST /api/v1/visits/{visit_id}/confirm-agent-signatures` `{ confirmed: true }`: estado `signed`, con
  acompañante, no confirmada, ambos con firma registrada; guarda fecha, usuario e IP; auditoría
  `agent_signatures_confirmed` con `agent_id`, `companion_agent_id` y las fechas de registro de cada firma.
  Devuelve `redirect_url = /visits/complete/{id}`.
- `POST /visits/{visit_id}/remove-companion` (web, form): mismas condiciones; auditoría; flash.
- **Protección** (decisión 6): helper `_visit_for_api(request, db, visit_id)` en `api/v1/endpoints/visits.py`
  que usa `get_api_user` (401 si no hay sesión) + `resolve_company_for_api` + `get_visit_in_company` (404 si
  no es de la empresa activa). Lo usan los cuatro endpoints (`accept-terms`, `save-signature`, `finalize` y el
  nuevo). Comprobar que `signature.html`, `preview.html` y `complete.html` envían la cookie (mismo origen:
  `fetch` con `credentials: 'same-origin'` es el valor por defecto; verificarlo).

### 3.4 PDF y preview

- Tabla de firmas con **tres columnas** cuando hay acompañante: COMPRADOR · AGENTE INMOBILIARIO · AGENTE
  ACOMPAÑANTE (anchos 155 / 155 / 155 con separadores de 20). Bajo cada etiqueta, el nombre del firmante
  (`<font size=8>`). Bajo la firma, "Firmado digitalmente el {fecha de registro}" como hoy.
- Sin acompañante: dos columnas, exactamente como hoy (comprobar con un PDF antes/después que no cambia).
- Fuente de la firma del acompañante: `companion_agent.signature_filepath`. Si no existe el archivo, línea vacía
  (no debería ocurrir, porque la confirmación lo bloquea; cubre PDFs regenerados de visitas antiguas).
- Pie "Metadatos de validación": añadir "Firmas de agentes confirmadas el {fecha}" cuando exista.
- `preview.html`: nueva sección "Firmas" con dos o tres recuadros vacíos y los nombres debajo, igual que el PDF,
  antes del bloque de aceptación RGPD.
- Regenerar PDF desde edición y "Generar PDF": misma lógica (ya pasan `companion_agent`).

### 3.5 Casos límite

- **Borrar la visita**: sin archivos nuevos que borrar (la firma es la del agente).
- **El agente cambia su firma registrada después** de una visita completada: el PDF ya generado no cambia; una
  regeneración manual usaría la nueva (comportamiento actual para el principal; se documenta).
- **Edición** en `signed`/`completed`: el bloque de agentes muestra "Firmas confirmadas el …" si aplica.
- **Preparado para B**: las columnas por agente (`agent_signature_filepath`, etc.) no se crean ahora; cuando
  llegue B, la pantalla de confirmación se convierte en la de firma por visita y el PDF prioriza la firma por
  visita sobre la registrada.

---

## 4. Fases de implementación

Un commit por fase: `feat(visitas): fase N - firma de agentes …`. Skill `moyza-ui-ux-pro` en lo visual.

### Fase 1 · Modelo, migración y protección de la API
- [ ] Columnas de §3.1, propiedades del modelo, migración `w6x7y8z9a0b1` + downgrade.
- [ ] Helper `_visit_for_api` y su uso en `accept-terms`, `save-signature`, `finalize` (decisión 6).
- [ ] Tests: propiedades del modelo (sin BD); los tres endpoints devuelven 401 sin sesión y 404 con la
      visita de otra empresa; con sesión siguen funcionando (flujo completo de una visita individual).

### Fase 2 · Paso de confirmación
- [ ] Ruta web + plantilla `visits/agent_signatures.html` (§3.2), parcial de progreso compartido si procede.
- [ ] Endpoint `confirm-agent-signatures`, ruta `remove-companion`, redirección desde `save_signature`,
      guardas en `complete_visit_page` y `finalize_visit`.
- [ ] Auditoría: `agent_signatures_confirmed`, `companion_removed_before_confirmation`.
- [ ] Tests de ruta: visita individual no pasa por el paso; con acompañante no finaliza sin confirmar;
      confirmación bloqueada si falta firma registrada (mensaje con el nombre); confirmación repetida
      rechazada; quitar acompañante antes de confirmar pasa a individual y permite finalizar; quitar
      acompañante después de confirmar rechazado; evento de auditoría presente.

### Fase 3 · PDF y preview
- [ ] `visit_sheet_generator`: tres columnas con nombres y fallback (§3.4); pie con la confirmación.
- [ ] `preview.html`: sección "Firmas".
- [ ] Tests: PDF con acompañante contiene las tres etiquetas y los dos nombres (texto extraído con
      `pypdf`/`pdfplumber`, el que esté en requirements; si ninguno, comprobar el `elements` del generador
      mediante un hook de test); PDF sin acompañante idéntico en estructura al actual.

### Fase 4 · QA y despliegue
- [ ] Flujo completo en local: visita conjunta (cliente → confirmación → PDF con tres firmas) con agentes 6 y 12;
      visita conjunta con un acompañante sin firma registrada (bloqueo + quitar acompañante); visita individual
      sin cambios.
- [ ] `ui_lint.py` sobre plantillas tocadas; revisión en móvil con `fetch_page.py`.
- [ ] Nota de despliegue en `MULTIEMPRESA_MOYZA_MOES.md` (§10): `alembic upgrade head` + reinicio; aviso de
      que los endpoints de firma ahora exigen sesión (si alguna integración externa los usaba, dejará de funcionar).

### Criterios de aceptación
1. Una visita con acompañante no se puede finalizar sin la confirmación de firmas de agentes.
2. La confirmación queda con usuario, fecha, IP y evento de auditoría.
3. El PDF y el preview muestran tres firmas con nombre; una visita individual sigue igual que hoy.
4. Si un agente de la visita no tiene firma registrada, no se puede confirmar; se puede quitar al acompañante antes de confirmar.
5. Los cuatro endpoints de `/api/v1/visits/*` exigen sesión y empresa.

---

## 5. Brief para el agente ejecutor

> Implementa `PLAN_FIRMA_AGENTES_VISITA.md` por fases, un commit por fase, sin push, con el skill
> `moyza-ui-ux-pro` en todo lo visual. Lee primero `PLAN_VISITAS_AGENTES.md` (hecho), `models/property_visit.py`,
> `api/v1/endpoints/visits.py` entero, `routes/visits.py` (preview, signature, complete, update, generate-pdf,
> delete, `_visit_agents_context`), `services/visit_audit_service.py`, `services/visit_sheet_generator.py`
> (tabla de firmas y texto legal), `routes/agents.py::upload_agent_signature`, `templates/visits/signature.html`,
> `preview.html`, `complete.html`, `agents_fields.html`, `web/dependencies/company.py` (`get_api_user`,
> `resolve_company_for_api`), `web/routes/notifications.py` (ejemplo de endpoint `/api/*` protegido con
> `get_api_user`) y la última migración `v5w6x7y8z9a0`. Para leer texto de un PDF en tests solo hay `reportlab`
> en requirements: usa `pypdf` si está instalado en el contenedor o comprueba los elementos del generador. Respeta las decisiones de §2. El
> contenedor `moyza_backend` debe estar levantado; si Docker no responde, deja la migración escrita, ejecuta lo
> que puedas sin BD y repórtalo sin fingir que se aplicó. Reporta la salida real de alembic, pytest y ui_lint.
