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
(`companion_agent_id`). Ambos deben ser agentes de la empresa activa.

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

## 8. Pendientes conocidos

- Datos legales y logo reales de MOES PREMIUM (sección 4).
- Eliminar las columnas heredadas `users.company` y `agents.company` cuando ya
  no las lea nada.
- `/activity-logs` y el dashboard de admin no filtran por empresa a propósito:
  la actividad de usuarios no es un dato de empresa.
- Vista consolidada "Todas las empresas" para el admin: descartada en esta
  versión, pendiente de decidir.
