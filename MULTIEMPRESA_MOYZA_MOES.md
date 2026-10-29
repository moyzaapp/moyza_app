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
- Excepciones al aislamiento (lista cerrada, detalle en la sección 16): en
  `/properties?tab=other_company` todos los roles ven, en solo lectura, las
  propiedades activas y disponibles de la otra empresa (sin propietario ni
  enlace al detalle); y las sugerencias del perfil del comprador salen de las
  dos empresas, con distintivo, y se pueden asociar a la alerta. Nada más de
  la otra empresa se expone.

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

La migración `r1s2t3u4v5w6` creó MOES PREMIUM con los datos legales de MOYZA
de forma provisional. **Los reales los pone la migración de datos
`d3e4f5a6b7c8_moes_company_data` (2026-10-28, ver §20)**: razón social
"MOES 2024 S.L.U.", CIF B70662390, teléfono 722 877 402, logo
`/static/logo_moes.png` y domicilio fiscal "Avenida de Madrid 37, 23009 Jaén",
que también pasa a ser el de MOYZA. Cualquier cambio posterior se hace igual,
con una migración de datos o con un UPDATE como este:

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

- Texto RGPD propio de MOES PREMIUM (hoy es el de MOYZA con el nombre
  cambiado; los datos legales y el logo ya son los reales, §4 y §20).
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

## 16. Excepciones: qué cruza empresas (2026-10-20)

Detalle en `PLAN_SUGERENCIAS_MULTIEMPRESA.md`. Las propiedades **sugeridas**
por el perfil del comprador salen de **las dos empresas**, no solo de la
activa, y cada una lleva el distintivo de su empresa (badge neutro con el
punto de `companies.primary_color`, macro `ui.company_badge`). Es una
excepción consciente y acotada. Lo **único** que cruza:

| Qué | Dónde | Código |
|---|---|---|
| Sugerencias del perfil | Paso Propuesta de la alerta y pestaña "Propiedades compatibles" de la ficha del comprador | `buyer_matching.matching_properties(_query)` sin `company_id` (con él: filtro "Solo {empresa}", `?company=active`); desglose `matching_summary_by_company` ("12 propiedades sugeridas · 8 MOYZA · 4 MOES PREMIUM") |
| Opciones del perfil | Cascada País → Provincia → Población → Zona y tipos de inmueble | `buyer_matching.geo_options(db)` y `_property_filter_values(db, criteria)` en `routes/alerts.py` |
| Buscador manual de la Propuesta | "¿No está en la lista?" / "Buscar una propiedad" | `/alerts/search-properties` **solo con `alert_id`** de una alerta de la empresa activa que el usuario puede trabajar; cada resultado lleva `company` |
| Asociar / cambiar propiedad | `/alerts/{id}/link-property` y el aviso de duplicado | `_linkable_property` (sin `get_property_in_company`); exige no archivada y disponible |

Reglas:

- `alert.company_id` **no cambia** al asociar una propiedad de la otra
  empresa: la alerta sigue en la empresa donde se captó al comprador (listado,
  cola, métricas, recordatorios y reasignación siguen yendo por ella). El
  seguimiento `PROPIEDAD_ASOCIADA` nombra la empresa cuando no es la de la
  alerta: "Propiedad asociada: Piso en Martos (MOES PREMIUM)".
- Duplicados al asociar (`find_duplicate_alerts`): por la empresa de la alerta.
- Enlace "Ver" a la ficha: solo si la propiedad es de la empresa activa y
  (admin o propiedad del propio agente). Si es de la otra y el rol la podría
  ver, "Cambia de empresa para ver la ficha".
- La tarjeta de la propiedad asociada (detalle de la alerta) y la columna
  Propiedad de `/alerts` y de la ficha del comprador muestran el distintivo
  cuando la propiedad no es de la empresa activa.
- En "Propiedades compatibles" de la ficha del comprador, una propiedad de la
  otra empresa no ofrece "Crear alerta" (el alta con referencia sigue
  limitada): se asocia desde la alerta.

**No cruza** (sigue limitado a la empresa activa): el modal de creación de
alertas con referencia y su buscador (`/alerts/search-properties` sin
`alert_id`), `/alerts/create`, la ficha de propiedad (`/properties/{id}` da
"no encontrada"), visitas, informes, métricas y listados de propiedades.

Sin migración ni variables nuevas: desplegar el código y reiniciar.

```bash
# Tests (rutas y servicios en SQLite en memoria)
docker exec moyza_backend python -m pytest tests/test_sugerencias_multiempresa.py tests/test_alert_search.py -q
```

## 17. Avisos de compradores solo para alertas asignadas desde el 20/10/2026 (2026-10-26)

Las alertas antiguas que nadie cerró llenaban la campana, el email diario y el
Inicio de avisos "Sin gestión" y "Volver a llamar". Decisión: **sin borrar
ninguna alerta**, los avisos (R1 y R3, secciones 12 y 15) solo cuentan las
alertas cuya ventana de asignación (`assigned_at`, o `created_at` si falta)
empieza el **20/10/2026 a las 00:00 de Madrid** o después.

- Un único punto: `buyer_attention_service` (`alert_clock`, que usan
  `evaluate_alert(s)` y el detalle, y el filtro SQL de
  `find_buyers_needing_attention`). Por ahí pasan el badge de `/alerts`, el
  banner "Venció / Vence el …" del detalle, el Inicio ("Hoy y pendiente",
  "Requiere atención"), el email diario, el job horario de "volver a llamar"
  y la campana. Una alerta anterior al corte no tiene reloj en ningún sitio.
- Una alerta antigua **reasignada** después del corte vuelve a avisar: la
  reasignación pone `assigned_at` a la fecha de reasignación y cuenta desde
  ahí, como ya ocurría (sección 9).
- No cambia: la cola secuencial, "Compradores abandonados" (PENDING > 7 días)
  ni las métricas; las alertas antiguas siguen en los listados y **se cierran
  a mano** como siempre.

Variable nueva:

- `BUYER_ATTENTION_SINCE` (`2026-10-20` por defecto, formato `YYYY-MM-DD`):
  vacía o inválida = sin corte (comportamiento anterior). Para moverla basta
  con cambiar el `.env` y reiniciar.

Despliegue (migración **solo de datos**, sin cambios de esquema):

```bash
docker exec moyza_backend alembic upgrade head      # b1c2d3e4f5a6: marca leídas las notificaciones de compradores de alertas anteriores al corte
docker restart moyza_backend
```

La migración marca `read_at` en las notificaciones sin leer `buyer_no_action`,
`buyer_callback_due` y `buyer_stage_stall` de alertas con
`coalesce(assigned_at, created_at)` anterior al 20/10/2026 00:00 de Madrid. No
borra nada. Downgrade vacío: lo marcado como leído se queda leído.

Rollback: `BUYER_ATTENTION_SINCE=` (vacía) en el `.env` y reiniciar; o
desplegar el código anterior. Las notificaciones marcadas leídas no vuelven.

```bash
# Tests (unitarios, consulta y SQL de la migración en una transacción que se deshace)
docker exec moyza_backend python -m pytest tests/test_buyer_attention_service.py tests/test_buyer_attention_channels.py -q
```

## 18. Trazabilidad de indicadores para el admin (2026-10-26)

PLAN_TRAZABILIDAD_INDICADORES.md. Sin migración y sin variables de entorno
nuevas. Solo admin: lupa en cada tarjeta de Resultados Comerciales →
Rendimiento que abre un panel lateral con la regla en una frase, los totales
(congelado frente a recalculado en períodos cerrados, con aviso si difieren) y
los registros que suman, con enlace al origen y descarga CSV. Ruta nueva
`GET /commercial-results/{agente}/metric/{clave}` (`?format=csv`, `?offset=`),
siempre dentro de la empresa activa (agente de otra empresa → 404; no admin →
403). El contador y el detalle comparten la misma consulta, y un test por
indicador comprueba que el número de filas coincide con la tarjeta.

Tras desplegar: recompilar Tailwind (lo hace el build de Docker) y reiniciar.

Nota conocida: las fechas de las filas se muestran en hora de Madrid, pero el
período se corta en UTC (regla previa del contador). Un registro de las 22:00
a 24:00 UTC del último día puede verse con fecha del día siguiente en el panel.

## 19. Ceder compradores entre agentes e historial de cesiones (2026-10-28)

PLAN_CEDER_COMPRADORES.md §5 y §7. Migración `c2d3e4f5a6b7` (sin
dependencias ni variables de entorno nuevas): `alert_assignment_logs.kind`
(`created` / `reassigned` / `ceded`, NOT NULL con valor por defecto
`reassigned`; las filas sin agente de origen pasan a `created`) y
`property_alerts.ceded_at` + `ceded_by_agent_id` (FK a agents, ON DELETE SET
NULL). Downgrade limpio (borra las tres columnas).

- El agente de una alerta abierta puede **cederla** (`POST /alerts/{id}/cede`,
  desde el detalle o la acción de fila del listado) a otro agente **de la
  empresa de la alerta**, con motivo obligatorio y la casilla del aviso de
  comisión, mientras no venza su reloj de atención (R1 / R3; sin reloj por el
  corte del §17, 48 h hábiles desde la asignación). Vencido, el botón sale
  desactivado: "El plazo para ceder ha vencido: pide a un administrador que la
  reasigne". Efectos de una reasignación (Pendiente, sin leer, reloj de cero,
  avisos del anterior resueltos) y aviso "Te han cedido un comprador" al nuevo.
- Distintivo «Cedido» en el listado y el detalle (admin y receptor); el
  receptor ve quién y cuándo, no el motivo. Una reasignación posterior del
  admin quita la marca.
- Admins de la empresa: notificación `alert_ceded` (queda en `/notifications`),
  bloque "Cesiones recientes" (7 días) en su Inicio y página
  `GET /alerts/assignments` (solo admin, empresa activa) con el historial de
  altas, reasignaciones y cesiones, filtros y resumen por agente. Nada por email.

Tras desplegar: `alembic upgrade head`, recompilar Tailwind (lo hace el build de
Docker) y reiniciar.

## 20. Datos legales reales de MOES PREMIUM (2026-10-28)

Migración de datos `d3e4f5a6b7c8_moes_company_data` (sin cambios de esquema,
idempotente, downgrade a los valores de la siembra):

| Empresa | Campo | Valor |
|---|---|---|
| MOES | `legal_name` | MOES 2024 S.L.U. |
| MOES | `tax_id` | B70662390 |
| MOES | `phone` | 722 877 402 |
| MOES | `logo_path` | `/static/logo_moes.png` (1254×1254, ya en el repo) |
| MOES y MOYZA | `fiscal_address` | Avenida de Madrid 37, 23009 Jaén |

Lo usan la ficha de visita (cabecera con logo, texto legal con razón social,
CIF y domicilio) y la vista previa que se firma. Los PDF ya generados no se
regeneran. El texto RGPD de MOES sigue siendo el de MOYZA con el nombre
cambiado (§13).

Tras desplegar: `alembic upgrade head` (aplica `d3e4f5a6b7c8`); no hace falta
tocar nada a mano en producción.
