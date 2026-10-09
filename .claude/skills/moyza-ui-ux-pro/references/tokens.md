# Tokens de diseño

Todo lo que se escribe en una plantilla debe salir de aquí. Si falta algo, se añade aquí
primero. Las clases son de Tailwind 3 (Play CDN local), así que los modificadores de
opacidad (`blue-500/40`) y los valores arbitrarios (`max-h-[60vh]`) funcionan.

## Marca por empresa

| Empresa | Código | Color (`companies.primary_color`) | Uso |
|---|---|---|---|
| MOYZA | `MOYZA` | `#000000` | Franja superior del sidebar, punto junto al nombre, avatar del navbar, `theme-color`, serie "venta" en gráficas |
| MOES PREMIUM | `MOES` | `#8A6D1F` (dorado) | Igual |

En plantillas llega como `brand_color` y `brand_name` (context processor en
`app/web/template_env.py`). Se aplica con `style="background-color: {{ brand_color }}"`
o `style="color: ..."`. Por qué no en botones: el negro de MOYZA ya es el primario, y el
dorado de MOES como fondo de botón con texto blanco queda justo en el límite de contraste
y rompe la coherencia entre empresas. La marca se reconoce por la franja y el nombre.

Logo: `/static/logo_moyza.png` para ambas por ahora (`companies.logo_path`). Solo se usa
en documentos (ficha de visita, PDF). En la app, el nombre en texto basta.

## Paleta funcional

| Rol | Clases | Cuándo |
|---|---|---|
| Fondo de página | `bg-gray-50` | Ya está en `body` |
| Superficie | `bg-white` | Tarjetas, modales, tablas |
| Borde | `border-gray-200` (superficies), `border-gray-300` (controles) | |
| Texto principal | `text-gray-900` | Títulos, valores |
| Texto normal | `text-gray-700` | Cuerpo, celdas |
| Texto secundario | `text-gray-500` | Etiquetas, metadatos, ayuda |
| Texto apagado | `text-gray-400` | Placeholders, iconos inactivos |
| Primario (acción) | `bg-gray-900 hover:bg-gray-800 text-white` | Botón principal |
| Enlace / selección | `text-blue-600 hover:text-blue-700` | Enlaces, pestaña activa, fila seleccionada |
| Éxito | `green` | Completado, activo, disponible, objetivo cumplido |
| Aviso | `amber` | Pendiente, atención, cerrado reciente, duplicado. **No `yellow`** |
| Peligro | `red` | Error, prioridad alta, vendida/no disponible, acción destructiva |
| Información | `blue` | En proceso, informativo, neutro con énfasis |
| Neutro | `gray` | Baja prioridad, sin dato, cancelado |

Tonos por uso dentro de cada color:

- Badge: `bg-{c}-100 text-{c}-800`
- Banner / caja de aviso: `bg-{c}-50 border border-{c}-200 text-{c}-900` (texto secundario `text-{c}-800`)
- Botón sólido semántico (solo destructivo): `bg-red-600 hover:bg-red-700 text-white`
- Botón suave de fila: `bg-{c}-50 hover:bg-{c}-100 text-{c}-700`
- Icono de KPI: `bg-{c}-100 text-{c}-600`
- Valor de KPI: `text-{c}-600`

## Mapa de estados (único, úsalo tal cual)

| Dominio | Valor | Etiqueta | Color |
|---|---|---|---|
| Alerta `status` | `PENDING` | Pendiente | amber |
| | `IN_PROGRESS` | En proceso | blue |
| | `COMPLETED` | Completada | green |
| | `CANCELLED` | Cancelada | gray |
| Alerta `priority` | `ALTA` | Alta | red |
| | `NORMAL` | Normal | blue |
| | `BAJA` | Baja | gray |
| Etapa de seguimiento | ver `FollowUpActionType.stage_badge_color` en `core/constants.py` | | ya definido en Python; cambia `yellow`→`amber` ahí si aparece |
| Propiedad | Activa / disponible | | green |
| | Pausada | | amber |
| | Vendida / No disponible | | red |
| | Archivada | | gray |
| Operación | Venta | | blue |
| | Alquiler | | amber |
| Log de reportes | `success` | Exitoso | green |
| | `failed` | Fallido | red |
| | `pending` | Pendiente | amber |
| | `skipped` | Omitido | gray |
| Usuario | Activo / Inactivo | | green / gray |
| Semáforo de métricas | cumple objetivo | | green |
| | a medias | | amber |
| | lejos | | red |

Umbrales de semáforo: se definen por métrica en Python, pero los colores son siempre
verde / ámbar / rojo. Hoy "cumplimiento" usa verde / azul / naranja y "conversión"
verde / amarillo / rojo; al tocar esas pantallas, unifícalos.

## Tipografía

Sin fuente propia: pila `sans` de Tailwind (system-ui). Es rápida y se ve bien en móvil.
Si algún día se añade una fuente, va en `base.html` y en un `tailwind.config` inline.

| Uso | Clases |
|---|---|
| H1 de página | `text-2xl sm:text-3xl font-bold text-gray-900` |
| Subtítulo de página | `text-sm text-gray-500 mt-1` |
| Título de tarjeta / modal | `text-lg sm:text-xl font-bold text-gray-900` |
| Título de sección pequeña | `text-xs font-semibold uppercase tracking-wide text-gray-500` |
| Cuerpo, celdas, inputs | `text-sm text-gray-700` |
| Metadatos | `text-xs text-gray-500` |
| Valor KPI | `text-3xl font-bold` + color semántico |
| Etiqueta KPI | `text-sm font-medium text-gray-500` |

Evita `text-[10px]`: no se lee en móvil. Mínimo `text-xs`.

## Radios, sombras, bordes

| Elemento | Radio |
|---|---|
| Tarjeta, modal, tabla envuelta | `rounded-2xl` |
| Botón, input, select, textarea, banner | `rounded-xl` |
| Badge, avatar, punto de estado | `rounded-full` |
| Elementos pequeños (chip de filtro, opción de lista, caja de icono) | `rounded-lg` |

Sombras: las superficies no llevan sombra, llevan borde. Solo el menú desplegable y el
autocompletado usan `shadow-lg`, y el modal `shadow-xl`. Más sombras = más ruido.

## Espaciado

- `<main>` ya aplica `p-4 sm:p-6 lg:p-8`. El contenido va directo dentro con `space-y-6`.
  No repitas ese padding en la plantilla (hoy pasa en 5 páginas y deja 64 px por lado).
- Ancho máximo de contenido: `max-w-7xl mx-auto` en listados y dashboards; `max-w-3xl`
  en formularios de página completa y fichas de detalle con una sola columna.
- Interior de tarjeta: `p-4 sm:p-6`. Cabecera de tarjeta: `px-4 sm:px-6 py-4 border-b border-gray-200`.
- Separación entre bloques: `space-y-6`; entre controles de un formulario: `space-y-4`;
  entre botones: `gap-3`; entre icono y texto: `gap-2`.
- Modales: panel `p-6`, pie `px-6 py-4 border-t border-gray-200`.

## Tamaños táctiles

Botones e inputs: alto mínimo 40 px (`py-2.5` con `text-sm`). Acciones de fila en móvil:
`w-9 h-9` con icono centrado. Nada clicable por debajo de 36 px.

## Iconos

Heroicons v2 outline (24 px), inline SVG, `stroke-width="1.5"`, `w-5 h-5` en botones y
`w-4 h-4` en badges o metadatos. Siempre `aria-hidden="true"` si hay texto al lado;
si el botón es solo icono, `aria-label` en el botón.

Reservar un icono por sección y no repetir: hoy Visitas, Clientes y Compradores usan el
mismo. Propuesta: Propiedades `home`, Clientes `briefcase`, Agentes `user-group`,
Compradores `users`, Visitas `calendar-days`, Informes `document-text`, Resultados `chart-bar`,
Logs `clipboard-document-list`, Consumo IA `cpu-chip`, Actividad `clock`, Usuarios `key`.

## Z-index

`z-30` navbar sticky, `z-40` overlay del sidebar, `z-50` sidebar y modales, `z-[60]`
menús desplegables dentro de un modal. No inventar otros.
