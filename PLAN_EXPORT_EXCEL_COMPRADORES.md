# Plan: Excel de compradores para administración

Fecha: 2026-11-23. Petición: «Excel descargable para administración, filtrado
por fecha, con los compradores que han ingresado, las alertas que han generado
y cosas así. Algo sencillo».

## 1. Decisiones (confirmadas por el usuario el 2026-11-23)

- **D1** Filtro por fecha de creación (alta) de compradores y de alertas: «los
  que entran» en el periodo. Rango Desde / Hasta inclusivo, en días de Madrid.
- **D2** Tres hojas: «Resumen», «Compradores» y «Alertas». Sin hoja de
  seguimientos.
- **D3** Solo la empresa activa del selector del admin (como el resto del admin).
- **D4** Solo admin. Un agente recibe la misma respuesta que en otras vistas
  solo-admin (redirección con flash «Acceso denegado»).
- Formato `.xlsx` real con `openpyxl` (nueva dependencia en `requirements.txt`).
  El CSV de Resultados Comerciales no se toca.

## 2. Diseño

### 2.1 Ruta (`app/web/routes/alerts.py`)

`GET /alerts/export.xlsx?desde=YYYY-MM-DD&hasta=YYYY-MM-DD`

- Dependencia `require_admin_role` (propagar su `RedirectResponse` como hacen
  las demás rutas admin del fichero).
- Empresa: `get_active_company(request)`.
- `desde` / `hasta` opcionales; por defecto el mes en curso (día 1 a hoy, en
  `madrid_today()`). Si `desde > hasta`, se intercambian. Fecha inválida →
  303 a `/alerts` con flash de error.
- Rango UTC: `to_utc(datetime.combine(desde, time.min))` ≤ `created_at` <
  `to_utc(datetime.combine(hasta + 1 día, time.min))` (`app/core/business_calendar`).
- Respuesta: `Response(content=bytes, media_type=
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")` con
  `Content-Disposition: attachment; filename="compradores_{company.code.lower()}_{desde}_{hasta}.xlsx"`.
- La ruta debe declararse **antes** de `GET /alerts/{alert_id}` para que
  `export.xlsx` no se interprete como id (revisar el orden en el fichero;
  `/alerts/search-buyers` y `/alerts/check-buyer` ya resuelven esto igual).

### 2.2 Servicio nuevo `app/services/buyer_export_service.py`

```python
def build_buyers_workbook(db, company, start: date, end: date) -> bytes
```

Consultas (todas filtradas por `company_id == company.id`):

- Compradores: `Buyer` con `created_at` en el rango, con `search_criteria`
  (selectinload) y, para la columna «Alertas», el recuento de `PropertyAlert`
  del comprador en la empresa (todas, no solo las del periodo) y la fecha de
  la última.
- Alertas: `PropertyAlert` con `created_at` en el rango, con `buyer`,
  `property`, `agent`, `follow_ups` (selectinload), ordenadas por `created_at`.
- Nombre de quien creó el comprador: `created_by` → `User.name` (o email).

**Hoja «Resumen»** (dos columnas Concepto / Valor, sin fórmulas):

- Empresa, Periodo (dd/mm/aaaa – dd/mm/aaaa), Generado el (hora de Madrid).
- Compradores nuevos; Alertas nuevas; Alertas con referencia / búsqueda
  general (`AlertOrigin`).
- Bloque «Alertas por fuente» (`source`, vacío → «Sin fuente»), ordenado por
  cantidad desc.
- Bloque «Alertas por agente» (`agent.name`, sin agente → «Sin asignar»).
- Bloque «Alertas por etapa actual» (etiqueta de etapa, sin seguimientos →
  «Sin iniciar»).

**Hoja «Compradores»** (una fila por comprador del periodo):

Fecha de alta · Nombre · Teléfono · Email · Creado por · Alertas (nº total)
· Última alerta (fecha) · Tipo de negocio · Tipo de inmueble · Provincia ·
Zonas/ciudades · Presupuesto mín. · Presupuesto máx. · Notas.
Criterios de `BuyerSearchCriteria`: `business_type`, `property_types` (JSON;
si vacío, `property_type`), `province`, `cities` + `zones` unidos por «, »,
`min_price`, `max_price`. Sin criterios → celdas vacías.

**Hoja «Alertas»** (una fila por alerta del periodo):

Fecha · Comprador (`lead_name`, o `buyer.name` si existe) · Teléfono · Email
· Origen («Con referencia» / «Búsqueda general») · Referencia (propiedad
`reference`) · Propiedad (título/dirección corta) · Fuente (`source`) ·
Agente · Etapa actual · Estado (`AlertStatus` → Pendiente / En curso /
Completada / Cancelada; usar las etiquetas existentes si las hay) · Última
gestión (fecha del último seguimiento real) · Nº gestiones · Fecha de cierre
(`completed_at`) · Cedida («Sí» si `ceded_at`).

Etapa actual = la misma regla que el listado del admin
(`alerts.py` ~línea 901): último seguimiento real
(`alert_view.real_follow_ups_since(alert.follow_ups, None)`) que no esté en
`FollowUpActionType.REPEATABLE_ACTIONS`; si solo hay repetibles, el último de
ellos; etiqueta con `FollowUpActionType.labels()`. Extraer esa regla a una
función `current_stage(follow_ups, since)` en `app/services/alert_view.py` y
usarla desde la ruta del listado y desde el export (sin cambiar el
comportamiento del listado).

Formato: cabecera en negrita con relleno gris claro, fila fija
(`freeze_panes`), autofiltro, anchos de columna razonables (sin medir texto),
fechas como `datetime` con `number_format = "dd/mm/yyyy hh:mm"` (hora de
Madrid, `to_madrid`), importes como número con `#,##0`. Nada de estilos
corporativos; es un documento de trabajo.

### 2.3 Botón en el listado (`app/web/templates/alerts/list.html`)

Solo `admin_view`, en la cabecera de la sección de alertas junto a los
filtros. Botón secundario «Exportar Excel» con icono de descarga que abre un
modal `exportExcelModal` (`ui.modal`) con un formulario `GET
/alerts/export.xlsx`: dos campos de fecha `desde` / `hasta` (inputs `date`,
`required`, por defecto el día 1 del mes y hoy, pasados desde la ruta del
listado como `export_default_from` / `export_default_to` en ISO) y
`ui.modal_footer(submit_label="Descargar")`. Nota en texto pequeño: «Incluye
los compradores y alertas dados de alta en ese periodo en {{ company.name }}».
Sin JS nuevo: el GET descarga el fichero y el modal se cierra con el cierre
normal. Seguir el skill `moyza-ui-ux-pro` (componentes `ui.*`, clases
Tailwind ya compiladas: comprobar que las clases usadas existen en el CSS
compilado o reutilizar botones ya presentes en la plantilla).

### 2.4 Dependencia

`requirements.txt`: `openpyxl>=3.1`. En local ya está instalada en el
contenedor (`pip install openpyxl`); en producción se reconstruye la imagen.

### 2.5 Tests

- `tests/test_buyer_export.py` (nuevo), con el patrón de `tests/test_metric_detail.py`
  (cliente `Client(ADMIN_EMAIL, "MOYZA")`, fixtures de empresa/agente/alertas):
  - admin descarga: 200, `content-type` xlsx, `Content-Disposition` con el
    nombre esperado; el libro (abrir con `openpyxl.load_workbook(BytesIO)`)
    tiene las tres hojas con las cabeceras del diseño.
  - filtro por fecha: un comprador y una alerta dentro del rango aparecen, otros
    fuera no; `hasta` es inclusivo (alerta a las 23:30 de Madrid de ese día).
  - empresa activa: una alerta de MOES no sale en el export de MOYZA.
  - agente: redirección 303 (como `require_admin_role`).
  - `desde > hasta` se intercambia; fecha inválida → 303 a `/alerts`.
  - etapa actual: alerta con CONTACTADO y luego SIN_RESPUESTA muestra
    «Contactado»; alerta sin seguimientos «Sin iniciar».
  - Resumen: los totales coinciden con las filas de las otras hojas.
- `tests/test_alerts_unmanaged_filter.py` o el test del listado existente:
  el admin ve el botón «Exportar Excel» y el agente no.

### 2.6 Documentación

- `MULTIEMPRESA_MOYZA_MOES.md` §15 (despliegue): nueva dependencia
  `openpyxl`, reconstruir imagen.

## 3. Fases

1. Servicio + ruta + `current_stage` en `alert_view` + `requirements.txt` +
   tests del servicio/ruta (un agente).
2. Botón y modal en `alerts/list.html` + contexto de la ruta del listado +
   test de visibilidad del botón + nota de despliegue (otro agente, en
   paralelo; la URL y los nombres de parámetros son los de §2.1 y §2.3).
3. Revisión del diff, suite completa y smoke con datos demo.

### Estado

- [x] Fase 1 (2026-11-23): `openpyxl>=3.1` en `requirements.txt`; `alert_view.current_stage(follow_ups, since)` usada por `alerts_page` y el export; servicio `buyer_export_service.build_buyers_workbook`; ruta `GET /alerts/export.xlsx` (antes de `/alerts/{alert_id}`); `tests/test_buyer_export.py` (10 tests). Desviaciones: estado con las etiquetas existentes (`alert_duplicate_service.STATUS_LABELS`: «En proceso», no «En curso»); «Referencia» = `Property.referencia` (no hay `reference`) y «Propiedad» = `title · calle`; «Creado por» = `User.full_name` (o email); Comprador = `buyer.name` si hay comprador, si no `lead_name`, y teléfono/email de la alerta con el del comprador como respaldo; el Resumen separa «Alertas con referencia» y «Alertas de búsqueda general» en dos filas; un agente recibe 303 a `/clients` (lo que hace `require_admin_role`).
- [x] Fase 2 (2026-11-23): botón y modal `exportExcelModal` en `alerts/list.html` (`data-modal-open`, nota con `active_company.name`), `export_default_from/to` en `alerts_page`, test de visibilidad en `test_alerts_unmanaged_filter.py`, nota de despliegue en `MULTIEMPRESA_MOYZA_MOES.md` §15. Verificado a 375 px y 1280 px sin desbordamiento.
- [x] Fase 3 (2026-11-23): revisión del diff con dos defectos corregidos (textos que empiezan por
      «=» se guardaban como fórmula; un carácter de control en notas rompía el export con 500):
      `_append` en el servicio limpia `ILLEGAL_CHARACTERS_RE` y fuerza texto literal. Menores:
      año fuera de 2000–2100 → flash en vez de `OverflowError`; `source` con `strip()` también en
      la hoja «Alertas»; test del límite inferior en hora de Madrid. Suite completa: 1416 pasan
      (deseleccionados dos fallos ajenos: `test_agente_no_puede_elegir_agente` y
      `test_admin_home_kpis_equipo_cumplimiento_y_atencion`, este último por los objetivos
      semanales de los agentes demo cargados esta semana). Descarga real comprobada como admin
      con los datos demo; agente demo redirigido.

## 4. Fuera de alcance

- Export para agentes, varias empresas en un fichero, hoja de seguimientos,
  filtro por fecha de última gestión o de cierre.
- Gráficos o fórmulas en el libro.

## 6. Cambio 2026-11-24: filtro por agente y solo la hoja «Compradores»

Petición: «un filtro que sea agente, y que pueda seleccionar varios o todos»
y «exportar solo la hoja de compradores por el momento».

### 6.1 Decisiones

- **D6** El libro lleva solo la hoja «Compradores». Las hojas «Resumen» y
  «Alertas» se retiran del código (quedan en el historial de git si vuelven a
  hacer falta); sus tests también.
- **D7** Filtro «Agentes» en el modal: lista de casillas con todos los agentes
  activos de la empresa activa (`scope_active_agents`, orden por nombre) y una
  casilla «Todos» marcada por defecto que marca/desmarca el resto. Parámetro
  repetido `agente=<id>`; sin ninguno = todos (sin filtro). Ids que no sean
  agentes activos de la empresa se ignoran.
- **D8** Un comprador «es» de un agente con la misma regla que usa la app para
  que el agente lo vea (`alerts.visible_buyers_query`): lo creó el usuario del
  agente (`Buyer.created_by` = usuario con el email del agente), o es el agente
  de su perfil (`BuyerSearchCriteria.agent_id`), o tiene alguna alerta de la
  empresa asignada a él (`PropertyAlert.agent_id`, cualquier estado y fecha).
  Con varios agentes marcados, basta con que cumpla con uno.
- **D9** Nueva columna «Agentes» en la hoja, tras «Creado por»: nombres de los
  agentes de la empresa que cumplen D8 con ese comprador, separados por «, »
  (vacío si ninguno). Así se ve a quién pertenece cada fila también sin filtro.

### 6.2 Diseño

- Servicio: `build_buyers_workbook(db, company, start, end, agent_ids=None)`.
  Si `agent_ids` (lista no vacía), filtra con `Buyer.id.in_(...)` sobre la
  unión de las tres condiciones de D8. Para la columna D9, tres consultas
  agrupadas (no N+1): alertas por `(buyer_id, agent_id)` de la empresa,
  criterios `(buyer_id, agent_id)`, y `created_by` → agente por email
  (`Agent.email == User.email`, solo agentes de la empresa). Quitar
  `_alerts`, `_alert_row`, `_summary_rows`, `ALERT_COLUMNS`, `SUMMARY_COLUMNS`
  y constantes que ya no se usen; `_append` y `_write_sheet` se quedan.
- Ruta `GET /alerts/export.xlsx`: nuevo `agente: List[str] = Query(default=[])`;
  convierte a int, descarta los que no estén en `scope_active_agents(company)`;
  pasa `agent_ids`. Nombre del fichero sin cambios.
- Listado (`alerts_page`): pasar `export_agents` (activos de la empresa, por
  nombre; ya existe `agents` para el filtro del listado, reutilizar).
- Modal (`alerts/list.html`): bajo las fechas, bloque «Agentes» con casilla
  «Todos» (`id="exportAgentsAll"`, marcada) y una casilla por agente
  (`name="agente" value="{{ a.id }}"`), en una rejilla de 1–2 columnas con
  scroll si hay muchos (`max-h-48 overflow-y-auto`, comprobar que existen en
  el CSS compilado). JS mínimo inline en la plantilla (o en el JS de la
  página si ya hay uno): «Todos» marcado → desmarca y deshabilita las demás;
  desmarcado → las habilita; si el admin desmarca todas, vuelve a «Todos».
  Nota: «Incluye los compradores dados de alta en ese periodo en {{ empresa }}».
- Tests `tests/test_buyer_export.py`: quitar los de Resumen/Alertas; libro con
  una sola hoja; columna «Agentes»; `?agente=<id>` deja solo los compradores
  de ese agente (uno por alerta, otro por `created_by`, otro por criterios) y
  excluye al resto; dos `agente=` suman; `agente` inválido o de otra empresa
  se ignora (= todos). `test_alerts_unmanaged_filter.py`: el modal lista a
  los agentes activos de la empresa con la casilla «Todos».
- Docs: `MULTIEMPRESA_MOYZA_MOES.md` §15 no cambia (misma dependencia).

### 6.3 Estado

- **D10** (2026-11-24, petición del usuario durante la Fase A): sin las columnas «Creado por»,
  «Alertas» ni «Última alerta»; «Agentes» va tras «Email». La regla D8 no cambia (el caso
  `created_by` → agente por email sigue contando para el filtro y para «Agentes»). Cabeceras:
  Fecha de alta · Nombre · Teléfono · Email · Agentes · Tipo de negocio · Tipo de inmueble ·
  Provincia · Zonas/ciudades · Presupuesto mín. · Presupuesto máx. · Notas.
- [x] Fase A (2026-11-24): `build_buyers_workbook(db, company, start, end, agent_ids=None)`
  con solo «Compradores» (fuera `_alerts`, `_alert_row`, `_summary_rows`, `_property_text`,
  `_user_names`, `_alert_counts` y constantes); D8 como subconsultas en `_agent_filter` y D9
  con tres consultas agrupadas en `_buyer_agents` (agentes de la empresa, también de baja,
  nombres ordenados); ruta con `agente: List[str]` (no numéricos, ≥ 2³¹, inactivos o de otra
  empresa se ignoran); `tests/test_buyer_export.py` 21 pasan. Desviaciones: D8 cuenta alertas
  de cualquier estado como dice §6.1 (`visible_buyers_query` solo cuenta las no PENDING);
  `hasta` inclusivo se prueba ahora con un comprador a las 23:30 (ya no hay «Última alerta»).
- [x] Fase B (2026-11-24): `export_agents` en `alerts_page` (reutiliza `agents`); bloque «Agentes» en `exportExcelModal` con «Todos» y JS inline al final de `alerts/list.html` (solo admin); test de visibilidad ampliado. Verificado a 375 px y 1280 px sin desbordamiento.
- [x] Fase C (2026-11-24): revisión con un defecto corregido (`agente=²` o una cadena de
      miles de cifras daba 500: ahora solo cifras ASCII de hasta 10 dígitos) y dos menores
      (columna «Agentes» por ids para no fundir homónimos; comentario de test). Suite completa
      1428 pasan (dos fallos ajenos deseleccionados). Smoke como admin con datos demo: una sola
      hoja con las cabeceras de D10; un agente filtra, dos suman, valores inválidos = todos.
