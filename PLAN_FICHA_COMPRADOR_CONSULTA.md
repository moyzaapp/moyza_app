# Plan: la ficha del comprador es de consulta; el trabajo se hace desde la alerta

Fecha: 2026-11-18. Rama: `63-agregar-moes`.

## Problema

Algunos agentes entran por la tabla «Compradores» de `/alerts`, abren la ficha
del comprador, registran ahí el perfil y proponen propiedades **sin pasar por
una alerta**. Guardar el perfil desde la ficha (`/buyers/{id}/search-criteria`)
no deja ningún seguimiento, así que para la app no ha pasado nada: la alerta
(si la hay) sigue «sin gestionar», el reloj de atención sigue corriendo y nada
cuenta en Rendimiento ni en Resultados. Sin alerta, el comprador es invisible.

Medido en producción el 2026-11-18: 162 compradores con perfil y sin alerta
abierta, pero **150 habían pasado por una alerta ya cerrada** (flujo normal) y
solo **12, de 5 agentes, nunca tuvieron alerta**. Problema pequeño hoy, puerta
abierta.

## Decisiones cerradas con el usuario

- **No se oculta** la tabla de compradores ni la ficha: son el directorio y la
  vista del comprador a lo largo de sus alertas («seguimiento a nivel de
  comprador», pestaña Alertas).
- Desde la ficha **no se puede trabajar fuera de la alerta**: el perfil y las
  compatibles solo actúan a través de la alerta abierta del usuario con ese
  comprador, y sin ella la ficha ofrece **crear la búsqueda** (alerta sin
  referencia) y lleva al agente a la alerta.
- **El agente se crea él mismo la búsqueda** desde la ficha (el admin elige el
  agente). Es la entrada al camino bueno, no un atajo.
- El orden de pasos (Contactar → Perfil → Propuesta) no cambia.

## Diseño

`work_alert` = la alerta **abierta** más reciente del comprador que el usuario
puede gestionar (agente: las suyas; admin: cualquiera), por última asignación.

- **Cabecera de la ficha**: con `work_alert`, aviso azul «La gestión de X se
  hace desde su alerta #N» + «Ir a la alerta». Sin ella, aviso ámbar «Sin
  alerta abierta» + «Crear búsqueda».
- **Perfil**: con `work_alert`, el mismo formulario pero enviado a
  `/alerts/{N}/search-profile` (registra «Contactado» / «Perfil guardado» en
  la alerta y lleva a su Propuesta; el agente responsable es el de la alerta).
  Sin ella, solo lectura (chips del perfil o «Sin definir») + «Crear
  búsqueda». La ruta `/buyers/{id}/search-criteria` se conserva (sin uso en la
  interfaz).
- **Compatibles**: con `work_alert`, casilla «Le interesa» por tarjeta y
  barra «Añadir a su lista (N)» → `/alerts/{N}/interest-properties`
  (PLAN_ALERTA_VARIAS_PROPIEDADES.md); las ya en su lista, «En su lista».
  Sin ella, tarjetas sin acción y una línea «Para proponérselas, crea su
  búsqueda». Desaparecen «Crear alerta» (modal rápido con referencia), «De
  otra empresa…» y «Solo el agente de la propiedad…». Enviar por WhatsApp
  sigue igual.
- **Crear búsqueda**: modal en la ficha (operación precargada del perfil,
  agente si admin, origen y notas) → `POST /alerts/create` con `buyer_id`, sin
  propiedad y `return_to=buyer`: al crearla redirige al detalle de la alerta
  nueva (paso Contactar; el perfil se registra en «Contactado»); el aviso de
  búsqueda duplicada y los errores de agente vuelven a la ficha.
- El JS de las casillas «Le interesa» pasa a `ui.js` (lo usan la Propuesta y
  la ficha).

## Lo que se pierde a propósito

- Crear desde la ficha una alerta **con referencia** sobre una propiedad
  propia: ahora se crea la búsqueda y se añade la propiedad a su lista.
- Editar el perfil o su «Agente responsable» sin alerta abierta (también el
  admin): el responsable es el agente de la alerta.

## Tests

`tests/test_buyer_detail_work_alert.py` (entorno de `test_alert_search.py`):
ficha con alerta abierta del agente (aviso, formulario a la alerta, casillas,
guardar registra Contactado en la alerta); ficha sin alerta abierta (solo
lectura, CTA, sin casillas); alerta abierta de otro agente = sin alerta para
el agente; crear búsqueda desde la ficha (agente y admin) redirige al detalle;
duplicada vuelve a la ficha; admin sin agente vuelve a la ficha. Ajustar
`test_sugerencias_multiempresa.py` (textos retirados).

## Estado

- [x] Rutas (`work_alert`, `return_to`)
- [x] Ficha (`buyers/detail.html`) y JS compartido (`ui.js`, `[data-interest-form]`)
- [x] Tests (`tests/test_buyer_detail_work_alert.py`, 10), lint (175 → 170 avisos), CSS,
  documentación (`docs/DECISIONES_ALERTAS_BUSQUEDA.md` §10)

Notas de la implementación (2026-11-18):

- Comprobado a 375 px (sin desbordamiento) en las dos variantes de la ficha.
- Tres tests antiguos de la ficha se ajustaron al comportamiento nuevo
  (`test_sugerencias_multiempresa`, `test_profile_solo_venta`, `test_profile_location`).
- Pendiente de decidir: qué hacer con los 52 compradores «sin nombre / sn / usuario»
  de producción (probablemente pruebas) y con los 12 sin alerta (el admin puede
  crearles la búsqueda desde la ficha).
