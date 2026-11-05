# Plan: cierres registrados a mano y direcciones solo de la propia empresa

Fecha: 2026-11-04. Rama `63-agregar-moes`. Dos peticiones independientes.

## 1. Situación actual

### 1.1 Cierres

- La métrica **Cierres** de Inicio y de Resultados Comerciales cuenta los seguimientos «Cerrado» de
  las alertas de comprador (`AlertFollowUp.action_type == CERRADO`) del agente de la alerta,
  dentro de la empresa, con desglose venta / alquiler por el tipo de la alerta o de la propiedad
  (`performance_report_service._indicator_spec("cierres")`).
- Se ve en: tarjeta "Cierres" de Rendimiento (con objetivo mensual y anual `target_cierres`),
  gráfica de Evolución, tabla "Cumplimiento del equipo" y anillo del agente en Inicio, actividad
  reciente del Inicio del admin ("Cierre · comprador"), lupa de trazabilidad (filas + CSV) y
  snapshots congelados (`agent_performance_reports.cierres/_venta/_alquiler`).
- El usuario aclara que un cierre es **la firma o venta de una propiedad**, no el cierre de una
  alerta. Más adelante saldrá de una sección de operaciones; por ahora se registra a mano. El
  objetivo (`target_cierres`) no cambia: lo manual es el **resultado**.

### 1.2 Direcciones de la otra empresa

Hoy la dirección (ya sin número, filtro `street`) de una propiedad de la otra empresa la ve
cualquier agente en:

| Dónde | Archivo |
|---|---|
| Pestaña "Propiedades de {otra empresa}" | `properties/table_others.html`, `routes/properties.py::_readonly_property_rows` |
| Sugerencias del perfil (tarjetas de las dos empresas) | `components/property_card.html` |
| Buscador "Asociar propiedad" del paso Propuesta (JSON, dos empresas) | `routes/alerts.py` búsqueda `address: p.street` |
| Detalle de alerta con propiedad de la otra empresa | `alerts/detail.html` |
| Listado de alertas y ficha del comprador | `alerts/list.html`, `buyers/detail.html` |
| Visitas en las que acompaña a un agente de la otra empresa | `visits/preview.html`, `complete.html`, PDF |

## 2. Diseño propuesto

### 2.1 Cierres manuales

- **Tabla nueva `closings`** (migración tras `f5a6b7c8d9e0`): `id`, `company_id`, `agent_id`,
  `business_type` ("Venta" / "Alquiler"), `closed_on` (fecha), `property_id` opcional
  (FK `ON DELETE SET NULL`), `notes` opcional, `created_by`, `created_at`. Un registro por
  cierre y por agente.
- **Métrica**: `cierres` pasa a contar registros de `closings` por `agent_id`, `company_id` y
  `closed_on` en el período; desglose por `business_type`. La lupa de trazabilidad lista los
  cierres (fecha, tipo, propiedad, nota) y el CSV igual. La explicación de la regla cambia a
  "cierres registrados por el administrador". El seguimiento «Cerrado» sigue cerrando la alerta
  pero deja de contar.
- **Pantalla (solo admin)**: en Resultados Comerciales, nueva pestaña **Cierres** con el listado
  del año (fecha, agente, operación, propiedad, nota, quién lo registró) y botón **Registrar
  cierre** que abre un modal: agente (de la empresa activa), fecha (hoy por defecto, no futura),
  operación Venta / Alquiler, propiedad opcional (buscador de la empresa activa, incluidas las
  vendidas / archivadas) y nota. Borrar con confirmación. Patrón `ui.modal` + `ui.drawer` del skill.
- **Snapshots**: al registrar o borrar un cierre con fecha en un mes o año ya congelado, se
  recalculan solo las columnas de cierres de ese snapshot (agente y empresa del cierre). Así
  Evolución y los períodos pasados reflejan el dato aunque se meta tarde.
- **Inicio del admin**: la actividad reciente muestra "Cierre · {propiedad o Venta/Alquiler}"
  con el agente, enlazando a la pestaña Cierres.
- **Agentes**: no registran ni ven el listado; sí ven su métrica en Inicio como hasta ahora.

### 2.2 Dirección solo de la propia empresa

- Regla: un usuario ve la calle de una propiedad **solo si su empresa está entre las que él
  puede usar** (`request.state.allowed_companies`: las del usuario y las de su ficha de agente).
  El admin ve todas. Un agente dado de alta en MOYZA y MOES ve las dos.
- Si no puede verla, en su lugar sale solo población y zona (sin texto de "reservada").
- Implementación: función Jinja con contexto `street_of(prop)` en `template_env.py` que aplica la
  regla (`app/core/address.py::street_for`), y se usa en vez de `prop.address | street` en los
  sitios de §1.2. En el JSON del buscador y en las filas de solo lectura de la pestaña de la otra
  empresa la dirección se omite **desde el servidor** (no solo en la plantilla).
- Buscadores: la búsqueda por texto deja de mirar `address` en las propiedades de la otra
  empresa (si no, se adivinaría la calle buscándola).
- Visitas: si un agente acompaña una visita de la otra empresa, la ficha de visita (pantalla y
  PDF) conserva la dirección completa: es el documento legal de una visita que él hace en persona.
- PDFs y WhatsApp no cambian (ya son solo de la empresa activa).

## 3. Fases

- **Fase A — Cierres: modelo, migración y métrica.** `models/closing.py`, migración, cambios en
  `performance_report_service.py` (spec, filas, explicación), `dashboard_service.py` (actividad),
  `commercial_results.py` (CSV), recálculo de snapshots, tests.
- **Fase B — Cierres: pantalla.** Pestaña Cierres + modal de alta + borrado, rutas POST, tests
  de ruta.
- **Fase C — Direcciones.** `street_of`, plantillas, JSON y filas de solo lectura, búsqueda,
  tests de aislamiento.

## 4. Preguntas abiertas (respuestas del usuario)

1. Cierres: un registro por cierre (fecha, agente, venta/alquiler, propiedad opcional, nota) — **recomendado** — ¿o basta un número por agente y mes?
2. ¿Registra solo el admin? — **recomendado sí**.
3. Cierre con dos agentes (captador y el que trajo al comprador): ¿un registro por cada agente (el admin mete dos) — **recomendado, más simple** — o un solo registro con dos agentes?
4. Cierre con fecha en un mes ya congelado: ¿se actualiza el snapshot de ese mes y año? — **recomendado sí**.
5. Direcciones: ¿el admin las ve todas? — **recomendado sí**.
6. ¿Un agente que está en las dos empresas ve las dos? — **recomendado sí**.
7. Agente acompañante en una visita de la otra empresa: ¿la ficha de visita mantiene la dirección completa? — **recomendado sí**.

## 5. Estado

Pendiente de respuestas. Ojo: el árbol de trabajo tiene cambios sin commitear de otra sesión
(`PLAN_BAJA_USUARIOS.md`, migración `f5a6b7c8d9e0`) y de `PLAN_VISITAS_INDICATIVO_HONORARIOS.md`;
los agentes solo añaden al commit sus propios archivos por nombre.
