# Componentes canónicos

HTML listo para copiar. Cuando el mismo bloque aparezca en más de dos plantillas, pásalo a
macro (`assets/ui_macros.html` tiene la versión Jinja de casi todos). Las clases salen de
`tokens.md`; si necesitas desviarte, cambia el token, no el componente.

Índice: cabecera de página · botones · tarjeta · tabla · badge · modal · formulario ·
autocompletado · banner · flash · tabs · filtros · estado vacío · paginación ·
confirmación · acciones de fila · sidebar activo.

## Cabecera de página

```html
<div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
    <div>
        <h1 class="text-2xl sm:text-3xl font-bold text-gray-900">Compradores</h1>
        <p class="text-sm text-gray-500 mt-1">Alertas de interés y seguimiento por agente</p>
    </div>
    <div class="flex flex-wrap gap-3">
        <!-- secundarios primero, el primario al final (a la derecha) -->
        <button type="button" class="BTN-SECUNDARIO">Exportar</button>
        <button type="button" class="BTN-PRIMARIO">Nueva alerta</button>
    </div>
</div>
```

Una sola acción primaria. Si hay más de tres acciones, las menos usadas van a un menú "Más".

## Botones

```html
<!-- Primario -->
<button type="submit" class="inline-flex items-center justify-center gap-2 bg-gray-900 hover:bg-gray-800 text-white rounded-xl px-4 py-2.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/30 disabled:opacity-50 disabled:cursor-not-allowed">
    <svg class="w-5 h-5" aria-hidden="true" ...></svg>
    Guardar
</button>

<!-- Secundario -->
<button type="button" class="inline-flex items-center justify-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 rounded-xl px-4 py-2.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/20">
    Cancelar
</button>

<!-- Terciario / de texto -->
<button type="button" class="text-sm font-medium text-blue-600 hover:text-blue-700 underline-offset-2 hover:underline">
    Limpiar filtros
</button>

<!-- Destructivo (solo dentro de una confirmación o en la ficha del elemento) -->
<button type="submit" class="inline-flex items-center gap-2 bg-red-600 hover:bg-red-700 text-white rounded-xl px-4 py-2.5 text-sm font-medium">
    Eliminar
</button>

<!-- Forzar / "de todas formas" (ámbar, tras un aviso) -->
<button type="submit" class="... bg-amber-600 hover:bg-amber-700 text-white ...">Crear de todas formas</button>
```

En móvil, los botones de cabecera y de pie de modal ocupan todo el ancho: `w-full sm:w-auto`.
`focus-visible` en vez de `focus` para que el anillo no salga al hacer clic con ratón.

## Tarjeta

```html
<section class="bg-white rounded-2xl border border-gray-200">
    <header class="flex items-center justify-between gap-3 px-4 sm:px-6 py-4 border-b border-gray-200">
        <h2 class="text-lg font-bold text-gray-900">Seguimientos</h2>
        <button class="BTN-SECUNDARIO text-xs px-3 py-1.5">Añadir</button>
    </header>
    <div class="p-4 sm:p-6">...</div>
</section>
```

Sin sombra. Si la tarjeta es clicable entera, es un `<a class="block ... hover:border-gray-300 transition-colors">`.

## Tabla

```html
<div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
    <div class="overflow-x-auto">
        <table class="w-full min-w-[640px] text-sm">
            <thead class="bg-gray-50 border-b border-gray-200">
                <tr>
                    <th scope="col" class="text-left px-4 sm:px-6 py-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Propiedad</th>
                    <th scope="col" class="text-center ...">Estado</th>
                    <th scope="col" class="text-right ...">Precio</th>
                    <th scope="col" class="text-right ..."><span class="sr-only">Acciones</span></th>
                </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
                <tr class="hover:bg-gray-50 transition-colors">
                    <td class="px-4 sm:px-6 py-3 text-gray-700">
                        <a href="/properties/1" class="font-medium text-gray-900 hover:text-blue-600">Piso en Jaén centro</a>
                        <p class="text-xs text-gray-500">Calle Real 12 · Jaén</p>
                    </td>
                    <td class="px-4 sm:px-6 py-3 text-center">BADGE</td>
                    <td class="px-4 sm:px-6 py-3 text-right tabular-nums text-gray-900">120.000 €</td>
                    <td class="px-4 sm:px-6 py-3 text-right">ACCIONES-DE-FILA</td>
                </tr>
            </tbody>
        </table>
    </div>
</div>
```

- Números a la derecha con `tabular-nums`; texto a la izquierda; badges centrados.
- Fila sin leer o destacada: `bg-blue-50/60` en el `<tr>`.
- Scroll vertical interno solo si la lista no pagina: `max-h-[60vh] overflow-y-auto` en el envoltorio y `sticky top-0 bg-gray-50` en los `th`.
- Listados largos (más de 50 filas): paginar en servidor, no `max-h`.
- Alternativa móvil para tablas con muchas columnas: lista de tarjetas con `block lg:hidden` + tabla `hidden lg:block` (patrón de `auth/home.html`). Vale la pena en Propiedades y Compradores.

## Badge

```html
<span class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium bg-amber-100 text-amber-800">
    <span class="w-1.5 h-1.5 rounded-full bg-amber-500" aria-hidden="true"></span>
    Pendiente
</span>
```

El punto de color es opcional; úsalo en estados, no en categorías (operación, tipo).
Los colores salen del mapa de estados en `tokens.md`. En Python, centraliza las clases
en `constants.py` como ya hace `FollowUpActionType.stage_badge_color`, y en Jinja usa el
macro `status_badge` en lugar de un `if/elif` en cada plantilla.

## Modal

```html
<div id="editModal" class="fixed inset-0 z-50 hidden" role="dialog" aria-modal="true" aria-labelledby="editModalTitle">
    <div class="absolute inset-0 bg-gray-900/50" data-modal-close></div>
    <div class="relative min-h-full flex items-end sm:items-center justify-center p-0 sm:p-4">
        <div class="bg-white w-full sm:max-w-lg max-h-[92vh] overflow-y-auto rounded-t-2xl sm:rounded-2xl shadow-xl">
            <header class="flex items-center justify-between gap-3 px-6 py-4 border-b border-gray-200">
                <h2 id="editModalTitle" class="text-lg font-bold text-gray-900">Editar cliente</h2>
                <button type="button" data-modal-close aria-label="Cerrar" class="w-9 h-9 -mr-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center">
                    <svg class="w-5 h-5" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12"/></svg>
                </button>
            </header>
            <form method="POST" action="..." class="p-6 space-y-4">
                ...
                <footer class="flex flex-col-reverse sm:flex-row sm:justify-end gap-3 pt-4 border-t border-gray-200 -mx-6 -mb-6 px-6 py-4 bg-gray-50 rounded-b-2xl">
                    <button type="button" data-modal-close class="BTN-SECUNDARIO w-full sm:w-auto">Cancelar</button>
                    <button type="submit" class="BTN-PRIMARIO w-full sm:w-auto">Guardar</button>
                </footer>
            </form>
        </div>
    </div>
</div>
```

JS: `assets/ui.js` expone `UI.openModal('editModal')` y `UI.closeModal('editModal')`,
cierra con Escape y con clic en `[data-modal-close]`, mueve el foco al primer control y lo
devuelve al botón que lo abrió. Tamaños: `sm:max-w-md` (confirmación), `sm:max-w-lg`
(formulario corto), `sm:max-w-2xl` (formulario largo), `sm:max-w-4xl` (propiedades).
En móvil el modal sale pegado abajo (`items-end`, `rounded-t-2xl`) como una hoja: se
alcanza con el pulgar.

Mientras no se adopte `ui.js`, el mínimo es: `role="dialog"`, `aria-modal`, `hidden`
alternado con `flex` (no ambos a la vez) y Escape.

## Formulario

```html
<div>
    <label for="buyer_phone" class="block text-sm font-medium text-gray-700 mb-1">
        Teléfono <span class="text-red-500" aria-hidden="true">*</span>
    </label>
    <input type="tel" id="buyer_phone" name="buyer_phone" required autocomplete="tel" inputmode="tel"
        class="w-full rounded-xl border border-gray-300 px-3 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 aria-[invalid=true]:border-red-500"
        aria-describedby="buyer_phone_help">
    <p id="buyer_phone_help" class="text-xs text-gray-500 mt-1">Con prefijo si no es español</p>
    <!-- error, solo cuando lo hay -->
    <p class="text-xs text-red-600 mt-1" role="alert">Ya existe un comprador con este teléfono</p>
</div>
```

- `id` + `for` siempre. Opcional se marca con `<span class="text-gray-400 font-normal">(opcional)</span>` solo si la mayoría de campos son obligatorios; si no, marca los obligatorios con `*`.
- `select` y `textarea` con las mismas clases. `textarea` con `rows="3"` y `resize-y`.
- Agrupa en `grid grid-cols-1 sm:grid-cols-2 gap-4`; campos largos con `sm:col-span-2`.
- Teclado móvil: `inputmode="numeric"` para precios, `type="email"`, `type="tel"`.
- El botón de envío se desactiva al enviar (`ui.js` lo hace con `data-once`).

## Autocompletado

Patrón de `alerts/list.html` (comprador y propiedad). Al reutilizarlo, extráelo a
`/static/js/autocomplete.js` con esta interfaz y borra los dos bloques duplicados:

```js
UI.autocomplete({
    input: '#buyerSearch', hidden: '#buyerIdHidden', list: '#buyerResults', selected: '#buyerSelected',
    url: term => '/alerts/search-buyers?q=' + encodeURIComponent(term),
    render: b => ({ title: b.name, meta: [b.phone, b.email].filter(Boolean).join(' · ') }),
    onSelect: b => window.alertDupRefresh && window.alertDupRefresh(),
    onClear: () => window.alertDupRefresh && window.alertDupRefresh()
});
```

Marcado: input con `role="combobox" aria-expanded aria-controls`, lista `<ul role="listbox">`
con `<li role="option">`, 250 ms de espera, flechas, Enter, Escape, "Sin coincidencias" y
"No se pudo buscar". El elemento elegido se muestra en una caja `bg-blue-50 border-blue-200`
con botón ✕ (`aria-label="Quitar"`).

## Banner (aviso en contexto)

```html
<div class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900 flex items-start gap-3" role="status">
    <svg class="w-5 h-5 shrink-0 mt-0.5" aria-hidden="true" ...></svg>
    <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold">Ya existe una alerta abierta para este comprador</p>
        <p class="text-xs text-amber-800 mt-1">Creada el 03/10/2026 por María · Idealista · En proceso</p>
        <div class="flex flex-wrap gap-2 mt-3">
            <a class="BTN-SECUNDARIO text-xs px-3 py-1.5 border-amber-300 text-amber-800">Ver alerta</a>
            <button class="bg-amber-600 hover:bg-amber-700 text-white rounded-lg px-3 py-1.5 text-xs font-medium">Registrar como nuevo contacto</button>
        </div>
    </div>
</div>
```

Tonos: ámbar aviso, azul información, rojo crítico (`role="alert"`), verde confirmación.
El banner va **donde está el problema** (dentro del modal, encima de la tabla afectada),
no arriba de la página.

## Flash (resultado de una acción)

Lo pinta `base.html` desde la cookie. Categorías: `success`, `error`, `warning`, `info`.
Reglas: un solo flash por acción; en una frase; nombra el objeto ("Alerta creada para
Juan Pérez"), no "Operación realizada". Si el error es de un campo, no uses flash:
devuelve el formulario con el error junto al campo. El contenedor debe llevar
`role="status" aria-live="polite"` (error: `role="alert"`). Al refactorizar `base.html`,
el bloque repetido 4 veces se convierte en un bucle con un mapa de color e icono.

## Tabs

Un solo estilo: subrayado.

```html
<nav class="flex gap-6 border-b border-gray-200 -mb-px overflow-x-auto" role="tablist" aria-label="Secciones">
    <a href="?tab=perfil" role="tab" aria-selected="true" class="whitespace-nowrap py-3 text-sm font-medium border-b-2 border-gray-900 text-gray-900">Perfil</a>
    <a href="?tab=matches" role="tab" aria-selected="false" class="whitespace-nowrap py-3 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300">Compatibles <span class="ml-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs">8</span></a>
</nav>
```

Server-side por query string (`?tab=`) salvo que el cambio no necesite datos nuevos.
El selector segmentado (Semana / Mes / Año) es otro componente: botones en un
`inline-flex rounded-xl border border-gray-300 p-0.5` con el activo `bg-gray-900 text-white rounded-lg`.

## Filtros

Una barra encima de la tabla, dentro de la misma tarjeta o justo encima:

```html
<form method="GET" class="flex flex-col sm:flex-row sm:flex-wrap gap-3 items-stretch sm:items-end">
    <div class="flex-1 min-w-[200px]">
        <label for="q" class="sr-only">Buscar</label>
        <div class="relative">
            <svg class="w-5 h-5 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" aria-hidden="true">...</svg>
            <input id="q" name="q" type="search" placeholder="Buscar por nombre, teléfono o email" class="INPUT pl-10">
        </div>
    </div>
    <div class="min-w-[160px]"><label for="status" class="sr-only">Estado</label><select id="status" name="status" class="INPUT">...</select></div>
    <button type="submit" class="BTN-SECUNDARIO">Filtrar</button>
    {% if filtros_activos %}<a href="?" class="BTN-TEXTO self-center">Limpiar</a>{% endif %}
</form>
```

Filtros activos visibles como chips (`rounded-lg bg-gray-100 text-xs px-2.5 py-1`) con ✕
cuando hay más de dos. Los filtros con `onchange` que recargan la página solo si no hay
botón "Filtrar".

## Estado vacío

```html
<div class="py-12 px-6 text-center">
    <div class="mx-auto w-12 h-12 rounded-full bg-gray-100 text-gray-400 flex items-center justify-center mb-3"><svg class="w-6 h-6" ...></svg></div>
    <p class="text-sm font-medium text-gray-900">No hay alertas con estos filtros</p>
    <p class="text-xs text-gray-500 mt-1">Prueba a quitar algún filtro o crea una nueva alerta.</p>
    <button class="BTN-PRIMARIO mt-4">Nueva alerta</button>
</div>
```

Título en una frase que diga qué falta; segunda línea con el siguiente paso. Dentro de
una tabla, en un `<td colspan>` con el mismo bloque. Textos: "No hay…" para listas
filtradas, "Aún no…" para listas vacías por primera vez.

## Paginación

```html
<nav class="flex items-center justify-between px-4 sm:px-6 py-3 border-t border-gray-200 text-sm text-gray-500" aria-label="Paginación">
    <p>Mostrando <span class="font-medium text-gray-900">1-25</span> de <span class="font-medium text-gray-900">312</span></p>
    <div class="flex gap-2">
        <a href="?page=1" class="BTN-SECUNDARIO px-3 py-1.5 text-xs" aria-disabled="true">Anterior</a>
        <a href="?page=3" class="BTN-SECUNDARIO px-3 py-1.5 text-xs">Siguiente</a>
    </div>
</nav>
```

## Confirmación

`confirm()` nativo es aceptable para borrar una fila si el mensaje nombra el objeto:
`confirm('¿Eliminar al cliente Juan Pérez? Esta acción no se puede deshacer.')`. Para
acciones con consecuencias (cerrar alerta, reasignar agente, borrar propiedad con
visitas), usar el modal de confirmación de `ui_macros.html` (`confirm_modal`) con el
texto de la consecuencia y el botón destructivo en rojo.

## Acciones de fila

```html
<div class="flex items-center justify-end gap-1">
    <a href="/clients/1" class="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-blue-700 bg-blue-50 hover:bg-blue-100" title="Ver detalle">
        <svg class="w-4 h-4" aria-hidden="true">...</svg><span class="hidden sm:inline">Ver</span>
    </a>
    <button type="button" onclick="editClient(this)" data-client='{{ client_dict | tojson | forceescape }}' class="... text-gray-700 bg-gray-100 hover:bg-gray-200" title="Editar" aria-label="Editar">
        <svg class="w-4 h-4" aria-hidden="true">...</svg><span class="hidden sm:inline">Editar</span>
    </button>
    <form method="POST" action="/clients/1/delete" onsubmit="return confirm('¿Eliminar a {{ client.name | e }}?')" class="inline">
        <button type="submit" class="... text-red-700 bg-red-50 hover:bg-red-100" title="Eliminar" aria-label="Eliminar"><svg ...></svg></button>
    </form>
</div>
```

Máximo tres acciones visibles; el resto a un menú. Los datos para JS van en `data-*`
con `tojson`, nunca interpolados dentro de `onclick="f('{{ x }}')"`.

## Sidebar: marcar la página activa

En `components/sidebar.html`, cada enlace calcula si es la sección actual:

```jinja
{% set path = request.url.path %}
{% macro nav(href, label, match) -%}
{% set active = path == href or path.startswith(match) %}
<a href="{{ href }}" {% if active %}aria-current="page"{% endif %}
   class="flex items-center gap-3 px-6 py-3 text-sm font-medium transition-colors
          {% if active %}bg-gray-100 text-gray-900 border-r-2 border-gray-900{% else %}text-gray-600 hover:bg-gray-50 hover:text-gray-900{% endif %}">
    {{ caller() }}<span>{{ label }}</span>
</a>
{%- endmacro %}
```

Y las condiciones de rol se escriben una vez con `is_admin` en el contexto, no con
`request.state.user.role.name.lower() == 'admin'` seis veces.
