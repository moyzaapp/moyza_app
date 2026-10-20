# Multiempresa: MOYZA y MOES PREMIUM

La aplicación gestiona dos empresas internas con una sola base de datos y un
solo despliegue. El usuario elige la empresa activa en el selector del sidebar
y todas las secciones muestran únicamente los datos de esa empresa.

## 1. Modelo de datos

| Tabla | Relación con empresa | Motivo |
|---|---|---|
| `companies` | — | Identidad legal y de marca de cada empresa |
| `properties`, `buyers` | `company_id` (NOT NULL) | Pertenecen a una sola empresa |
| `users`, `agents`, `clients` | N:M (`user_companies`, `agent_companies`, `client_companies`) | Pueden trabajar en ambas |
| alertas, visitas, informes, logs | Heredan de su propiedad o agente | No llevan columna propia |

Códigos estables: `MOYZA` y `MOES` (columna `companies.code`, clase
`CompanyCode` en `app/core/constants.py`). El nombre visible de MOES es
"MOES PREMIUM".

Columnas heredadas `users.company` y `agents.company` (texto libre): se siguen
rellenando con los nombres unidos ("MOYZA, MOES PREMIUM") pero ya no se
editan desde la interfaz. Se pueden eliminar en una migración futura.

## 2. Cómo funciona

- **Contexto**: `AuthMiddleware` calcula las empresas permitidas del usuario y
  la activa (cookie `active_company`), y las deja en `request.state.company`
  y `request.state.allowed_companies`. Lógica en
  `app/web/dependencies/company.py`.
- **Permisos**: el admin ve todas las empresas; el resto, las de su usuario
  más las de su ficha de agente. Un usuario sin ninguna cae a MOYZA.
- **Selector**: `POST /switch-company` valida la empresa contra las permitidas
  y guarda la cookie un año. Solo se muestra si el usuario tiene más de una.
- **Filtrado**: todo pasa por `app/services/company_scope.py` (`scope_*`,
  `get_*_in_company`). Un objeto de otra empresa se trata como inexistente.
- **Marca en documentos**: `branding_for(company)` en
  `app/services/company_service.py` alimenta la ficha de visita (PDF y
  preview), el informe PDF, los recordatorios de compradores y los emails de
  cuenta. Los documentos usan la empresa de la propiedad, no la de la cookie.
- **Endpoints `/api/*`**: no pasan por el middleware; resuelven usuario y
  empresa desde las cookies con `get_api_user` y `resolve_company_for_api`.
  Los de logs e IA devuelven 401 sin sesión (antes respondían a cualquiera).

### Reglas de negocio

- Alta de agente o cliente con un email que ya existe en la otra empresa: se
  le añade a la empresa activa, no se duplica la ficha.
- Baja de agente o cliente presente en ambas: solo se le quita de la activa.
  La ficha se borra cuando no queda en ninguna y no tiene propiedades.
- La cola secuencial de alertas de un agente es por empresa.
- Los recordatorios de compradores se envían por agente y empresa.
- Un agente no puede cambiar sus propias empresas; solo el admin.
- Única excepción al aislamiento: en `/properties?tab=other_company` todos los
  roles ven, en solo lectura, las propiedades activas y disponibles de la otra
  empresa (sin propietario ni enlace al detalle); nada más de ella se expone.

## 3. Despliegue en producción

Requiere la migración `r1s2t3u4v5w6_add_companies`. Todo lo existente queda
asignado a MOYZA; no se pierde ningún dato.

```bash
# 1. Copia de seguridad
docker exec moyza_db pg_dump -U <usuario> -d <bd> -Fc > backup_pre_multiempresa_$(date +%F).dump

# 2. Desplegar el código y aplicar la migración
docker exec moyza_backend alembic upgrade head

# 3. Verificar
docker exec moyza_db psql -U <usuario> -d <bd> -c "
  select code, name from companies;
  select company_id, count(*) from properties group by 1;
  select company_id, count(*) from buyers group by 1;
  select (select count(*) from users)   as users,   (select count(*) from user_companies)   as user_companies,
         (select count(*) from agents)  as agents,  (select count(*) from agent_companies)  as agent_companies,
         (select count(*) from clients) as clients, (select count(*) from client_companies) as client_companies;"

# 4. Reiniciar el backend (el proceso no recarga código por sí solo)
docker restart moyza_backend
```

Resultado esperado del paso 3: dos filas en `companies`, todas las propiedades
y compradores con el `company_id` de MOYZA, y tantas filas de pertenencia como
usuarios, agentes y clientes (una por cada uno, en MOYZA). Si algún usuario o
agente tenía "MOES…" en su texto de empresa, queda en MOES en lugar de MOYZA.

Prueba manual tras el despliegue: entrar como admin, comprobar que el selector
del sidebar muestra MOYZA, cambiar a MOES PREMIUM y confirmar que los listados
están vacíos, volver a MOYZA y confirmar que todo sigue igual.

### Rollback

```bash
docker exec moyza_backend alembic downgrade q0r1s2t3u4v5
docker restart moyza_backend   # con el código anterior desplegado
```

El downgrade elimina las tablas de pertenencia, las columnas `company_id` y la
tabla `companies`. No toca el resto de datos.

## 4. Datos de MOES PREMIUM

La migración crea MOES PREMIUM con los datos legales de MOYZA de forma
**provisional** (marcados `TODO` en la migración). En cuanto se tengan los
reales, se actualizan en base de datos sin tocar código:

```sql
UPDATE companies SET
  legal_name     = 'Razón social de MOES',
  tax_id         = 'CIF de MOES',
  fiscal_address = 'Domicilio fiscal de MOES',
  phone          = 'Teléfonos de MOES',
  rgpd_text      = 'Primer párrafo RGPD de MOES (el que nombra a la empresa)',
  logo_path      = '/static/logo_moes.png',
  primary_color  = '#8A6D1F',
  email_sender_name = 'Sistema MOES Premium'
WHERE code = 'MOES';
```

El logo se copia a `backend/app/static/` con el nombre indicado en `logo_path`.
`rgpd_text` es solo el primer párrafo del bloque RGPD; los demás son fijos.
Los campos que se dejen en NULL caen a los valores de MOYZA.

## 5. Tests

```bash
# Unitarios (sin base de datos)
docker exec moyza_backend python -m pytest tests/test_company_context.py -q

# Integración contra la app levantada en local (crean y borran datos en MOES)
docker exec moyza_backend python -m pytest tests/test_company_isolation.py -q
```

```bash
# Agentes de las visitas (unitarios + integración si la app responde)
docker exec moyza_backend python -m pytest tests/test_visit_agents.py -q
```

`pytest` no está en `requirements.txt`; se instala con
`docker exec moyza_backend pip install pytest` o con `run_tests.sh`.

## 6. Visitas con agente propio y acompañante

Detalle en `PLAN_VISITAS_AGENTES.md`. Cualquier agente puede registrar
visitas en cualquier propiedad disponible de la empresa activa; la visita
guarda quién la hizo (`property_visits.agent_id`) y un acompañante opcional
(`companion_agent_id`). El principal debe ser agente de la empresa activa; el
acompañante puede ser de cualquier empresa (cambio del 2026-10-09, commit a78f721).

- Listado `/visits` del agente: visitas en las que participó y las que otros
  hicieron a sus propiedades.
- Ficha PDF y preview: emite y firma el agente de la visita; el acompañante
  solo aparece en el texto legal. Visitas antiguas sin agente caen al
  captador.
- `hojas_visita`: suma 1 al principal y 1 al acompañante; no al captador.
- Agentes fijos al firmar: en `signed`/`completed` no se pueden cambiar.

Despliegue (migración `s2t3u4v5w6x7_add_agents_to_property_visits`, con
backfill: agente del usuario creador por email y, si no, el captador):

```bash
docker exec moyza_backend alembic upgrade head
docker exec moyza_db psql -U <usuario> -d <bd> -c "
  select count(*) as total, count(agent_id) as con_agente,
         count(*) filter (where agent_id is null) as sin_agente
  from property_visits;"
docker restart moyza_backend
```

Rollback: `docker exec moyza_backend alembic downgrade r1s2t3u4v5w6` con el
código anterior desplegado (elimina las dos columnas y sus índices).

## 7. Resultados Comerciales (rendimiento por empresa)

Detalle en `PLAN_RESULTADOS_COMERCIALES.md`. La sección "Dashboard
Compradores" pasa a ser **Resultados Comerciales** (`/commercial-results`,
solo admin) con tres pestañas: Rendimiento (semana / mes / año), Evolución
(gráficas del año con Chart.js local en `static/js/chart.umd.js`) y
Compradores. `/alerts-dashboard` y `/performance-reports` redirigen con 301
conservando los query params.

- Todas las métricas se calculan con las propiedades de la empresa activa.
  Un agente que está en las dos empresas tiene resultados, objetivos y
  snapshots separados en cada una.
- Captaciones, bajadas y cierres se desglosan en venta / alquiler (el
  cierre usa el tipo de la alerta y, si falta, el de la propiedad).
- Objetivos por período (`PerformanceObjectives` en `core/constants.py`):
  semana = captaciones y bajadas; mes y año = captaciones, bajadas y
  cierres. Los objetivos antiguos de contactos y hojas de visita se quedan
  en la tabla como histórico.
- Nuevo job `freeze_yearly_reports` (1 de enero, 00:01); semanal y mensual
  congelan ahora un snapshot por empresa y agente.

Despliegue (migración `t3u4v5w6x7y8_add_company_and_breakdown_to_performance`:
`company_id` en objetivos y snapshots con backfill a MOYZA, clave única por
agente + empresa + período, y 6 columnas de desglose que quedan NULL en los
snapshots existentes; sus totales no cambian):

```bash
docker exec moyza_db pg_dump -U <usuario> -d <bd> -Fc > backup_pre_resultados_$(date +%F).dump
docker exec moyza_backend alembic upgrade head
docker exec moyza_db psql -U <usuario> -d <bd> -c "
  select company_id, period_type, count(*) from agent_performance_reports group by 1, 2;
  select company_id, period_type, count(*) from agent_performance_targets group by 1, 2;"
docker restart moyza_backend
```

Resultado esperado: todas las filas existentes con el `company_id` de MOYZA y
los mismos totales que antes. Los snapshots anteriores se muestran "sin
desglose" (en las gráficas, su total cuenta como "otros").

Rollback: `docker exec moyza_backend alembic downgrade s2t3u4v5w6x7` con el
código anterior desplegado. **Borra los objetivos y snapshots de MOES**: la
clave antigua no admite el mismo agente y período en dos empresas.

```bash
# Tests (servicio sin app; rutas contra la app levantada)
docker exec moyza_backend python -m pytest tests/test_performance_service.py tests/test_commercial_results.py tests/test_scheduler.py -q
```

## 8. Inicio por rol y notificaciones in-app

Detalle en `PLAN_DASHBOARD_INICIO.md`. `/dashboard` es el **Inicio** para
todos los roles (el login sigue llevando ahí; el agente ya no ve "Acceso
denegado") y todo su contenido es de la empresa activa:

- Agente: KPIs del período (semana / mes / año) con delta y anillo de
  objetivo solo en las métricas de `PerformanceObjectives`, % global y
  puesto sin nombres, novedades, agenda, tendencia de 8 semanas, cartera y
  observaciones del admin.
- Admin: KPIs del equipo, cumplimiento por agente, "Requiere atención",
  actividad reciente (visita cruzada marcada) y tendencia de 12 semanas.
- Al entrar, ventana de compradores que requieren atención: misma regla que
  el email diario (desde la sección 12, en horas hábiles y con "sin avance"),
  filtrada por la empresa activa; una vez cerrada no vuelve ese día en ese
  navegador.
- Notificaciones **solo in-app** (campana del navbar para agentes,
  `/notifications` y bloque "Novedades"): visita en tu inmueble, acompañante,
  ficha firmada, envío de ficha fallido, seguimiento de hoy o vencido
  (job diario 08:00 Madrid) y observación del admin. Cada notificación es
  de un usuario y una empresa; nunca se avisa al propio actor y no se
  repite la misma en 24 h. Las leídas se borran a los 90 días (job diario).

Despliegue (migración `u4v5w6x7y8z9_create_notifications`, solo crea la
tabla `notifications`; no toca datos existentes):

```bash
docker exec moyza_backend alembic upgrade head
docker restart moyza_backend
```

Rollback: `docker exec moyza_backend alembic downgrade t3u4v5w6x7y8` con el
código anterior desplegado (borra la tabla y sus notificaciones).

```bash
# Tests (servicios con base de datos; rutas contra la app levantada)
docker exec moyza_backend python -m pytest tests/test_dashboard_service.py tests/test_notification_service.py tests/test_dashboard_routes.py tests/test_visit_preview_edit.py -q
```

## 9. Asignación de alertas de comprador a otro agente

Detalle en `PLAN_ASIGNACION_ALERTAS.md`. La alerta sigue yendo por defecto al
captador de la propiedad, pero el **admin** puede elegir otro agente al
crearla (modal "Nueva alerta" y formulario rápido de la ficha del comprador)
y **reasignarla** mientras está abierta (detalle y acción de fila del
listado). El agente no elige: ve "Se asignará a {captador}".

- Se puede elegir un agente de **cualquier empresa**. Si no pertenece a la
  empresa de la propiedad, se le añade a esa empresa (`agent_companies`,
  igual que desde la ficha del agente) y su usuario gana acceso a ella por
  la ficha (`get_allowed_companies`), sin tocar `user_companies`. El
  formulario lo avisa antes de guardar y `/alerts` le muestra al agente un
  banner con el cambio de empresa si tiene alertas abiertas en la otra.
- Propiedad sin captador: el admin puede crear la alerta eligiendo agente.
- Motivo opcional. Reasignar deja la alerta Pendiente y sin leer, conserva
  los seguimientos, la anota en el historial (`alert_assignment_logs`) y con
  una nota `REASIGNADA` en los seguimientos que no cuenta como gestión (no
  desbloquea la cola ni permite cerrar).
- Cola secuencial, recordatorio de 48 h, abandonados y tiempo de respuesta
  cuentan desde la asignación; contactos y cierres pasan al nuevo agente.
- Aviso **solo in-app** (`alert_assigned`) al nuevo agente, en la empresa de
  la propiedad; nunca email ni WhatsApp, ni aviso al agente anterior.

Despliegue (migración `v5w6x7y8z9a0_add_alert_assignment`: 4 columnas en
`property_alerts` con backfill `assigned_at = created_at`,
`assigned_by = created_by`, y la tabla `alert_assignment_logs` vacía; ninguna
alerta cambia de agente ni de orden en la cola):

```bash
docker exec moyza_backend alembic upgrade head
docker exec moyza_db psql -U <usuario> -d <bd> -c "
  select count(*) as total,
         count(*) filter (where assigned_at = created_at) as backfill_ok
  from property_alerts;"
docker restart moyza_backend
```

Rollback: `docker exec moyza_backend alembic downgrade u4v5w6x7y8z9` con el
código anterior desplegado (borra el historial y las columnas de asignación;
el agente actual de cada alerta se conserva). Las altas en empresa hechas al
asignar no se deshacen: se quitan a mano desde la ficha del agente.

```bash
# Tests (servicio con base de datos; rutas contra la app levantada)
docker exec moyza_backend python -m pytest tests/test_alert_assignment.py tests/test_alert_assignment_routes.py -q
```

## 10. Firma de los dos agentes en visitas conjuntas

Detalle en `PLAN_FIRMA_AGENTES_VISITA.md`. En una visita **con acompañante**,
tras la firma del cliente hay un paso nuevo, "Firmas de los agentes"
(`/visits/agent-signatures/{id}`): el usuario logueado en la tablet confirma
que la ficha se firma con las firmas **registradas** de los dos agentes (las
ve en miniatura). Queda guardado quién, cuándo y desde qué IP, más el evento
de auditoría `agent_signatures_confirmed`. Sin confirmar no se finaliza.

- Si un agente no tiene firma registrada, no se puede confirmar: o la
  registra (él mismo o el admin desde Agentes) o se pulsa "Quitar
  acompañante" y la visita se finaliza como individual (auditoría
  `companion_removed_before_confirmation`).
- El PDF de una visita conjunta lleva tres firmas con nombre (comprador,
  agente, acompañante) y "Firmas de agentes confirmadas el …" en los
  metadatos. La vista previa muestra los recuadros de firma. Las visitas
  individuales no cambian (mismo PDF de dos columnas, sin paso extra).
- Una visita conjunta que esté en `signed` al desplegar pasará por la
  confirmación al retomarla; las ya completadas no cambian. Si un agente
  cambia su firma registrada, los PDFs ya generados no cambian; regenerar
  uno usa la firma nueva.
- **Cambio de seguridad**: los endpoints `/api/v1/visits/{id}/accept-terms`,
  `save-signature`, `finalize` y el nuevo `confirm-agent-signatures` exigen
  la sesión de la app (401 sin cookie) y que la visita sea de la empresa
  activa (404). Antes no comprobaban nada; si alguna integración externa
  los llamaba sin sesión, dejará de funcionar. Las pantallas de la app no
  se ven afectadas (envían la cookie, mismo origen).

Despliegue (migración `x7y8z9a0b1c2_add_agent_signature_confirmation_to_visits`:
3 columnas nulas en `property_visits`, sin backfill; va después de
`w6x7y8z9a0b1_add_alert_indexes`, que se aplica en el mismo `upgrade` si
aún no estaba):

```bash
docker exec moyza_backend alembic upgrade head
docker restart moyza_backend
```

Rollback: `docker exec moyza_backend alembic downgrade w6x7y8z9a0b1` con el
código anterior desplegado (borra las confirmaciones guardadas; los PDFs ya
generados no cambian).

```bash
# Tests (unitarios sin base de datos; integración contra la app levantada)
docker exec moyza_backend python -m pytest tests/test_visit_agent_signatures.py -q
```

## 11. Teléfono del comprador con indicativo de país

Detalle en `PLAN_TELEFONO_COMPRADOR.md`. Los cuatro formularios de comprador
(nuevo comprador, comprador con criterios, comprador nuevo de "Nueva alerta" y
edición de contacto) piden el país (por defecto +34) y el número por separado
(macro `phone_field` de `components/phone_macros.html` + `static/js/phone-field.js`).
Se guarda `código + dígitos` sin `+` ("34600112233"), igual que las visitas;
si el agente repite el indicativo ("+34 600…", "0034…") se quita una vez y la
interfaz lo avisa antes de guardar. La parte local debe tener entre 6 y 12
dígitos; el teléfono sigue siendo opcional. Las rutas aceptan aún el campo
antiguo de texto libre (`phone` / `buyer_phone`) si llega solo.

- **Sin migración ni backfill.** Los teléfonos antiguos se siguen leyendo
  (`split_phone`, `phone_display`, `whatsapp_url`) y se editan con el país
  preseleccionado (los que no traen indicativo salen con +34 y el número
  completo, para que el agente lo revise). Guardar la ficha sin tocar el
  teléfono no lo reescribe.
- Script opcional para normalizar `buyers.phone` y `property_alerts.lead_phone`.
  Por defecto solo informa; con `--apply` reescribe solo los inequívocos
  (indicativo explícito, o 9 dígitos que empiezan por 6-9) y lista el resto
  para revisarlo a mano. Ejecutarlo es decisión del usuario tras ver el
  dry-run:

```bash
docker exec moyza_backend python scripts/normalize_buyer_phones.py            # dry-run
docker exec moyza_backend python scripts/normalize_buyer_phones.py --apply
```

- **Deuda (Visitas)**: `properties/visit_form.html` y `visits/edit_form.html`
  tienen su propio select de país y su copia del JS de acortado, y
  `routes/visits.py` compone el número a mano en `create_visit` y
  `update_visit`. Cuando se cierre el trabajo en curso sobre visitas, pasar a
  `phone.phone_field(...)`, cargar `phone-field.js` (y quitar el JS en línea)
  y usar `app.core.phone.phone_from_form` / `compose_phone`.

```bash
# Tests (unitarios sin base de datos; rutas contra la app levantada)
docker exec moyza_backend python -m pytest tests/test_phone.py tests/test_buyer_phone_routes.py -q
```

## 12. Avisos de compradores en horas hábiles (Jaén) y "sin avance"

> **Ajustado el 2026-10-19** (sección 15): R2 "sin avance" eliminada; nueva R3
> "volver a llamar" tras «Sin respuesta». R1 y el calendario hábil se mantienen.

Detalle en `PLAN_ALERTAS_DIAS_HABILES.md` (decisiones en su §4). Los avisos de
compradores pasan a contar **horas hábiles**: lunes a viernes, sin festivos
nacionales, de Andalucía (con los traslados al lunes) ni locales de Jaén
capital (11 de junio y 18 de octubre, `LocalHolidays` en `core/constants.py`,
cargados para 2026-2028; para 2029 hay que añadirlos). 48 h hábiles = dos días
hábiles completos a la misma hora: viernes 12:00 → martes 12:00 (miércoles si
el lunes es festivo).

- **R1 · Sin gestión**: 48 h hábiles desde la última gestión real (cualquier
  seguimiento, también «Sin respuesta») o desde la asignación.
- **R2 · Sin avance** (nuevo): 48 h hábiles sin pasar de **Primera llamada**
  (o sin etapa); «Sin respuesta» no reinicia este reloj. Las etapas
  siguientes no se vigilan.
- Una sola fila por comprador/alerta, con la causa más grave (R1 antes que R2).
- Canales: el email diario de siempre (ahora con dos secciones, "Sin gestión"
  y "Sin avance de etapa"), el Inicio (modal y "Hoy y pendiente" del agente,
  "Requiere atención" del admin), badge ámbar en `/alerts` con "Venció el …" y
  plazos "Vence el …" en el detalle, y notificaciones in-app
  `buyer_no_action` / `buyer_stage_stall`: una al cruzar el umbral y otra cada
  2 días hábiles mientras siga igual. Cuando dejan de aplicar (seguimiento,
  avance, cierre, reasignación o borrado) se **marcan leídas** (no se borran).
  Ningún WhatsApp; ningún email para el admin.

**Cambios que nota el equipo el día del despliegue (avisar antes):**

1. **Los agentes van a recibir avisos de alertas `IN_PROGRESS` que hasta ahora
   estaban en silencio.** Antes, con solo abrir la alerta (pasa a En proceso)
   dejaba de avisar para siempre; ahora se vigilan las abiertas y hay que
   registrar una gestión (R1) y avanzar de Primera llamada (R2). El primer
   email y la primera tanda de la campana pueden traer compradores antiguos.
2. El email diario cambia de hora y de calendario: de las 06:00 UTC todos los
   días a las **08:00 de Madrid solo en días hábiles** (cron de lunes a
   viernes con `timezone="Europe/Madrid"`; el servicio además se salta los
   festivos de Jaén).

Despliegue (sin migración de base de datos):

```bash
# Nueva dependencia `holidays` en requirements.txt: hay que reconstruir la imagen
docker compose build backend   # o el comando de build habitual del servidor
docker compose up -d backend
docker exec moyza_backend python -c "import holidays; print(holidays.__version__)"
```

Variables (todas opcionales; valores por defecto entre paréntesis):

- `BUYER_REMINDER_HOURS` (48): umbral de R1, ahora en **horas hábiles**.
- `BUYER_STAGE_STALL_HOURS` (48, nueva): umbral de R2 en horas hábiles.
- `BUYER_REMINDER_REPEAT_BUSINESS_DAYS` (2, nueva): cada cuántos días hábiles
  se repite el aviso in-app.
- `BUYER_REMINDER_HOUR` (8): **ahora es hora de Madrid** (antes 6 en UTC). Si
  el `.env` de producción la fija a 6, quitarla o poner 8.
- `BUYER_REMINDER_ENABLED` (true): apaga el email y los avisos in-app de este job.

Rollback: desplegar el código anterior y reiniciar; no hay cambios de
esquema. Las notificaciones `buyer_*` que queden se ven como un tipo
desconocido (icono de campana) y se limpian a los 90 días una vez leídas.

Prueba manual del job con fecha simulada y sin enviar correos (Gmail falso):

```python
# docker exec -it moyza_backend python
import app.db.base
from datetime import datetime
from app.core.business_calendar import to_utc
from app.jobs.scheduler import send_buyer_reminders
class FakeGmail:
    def send_email(self, to, subject, body): print(to, subject); return True
send_buyer_reminders(now=to_utc(datetime(2026, 11, 3, 8, 0)), gmail_service=FakeGmail())
# OJO: escribe alert_reminder_logs y notificaciones reales con esa fecha
```

```bash
# Tests (calendario sin base de datos; servicio y canales con base de datos; ruta contra la app levantada)
docker exec moyza_backend python -m pytest tests/test_business_calendar.py tests/test_buyer_attention_service.py tests/test_buyer_attention_channels.py -q
```

## 13. Pendientes conocidos

- Datos legales y logo reales de MOES PREMIUM (sección 4).
- Eliminar las columnas heredadas `users.company` y `agents.company` cuando ya
  no las lea nada.
- `/activity-logs` no filtra por empresa a propósito: la actividad de
  usuarios no es un dato de empresa.
- Vista consolidada "Todas las empresas" para el admin: descartada en esta
  versión, pendiente de decidir.

## 14. Ficha de visita: envío por WhatsApp desactivado (2026-10-18)

La ficha firmada ya no se envía por WhatsApp al comprador, ni al finalizar la
visita ni con el botón "Enviar" (que deja de mostrarse). El PDF se genera y se
descarga igual. Cada finalización deja una fila `SKIPPED` en
`visit_whatsapp_logs` con el motivo "Envío por WhatsApp desactivado".

Para reactivarlo: `VISIT_SHEET_WHATSAPP_ENABLED=true` en el `.env` y reiniciar.
No hay cambios de código ni de base de datos. Los envíos de informes a
propietarios no se ven afectados.

## 15. Recordatorio "volver a llamar" tras «Sin respuesta» y menos etapas (2026-10-19)

Detalle en `PLAN_RECORDATORIO_SIN_RESPUESTA.md`. Ajusta la sección 12:

- **R1 · Sin gestión** se mantiene igual (48 h hábiles sin ninguna gestión
  real, aviso al cruzar y cada 2 días hábiles).
- **R2 · Sin avance de Primera llamada**: eliminada.
- **R3 · Volver a llamar** (nueva, con prioridad): si el último seguimiento
  real es «Sin respuesta», a las **24 h hábiles** se avisa al agente; un aviso
  por intento, **máximo 3**; el tercero pide cerrar la alerta como «Sin
  interés». A partir del cuarto «Sin respuesta» la alerta vuelve a R1 (48 h
  hábiles). Una alerta solo cae en una regla a la vez.
- Formulario de seguimiento: ya **no ofrece "Primera llamada" ni
  "Calificado"** (y un POST con esos valores se rechaza). Los registros
  antiguos se siguen viendo con su etiqueta y color. Guardar el perfil de
  búsqueda desde la alerta crea un seguimiento **"Perfil guardado"** (antes
  "Calificado"): cuenta como gestión, no avanza la etapa.

**Cambios que nota el equipo el día del despliegue (avisar antes):**

1. La **campana** cambia de contenido: desaparece "Comprador sin avanzar" y
   aparece "Vuelve a llamar · {comprador}" (intento N de 3). Las de "sin
   avance" que quedaran sin leer se marcan leídas con la migración.
2. El **email diario** (08:00 Madrid, días hábiles) pasa a tener las secciones
   "Pendientes de volver a llamar" y "Sin gestión" (desaparece "Sin avance de
   etapa"). Sigue sin haber email para el admin y ningún WhatsApp.
3. Nuevo job **horario solo in-app** (`notify_buyer_callbacks`, minuto 15,
   hora de Madrid) para que el aviso "volver a llamar" llegue a la campana al
   vencer el plazo y no al día siguiente. No envía emails.
4. Inicio: "N pendientes de volver a llamar · M sin gestión" (agente y admin);
   `/alerts`: badge "Volver a llamar · intento N de 3" (rojo el tercero) o
   "Sin gestión"; detalle con "Venció el …".

Despliegue (migración **solo de datos**, sin cambios de esquema):

```bash
docker exec moyza_backend alembic upgrade head      # z9a0b1c2d3e4: marca leídas las buyer_stage_stall
docker restart moyza_backend
```

Variables:

- `BUYER_STAGE_STALL_HOURS`: **desaparece** (si está en el `.env`, quitarla;
  ya no se lee).
- `BUYER_CALLBACK_HOURS` (24, nueva): horas hábiles tras «Sin respuesta».
- `BUYER_CALLBACK_MAX_ATTEMPTS` (3, nueva): intentos que avisan.
- Sin cambios: `BUYER_REMINDER_HOURS` (48), `BUYER_REMINDER_REPEAT_BUSINESS_DAYS`
  (2), `BUYER_REMINDER_HOUR` (8), `BUYER_REMINDER_ENABLED` (true; apaga también
  el job horario).

Rollback: desplegar el código anterior y reiniciar. La migración no tiene
downgrade útil (las notificaciones marcadas leídas se quedan leídas). Los
seguimientos "Perfil guardado" creados mientras tanto se verían con su código
en crudo en el código anterior.

```bash
# Tests (servicio y canales con base de datos; rutas en SQLite en memoria o contra la app levantada)
docker exec moyza_backend python -m pytest tests/test_buyer_attention_service.py tests/test_buyer_attention_channels.py tests/test_alert_search.py -q
```
