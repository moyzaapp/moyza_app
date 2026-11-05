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

### 2.2 Dirección solo de la propia empresa (por ahora, solo en la sección Propiedades)

- **Alcance acotado por el usuario**: por el momento se aplica únicamente a la pestaña
  "Propiedades de {otra empresa}" de la sección Propiedades. Los demás sitios de §1.2
  (sugerencias, buscador de alertas, detalle de alerta, ficha del comprador, visitas) **no se
  tocan** en esta tanda.
- Regla: un usuario ve la calle de una propiedad de la otra empresa **solo si esa empresa está
  entre las que él puede usar** (`request.state.allowed_companies`: las del usuario y las de su
  ficha de agente). El admin ve todas. Un agente dado de alta en MOYZA y MOES ve las dos.
- Si no puede verla, la celda muestra solo población y zona (sin texto de "reservada").
- Implementación: `_readonly_property_rows(query, search, include_address=True)` en
  `routes/properties.py`; para la pestaña de la otra empresa se pasa `include_address=False`
  cuando el usuario no puede verla, y entonces la consulta **no carga `Property.address`** (la fila
  lleva `address=None`) y la búsqueda por texto **no mira `address`** (si no, se adivinaría la calle
  buscándola). `table_others.html` pinta la calle solo si viene.
- "Resto de propiedades" (misma empresa) no cambia.

## 3. Fases

- **Fase A — Cierres: modelo, migración y métrica.** `models/closing.py`, migración, cambios en
  `performance_report_service.py` (spec, filas, explicación), `dashboard_service.py` (actividad),
  `commercial_results.py` (CSV), recálculo de snapshots, tests.
- **Fase B — Cierres: pantalla.** Pestaña Cierres + modal de alta + borrado, rutas POST, tests
  de ruta.
- **Fase C — Direcciones (solo pestaña de la otra empresa).** `_readonly_property_rows` con
  `include_address`, `table_others.html`, tests de aislamiento.

## 4. Decisiones (respuestas del usuario, 2026-11-04)

1. Cierres: **un registro por cierre** (fecha, agente, venta/alquiler, propiedad opcional, nota).
2. **Solo el admin** registra y borra cierres.
3. Cierre con dos agentes: **un registro por cada agente** (el admin mete dos).
4. Cierre con fecha en un mes ya congelado: **sí se actualiza** el snapshot del mes y del año.
5. Direcciones: el admin las ve todas (sin respuesta explícita; se aplica la recomendación).
6. Un agente dado de alta en las dos empresas **ve las dos**.
7. Visitas: la ficha mantiene la dirección completa (**fuera de alcance** en esta tanda: solo se
   toca la sección Propiedades).

## 5. Estado

Hecho el 2026-11-04 (commits `97489be` fase C, `30ce6ef` fase A, `4d8b6b8` fase B, `dc02e1c`
pestañas en móvil). Suite: 3 fallos, los mismos del baseline. Comprobado a 375 px por CDP.

Decisiones de implementación: `Closing.business_type` es `String` con "Venta"/"Alquiler";
la actividad del Inicio usa `created_at` (cuándo se registró); el refresco de snapshots solo
toca mes y año (la semana no tiene objetivo de cierres); la propiedad se elige con un buscador
que filtra en el navegador (título, referencia, calle, población; inventario completo de la
empresa en JSON dentro de la página, máximo 30 resultados visibles); un error de alta devuelve
flash y no conserva lo escrito. En la pestaña de la otra empresa el texto del buscador deja de mencionar
"dirección" cuando la calle no se ve.

Despliegue: `alembic upgrade head` (`a6b7c8d9e0f1`, tabla `closings`); no hay migración de
datos, así que la métrica en vivo arranca en 0 hasta que el admin registre cierres y los
snapshots ya congelados conservan la cifra antigua hasta que se registre o borre un cierre de
ese período. El CSS se recompila en la build de la imagen.
