# Plan: varias propiedades de interés por alerta

Fecha: 2026-11-18. Rama: `63-agregar-moes`. Sustituye la decisión 1 ("una sola
propiedad por alerta") de `docs/DECISIONES_ALERTAS_BUSQUEDA.md` sin rehacer lo
que ya funciona.

## Qué pidió el usuario

En el paso 3 «Propuesta» de una alerta (con el perfil del comprador hecho), el
agente marca **varias** propiedades sugeridas que le llaman la atención al
comprador, de **las dos inmobiliarias y de cualquier agente**, y eso queda en el
**seguimiento**. El envío por WhatsApp ya deja «Propiedad enviada»; se mantiene.

## Decisiones cerradas con el usuario

- Varias propiedades en la **misma alerta** (no una alerta por propiedad).
- De cualquier agente y de MOYZA y MOES (la Propuesta ya las sugería así).
- Al captador de la propiedad **no** se le avisa: solo queda el seguimiento.
- La empresa de la alerta no cambia (la del comprador / la de alta).
- Listado: la primera propiedad y «+N más»; el detalle muestra la lista entera
  y permite quitar.
- Informes al propietario y métricas por propiedad: contarían todas, pero hoy
  ninguno lee las alertas (solo visitas, precios e interacciones), así que no
  hay nada que tocar.
- Por ahora **solo en la Propuesta de la alerta**: la ficha del comprador y el
  modal «Agregar alerta» con referencia siguen como están (fase posterior si se
  pide). El orden de los pasos (Contactar → Perfil → Propuesta) no cambia.

## Diseño

- Tabla nueva `alert_properties` (`alert_id`, `property_id`, `added_at`,
  `added_by`), única por (alerta, propiedad): las propiedades **adicionales**.
  `property_alerts.property_id` se queda como la **primera** de la lista, así
  listado, duplicados, avisos, trazabilidad de Resultados, cierres y visitas
  siguen funcionando sin cambios. Lista completa = propiedad de la alerta +
  adicionales (`PropertyAlert.interest_properties`). Sin backfill.
- `POST /alerts/{id}/interest-properties` (`property_ids` repetido): añade las
  marcadas. Mismas reglas que `/link-property` (perfil completo si es
  obligatorio, alerta abierta del agente o admin, propiedad de cualquier
  empresa, no archivada y disponible). Si la alerta no tiene propiedad, la
  primera pasa a ser la de la alerta (`property_linked_at`). Un seguimiento
  `PROPIEDAD_ASOCIADA`: «Propiedad de interés: A» / «Propiedades de interés: A,
  B (MOES PREMIUM)». Cuenta como gestión, no avanza la etapa, PENDING →
  IN_PROGRESS y resuelve el aviso «sin gestión», como asociar.
- Duplicados: si el comprador tiene otra alerta abierta con alguna de esas
  propiedades (como principal **o adicional**), no se añade nada y se pide
  confirmación para el lote entero (`confirm_properties`), con nota en la
  alerta. `find_duplicate_alerts` mira también las adicionales (afecta también
  al alta con referencia: es lo coherente).
- `POST /alerts/{id}/interest-properties/{property_id}/remove`: quita una
  adicional; si es la principal y hay adicionales, la más antigua pasa a
  principal. La única propiedad no se puede quitar (se cambia añadiendo otra y
  quitando esa). Seguimiento «Quitada de su lista: A».
- `/link-property` se conserva (tests y compatibilidad) pero la interfaz ya no
  lo usa.

## Interfaz (skill moyza-ui-ux-pro)

- Propuesta: bloque «Su lista (N)» con las tarjetas de la lista (Enviar por
  WhatsApp y Quitar). Sugerencias: casilla «Le interesa» en cada tarjeta que no
  está en la lista (`form=` fuera de la tarjeta, porque la tarjeta ya lleva el
  formulario de envío); las de la lista llevan «En su lista». Un único botón
  primario «Añadir a su lista (N)», deshabilitado sin selección. Buscador
  manual: «Añadir a su lista».
- Cabecera del detalle: «Otras propiedades de interés» bajo la propiedad; el
  enlace pasa a «Gestionar propiedades».
- Listado `/alerts` y alertas de la ficha del comprador: «+N más».

## Tests

`tests/test_alert_interest_properties.py` (SQLite en memoria, patrón
`test_send_property.py`): añadir varias de dos empresas y de otro agente; la
primera pasa a principal; seguimiento con la empresa; repetidas se ignoran;
archivada / no disponible rechazada; sin perfil rechazado; otro agente
rechazado; duplicado pide confirmación y con confirmación añade y anota;
duplicado detectado en adicionales; quitar adicional, quitar principal con
promoción, no quitar la única; render de la Propuesta, del detalle y del
listado. Suite completa sin fallos nuevos.

## Estado

- [x] Modelo, migración (`k7r8w9x0y1z2`) y `find_duplicate_alerts`
- [x] Rutas añadir / quitar
- [x] Interfaz Propuesta, detalle, listado, ficha del comprador
- [x] Tests, lint, CSS, documentación (`docs/DECISIONES_ALERTAS_BUSQUEDA.md` §9)

Notas de la implementación (2026-11-18):

- «Asociada ahora» pasa a «En su lista» y «Cambiar propiedad» a «Gestionar su
  lista»; los tests existentes se ajustaron a los textos nuevos.
- La barra «Añadir a su lista» es `sticky bottom-0`: en el móvil se ve
  mientras se recorren las tarjetas. Comprobado a 375 px sin desbordamiento.
- Pendiente si se pide: ficha del comprador y modal «Agregar alerta» con
  referencia (propiedades de otros agentes y de la otra empresa, y varias).
