# Decisiones: alertas sin referencia (búsqueda general)

Fecha: 2026-10-16. Plan de implementación: `PLAN_ALERTA_SIN_REFERENCIA.md`.
Migración: `y8z9a0b1c2d3_alert_without_property`.

## 1. Decisión tomada

Un comprador que llama sin una referencia concreta genera **una sola alerta**
("sin referencia", `origin = 'search'`) sin propiedad. El agente que la atiende:

1. **Contacta** al comprador (seguimientos habituales).
2. Toma su **perfil de búsqueda** (zonas, ciudades, tipo, dormitorios, baños,
   precio, imprescindibles; sin m²). Guardarlo registra un seguimiento
   automático `CALIFICADO` con el resumen y deja el perfil en el comprador
   (`BuyerSearchCriteria`, uno por comprador).
3. Ve las **propiedades sugeridas** (todas las disponibles de la empresa
   activa, de cualquier agente) y **asocia a esa misma alerta** la que elige
   el comprador. Puede **cambiarla** después (presupuesto, gustos).

Reglas:

- La alerta la **conserva el agente que atiende** al comprador aunque la
  propiedad asociada sea de otro agente: `alert.agent_id` no cambia al asociar.
- Solo las alertas de origen `search` pueden asociar o cambiar de propiedad.
  Las de origen `property` (creadas con referencia) siguen significando
  "interés en este inmueble" y no cambian.
- Asociar o cambiar registra un seguimiento real `PROPIEDAD_ASOCIADA`
  ("Propiedad asociada: X" / "Cambio de propiedad: de A a B"): cuenta como
  gestión (desbloquea la cola, permite cerrar) pero no avanza la etapa.
- Si el comprador ya tiene otra alerta abierta sobre esa propiedad, se pide
  confirmación y se anota en el mensaje de la alerta.
- La superficie (m²) sale del perfil en toda la app. Las columnas
  `min_m2` / `max_m2` se conservan con sus datos, pero no se editan ni filtran.
- El flujo "Agregar alerta con filtro" (`/buyers/create-with-criteria`) se
  eliminó: un único punto de entrada, "Agregar alerta comprador", con el
  selector "Con referencia / Sin referencia".

## 2. Alternativa descartada por ahora: una alerta nueva por propiedad

En lugar de asociar la propiedad a la misma alerta, crear una **alerta nueva
por cada propiedad** que interese al comprador, enlazada a la búsqueda.

Qué ganaría:

- Varias propiedades a la vez para el mismo comprador (hoy, una por búsqueda).
- El agente captador de cada propiedad quedaría implicado (su alerta, su cola).
- Métricas por propiedad más limpias: cada alerta apunta a un único inmueble
  desde su creación y nunca "salta".

Qué cambiaría en código:

- Tabla de enlace búsqueda ↔ alertas, o columna `parent_alert_id` en
  `property_alerts`.
- En el paso "Propuesta", un botón "Registrar interés" que crea la alerta
  hija (con referencia) en vez de "Asociar a esta alerta".
- Notificación al captador de la propiedad (`alert_assigned` o un aviso nuevo).
- Reglas de cola y cierre: qué pasa con la búsqueda padre cuando se cierran
  las hijas, y si la búsqueda cuenta como contacto además de las hijas.

## 3. Implicaciones para analítica y contadores (decisión actual)

- `alert.agent_id` **puede no coincidir** con `property.agent_id` en una
  búsqueda con propiedad asociada de otro agente.
- **Métricas por agente** (se quedan con quien atiende, `alert.agent_id`) y
  cuentan también las búsquedas sin propiedad. La empresa es la columna
  propia `property_alerts.company_id`, no la de la propiedad:
  - `services/performance_report_service.py`: indicador **contactos**
    (`select_from(PropertyAlert)`, sin JOIN) y **cierres** (`OUTER JOIN` a la
    propiedad solo para el tipo de respaldo; una búsqueda sin propiedad y sin
    tipo cuenta como "otros"). Captaciones y bajadas siguen siendo de la
    propiedad.
  - `services/dashboard_service.py`: agenda y "sin respuesta" del agente,
    tendencia semanal de contactos, compradores pendientes y abandonados,
    última actividad del agente y cierres del feed: todos por
    `PropertyAlert.company_id`.
  - `services/buyer_reminder_service.py` (recordatorio 48 h) y
    `services/notification_service.py` (seguimiento vencido): agrupan por la
    empresa de la alerta; ya no cargan la propiedad.
  - Resultados Comerciales, pestaña Compradores
    (`routes/commercial_results.py`): usa `scope_alerts` (empresa de la
    alerta); las búsquedas sin propiedad aparecen como "Búsqueda general".
- Los **contadores de `/alerts`** (pendientes / en proceso / completadas) no
  cambian: una búsqueda es una alerta más.
- **Métricas por propiedad**: solo ven la alerta cuando ya tiene propiedad
  asociada (consultas por `property_id`, p. ej. duplicados comprador +
  propiedad). Hoy no hay ningún informe "por propiedad" que cuente alertas;
  si se crea, tendrá que decidir qué hacer con las búsquedas: la propiedad
  asociada **puede cambiar** ("saltar" de un inmueble a otro) y el historial
  está en los seguimientos `PROPIEDAD_ASOCIADA`.
- El texto libre del listado sigue buscando por título de propiedad con
  `OUTER JOIN` (una búsqueda sin propiedad se encuentra por comprador o
  teléfono).

## 4. Qué permite cambiar de idea después

- `property_alerts.origin` (`property` / `search`): distingue las alertas
  creadas sin referencia, aunque ya tengan propiedad.
- `property_alerts.property_linked_at`: cuándo se asoció (o cambió) la
  propiedad de la búsqueda.
- Seguimientos `PROPIEDAD_ASOCIADA`: historial completo de propiedades por
  las que pasó cada búsqueda (con fecha y usuario). Con esto se pueden
  reconstruir alertas hijas por propiedad si se adopta la alternativa del §2.
- `property_alerts.company_id`: la alerta ya no depende de la propiedad para
  saber su empresa.
