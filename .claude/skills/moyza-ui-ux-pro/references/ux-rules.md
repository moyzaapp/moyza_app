# Reglas de UX y checklist de entrega

Pasa esta lista antes de dar por terminada cualquier pantalla. Cada punto existe porque
hoy falla en algún sitio de la app (ver `audit-2026-10.md`), así que no es teoría.

## Intuitivo: cómo se decide qué va dónde

- **Primero lo que se hace cada día.** En cada pantalla, la acción más frecuente del rol
  que la usa es la primaria y está arriba a la derecha (escritorio) o a ancho completo
  (móvil). Para un agente en Compradores: "Registrar seguimiento". Para admin: "Nueva alerta".
- **El estado se ve sin leer.** Badge de color + texto en cada fila. Lo urgente (alerta sin
  atender +7 días, prioridad alta) tiene un indicador propio, no solo un color más fuerte.
- **Una cosa por vista.** Si una página tiene tres pestañas y dos modales grandes,
  probablemente son dos páginas. `alerts/list.html` (1.300 líneas) es el ejemplo a evitar.
- **Nombra el objeto.** Botones, flashes y confirmaciones dicen sobre qué actúan: "Eliminar
  a Juan Pérez", "Alerta creada para Piso en Jaén". Nada de "Aceptar" / "Operación realizada".
- **Los filtros no esconden datos sin avisar.** Si hay un filtro activo (incluido el
  por defecto, como "activas"), se ve como chip y hay "Limpiar".
- **Consistencia por encima de originalidad.** Un mismo concepto (estado, prioridad,
  operación) se pinta igual en todas las pantallas: lista, detalle, ficha de comprador,
  dashboard. Si cambias uno, cambia todos o no cambies ninguno.

## Formularios

- [ ] Cada `<label>` tiene `for` y el control su `id` (o el label envuelve al control).
- [ ] Obligatorios con `required` y `*`; ayuda con `aria-describedby`.
- [ ] Error junto al campo (`role="alert"`, rojo) cuando el servidor rechaza; el flash solo
      si el error no es de un campo concreto.
- [ ] El valor introducido no se pierde tras un error: el servidor vuelve a pintar el
      formulario con los datos, o el aviso llega antes de enviar (como en duplicados).
- [ ] Teclado móvil correcto (`type`, `inputmode`, `autocomplete`).
- [ ] El botón de envío se desactiva al enviar y muestra "Guardando…" (`data-once` en `ui.js`).
- [ ] El orden de tabulación sigue el orden visual. Cancelar a la izquierda, primario a la derecha.
- [ ] Selects con una opción vacía explícita ("Sin especificar") cuando el campo es opcional.

## Modales

- [ ] `role="dialog" aria-modal="true" aria-labelledby`.
- [ ] Cierra con Escape, con la X y con clic en el fondo (salvo si hay cambios sin guardar:
      entonces solo X y Cancelar).
- [ ] El foco entra al primer control y vuelve al botón que lo abrió.
- [ ] En móvil ocupa el ancho completo y nace desde abajo; `max-h-[92vh]` con scroll interno.
- [ ] Un modal no abre otro modal. Un aviso dentro de un modal es un banner, no otro modal.
- [ ] Las validaciones que se pueden hacer antes de enviar (duplicado, comprador existente)
      se muestran dentro del modal con el botón "de todas formas" en ámbar.

## Tablas y listados

- [ ] Envoltorio con `overflow-x-auto` y `min-w-[...]` en la tabla.
- [ ] Cabecera `th scope="col"`, uppercase pequeño, `sticky top-0` si hay scroll interno.
- [ ] Columna de acciones sin título visible (`sr-only`), máximo tres acciones, icono solo en móvil.
- [ ] Números alineados a la derecha con `tabular-nums`; fechas en `dd/mm/aaaa` con filtro `madrid_dt`.
- [ ] Estado vacío con siguiente paso.
- [ ] Más de 50 filas: paginación en servidor con "Mostrando x-y de N".
- [ ] Orden por defecto explicado (badge "ordenado por prioridad") si no es el obvio.

## Móvil

- [ ] Probado a 375 px de ancho: sin scroll horizontal de página, botones a ancho completo,
      cabeceras en columna (`flex-col sm:flex-row`).
- [ ] Zoom permitido: quitar `maximum-scale=1.0, user-scalable=no` del viewport.
- [ ] Área táctil ≥ 40 px; separación entre acciones de fila ≥ 4 px.
- [ ] Nada depende de `hover` (tooltips `title` no funcionan en táctil: el texto esencial va visible).
- [ ] Gráficas con alto fijo y leyenda abajo.

## Accesibilidad mínima

- [ ] Contraste AA: texto gris ≥ `gray-500` sobre blanco; nunca `gray-400` para texto que haya que leer.
- [ ] Foco visible en botones y enlaces (`focus-visible:ring-2`); no `focus:outline-none` sin alternativa.
- [ ] Iconos decorativos con `aria-hidden="true"`; botones solo icono con `aria-label`.
- [ ] Flash con `role="status" aria-live="polite"`; errores con `role="alert"`.
- [ ] Menú móvil con `aria-expanded` en la hamburguesa y cierre con Escape.
- [ ] Página activa en el sidebar con `aria-current="page"`.

## Feedback y estados

| Situación | Qué mostrar |
|---|---|
| Acción completada | Flash `success` en una frase con el objeto |
| Error de servidor | Flash `error` y, si se puede, qué hacer ("Inténtalo de nuevo o avisa a…") |
| Validación de campo | Texto rojo bajo el campo |
| Aviso antes de actuar | Banner ámbar en contexto + botón "de todas formas" |
| Cargando datos por fetch | Esqueleto gris (`animate-pulse`) del tamaño del contenido, no "Cargando…" suelto |
| Enviando formulario | Botón desactivado con texto "Guardando…" |
| Lista vacía | Estado vacío con siguiente paso |
| Acción no permitida por rol | No mostrar el botón; si se muestra deshabilitado, `title` con el motivo |
| Alerta bloqueada en la cola | Candado + "Atiende primero la alerta #N" con enlace |

## Seguridad en plantillas

- Datos a JS siempre con `| tojson` (en atributos `data-*` añade `| forceescape`).
- Nunca `onclick="f('{{ texto }}')"`: se rompe con un apóstrofo y permite inyección.
- `innerHTML` solo con texto pasado por `escapeHtml` (ver `alert-duplicates.js`).
- Enlaces a otras rutas con `href` relativo; `target="_blank"` siempre con `rel="noopener"`.

## Roles (admin frente a agente)

- La plantilla recibe `is_admin` del route; no leer `request.state.user.role` en Jinja.
- Lo que un agente no puede hacer, no se pinta (ni deshabilitado), salvo que sea útil
  que sepa que existe (entonces deshabilitado con motivo).
- Un agente ve solo su empresa; el selector de empresa aparece solo si `can_switch_company`.
- El navbar muestra el nombre del rol, no `role_id`.

## Textos

- Español de España, trato de "tú", frases cortas, sin mayúsculas en cada palabra
  ("Nueva alerta", no "Nueva Alerta").
- Botones en infinitivo o sustantivo ("Guardar", "Nueva alerta"); nunca "OK".
- Fechas `dd/mm/aaaa`, horas `HH:MM`, moneda `120.000 €` (espacio antes del símbolo).
- Evitar jerga interna en la interfaz ("lead", "match"): "comprador interesado",
  "propiedad compatible".
