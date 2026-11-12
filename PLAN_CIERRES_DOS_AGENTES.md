# Plan: cierres compartidos por dos agentes

Fecha: 2026-11-12. Rama `63-agregar-moes`. Petición: en Resultados Comerciales → Cierres, que el
formulario "Registrar cierre" admita dos agentes cuando la venta la han hecho entre dos, y que
el cierre cuente para los dos.

## 1. Situación actual

- `closings`: un registro por cierre **y por agente** (`agent_id`); para dos agentes el admin
  mete dos registros a mano (decisión 3 de PLAN_CIERRES_MANUALES_Y_DIRECCIONES.md).
- La métrica cuenta registros por `agent_id` (`_indicator_spec("cierres")`), con desglose
  venta / alquiler; el total del equipo en Inicio, Rendimiento y Evolución es la **suma de los
  agentes**. Los snapshots congelados guardan la cifra por agente.
- La pestaña Cierres lista un registro por fila con su agente y permite borrarlo.

## 2. Diseño propuesto

- **Modelo**: se mantiene un registro por agente (la métrica y los snapshots no cambian) y se
  enlazan los dos registros de un cierre compartido: nueva columna `shared_with_agent_id`
  (FK `agents`, nullable) en cada uno apuntando al otro agente y `pair_key` (UUID o id del
  primer registro) para tratarlos como uno. Migración tras `a6b7c8d9e0f1`.
- **Formulario**: "Agente" pasa a "Agente 1" (obligatorio) y "Agente 2 (opcional, si cerraron
  entre dos)"; deben ser distintos y de la empresa activa. Un envío crea uno o dos registros con
  la misma fecha, operación, propiedad y nota, y refresca los snapshots de los dos agentes.
- **Pestaña Cierres**: un cierre compartido se pinta en **una fila** con los dos nombres
  ("Ana · con Bea") y un solo botón de borrar que elimina los dos registros. Los totales de
  cabecera de la pestaña (venta / alquiler) cuentan operaciones (1 por cierre compartido) y se
  indica "N de ellos compartidos".
- **Lupa de trazabilidad y CSV** por agente: la fila del cierre indica "con Nombre" cuando es
  compartido.
- **Inicio (actividad reciente)**: un solo evento "Cierre · propiedad · Ana y Bea".
- **Métrica por agente**: cada uno suma 1 cierre completo. **Total del equipo**: suma de los
  agentes (un cierre compartido cuenta 2 en el equipo), coherente con los objetivos por agente.

## 3. Decisiones (respuestas del usuario, 2026-11-12: "lo recomendado")

1. Cada agente suma 1 cierre completo; el total del equipo es la suma de los agentes (2 por un
   cierre compartido).
2. Máximo dos agentes por cierre.
3. Una sola fila en la pestaña Cierres con los dos nombres; borrar quita a ambos.
4. Los cierres compartidos ya metidos como dos registros sueltos no se enlazan: si los hay, se
   borran y se vuelven a registrar con el formulario nuevo.

## 4. Fases

- **Fase A — modelo, migración, alta doble y borrado en pareja**, refresco de snapshots, tests.
- **Fase B — pantalla**: formulario con Agente 2, fila única en el listado, totales, lupa/CSV,
  actividad del Inicio, tests de ruta y móvil.

## 5. Estado

Hecho el 2026-11-12: fase A en `f3cde28` y fase B en `fb475b5`. Suite: 3 fallos, los
mismos del baseline. Comprobado a 375 px por CDP (listado, modal de alta y modal de borrado).

Decisiones de implementación: lógica en `app/services/closing_service.py` (`create_closing`,
`delete_closing`, `ClosingError` con el mensaje del flash); el formulario envía `agent_id` y
`agent_id_2`; los dos registros comparten `created_at` y la fila de la pestaña es la del
Agente 1 (id menor), con "con {Agente 2}" debajo; el modal de borrado añade "se quitará a los
dos agentes"; el CSV de la lupa tiene la columna "Con" tras "Operación"; el evento del Inicio
mantiene el título "Cierre · {propiedad o operación}" y pone "Ana y Bea" donde iba el agente.
La explicación de la regla de la lupa añade que un cierre compartido cuenta entero para cada uno.

Despliegue: `alembic upgrade head` (`b7c8d9e0f1a2`: columnas `shared_with_agent_id` y
`pair_key`); sin migración de datos (decisión 4). Sin clases Tailwind nuevas.
