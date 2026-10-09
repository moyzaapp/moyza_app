# Gráficas, KPIs y dashboards

## Librería

Chart.js 4 en local: `/static/js/chart.umd.js` (añadido en octubre de 2026 para
Resultados Comerciales). Se carga solo en las plantillas que lo usan, al final del
bloque de contenido, nunca en `base.html`. No usar CDN externo: la app se usa en
movilidad y a veces sin buena conexión.

## Patrón de datos

Los datos van del servidor a la gráfica con un bloque JSON embebido, no con fetch ni con
variables Jinja dentro del JS:

```html
<script type="application/json" id="salesByAgentData">{{ sales_by_agent | tojson }}</script>
<div class="relative h-72 sm:h-80">
    <canvas id="salesByAgent" role="img" aria-label="Ventas por agente en {{ year }}"></canvas>
</div>
<details class="mt-3">
    <summary class="text-xs text-gray-500 cursor-pointer">Ver datos en tabla</summary>
    <table class="mt-2 w-full text-xs">...</table>
</details>
```

Por qué: `tojson` evita inyección y errores con comillas; el `canvas` con `role="img"` y
la tabla de respaldo dan acceso a lectores de pantalla y a quien no cargue JS; el
contenedor con alto fijo evita que Chart.js crezca sin límite en móvil.

Si Chart.js no está disponible (`typeof Chart === 'undefined'`), mostrar un banner ámbar
"No se pudieron cargar las gráficas" y dejar visible la tabla.

## Paleta de series

| Serie | Color | Nota |
|---|---|---|
| Venta | `#2563EB` (blue-600) | Serie principal. No usar `brand_color`: el de MOYZA es negro y se confunde con el marcador de objetivo |
| Alquiler | `#F59E0B` (amber-500) | |
| Otros / sin clasificar | `#9CA3AF` (gray-400) | |
| Objetivo | `#111827` (gray-900), línea discontinua `borderDash: [6, 4]` | |
| Total (línea sobre barras) | `#111827` | Punto `pointRadius: 3` |
| Comparativa (periodo anterior) | misma serie con `alpha 0.35` | |

Series categóricas sin significado fijo (por agente, por portal): usar en orden
`#2563EB`, `#F59E0B`, `#10B981`, `#8B5CF6`, `#EF4444`, `#6B7280`. Máximo 6; a partir de
ahí, agrupar en "Otros".

Colores de apoyo: texto `#374151`, texto secundario `#6B7280`, rejilla `#F3F4F6`,
fondo del tooltip `#111827`.

## Opciones comunes de Chart.js

```js
const base = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 12, boxHeight: 12, usePointStyle: true, color: '#374151', font: { size: 12 } } },
        tooltip: { backgroundColor: '#111827', titleColor: '#F9FAFB', bodyColor: '#F9FAFB', padding: 10, cornerRadius: 8 }
    },
    scales: {
        x: { grid: { display: false }, ticks: { color: '#6B7280', font: { size: 11 } } },
        y: { grid: { color: '#F3F4F6' }, ticks: { color: '#6B7280', font: { size: 11 }, precision: 0 }, beginAtZero: true }
    }
};
```

Barras: `borderRadius: 4`, `maxBarThickness: 28`, `categoryPercentage: 0.7`.
Líneas: `tension: 0.3`, `borderWidth: 2`, `pointRadius: 0` salvo la última serie destacada.
Formato de moneda en ticks y tooltips: `new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })`.

## Qué gráfica para qué pregunta

| Pregunta | Gráfica |
|---|---|
| ¿Cómo va cada agente frente a su objetivo? | Barras horizontales apiladas (venta / alquiler) con marca de objetivo |
| ¿Cómo evoluciona el mes a mes? | Barras apiladas por mes + línea de total |
| ¿Qué parte del total es cada cosa? | Barras apiladas al 100 %. Evitar tarta salvo 2 o 3 categorías |
| ¿Un solo número con tendencia? | Tarjeta KPI con variación respecto al periodo anterior |
| ¿Distribución de tiempos (respuesta a alertas)? | Barras por tramo (0-1 h, 1-24 h, 1-3 d, +3 d) |

No usar gráficas para 1 o 2 valores: una tarjeta KPI es más clara.

## Tarjeta KPI

```html
<div class="bg-white rounded-2xl border border-gray-200 p-4 sm:p-5">
    <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
            <p class="text-sm font-medium text-gray-500">Pendientes</p>
            <p class="text-3xl font-bold text-amber-600 mt-1">12</p>
            <p class="text-xs text-gray-500 mt-1">3 sin atender más de 7 días</p>
        </div>
        <div class="w-10 h-10 rounded-lg bg-amber-100 text-amber-600 flex items-center justify-center shrink-0">
            <svg class="w-5 h-5" ...></svg>
        </div>
    </div>
</div>
```

- El color del valor sigue el mapa de estados (`tokens.md`). Un KPI neutro (total) va en `text-gray-900`.
- Máximo 4 KPIs por fila en escritorio (`grid grid-cols-2 lg:grid-cols-4 gap-4`), 2 en móvil.
- Si el KPI es clicable (filtra la tabla), es un `<a>` o `<button>` con `hover:border-gray-300` y, cuando está activo, `ring-2 ring-gray-900/10 border-gray-900`.
- Variación: `<span class="text-xs font-medium text-green-600">▲ 12 %</span>` solo si hay periodo de comparación. Rojo si baja y bajar es malo.

Hay un macro `kpi_card` en `assets/ui_macros.html`.

## Barras de progreso (objetivos)

```html
<div class="flex items-center justify-between text-xs text-gray-500 mb-1">
    <span>Captaciones</span><span class="font-medium text-gray-700">8 / 10</span>
</div>
<div class="h-2 rounded-full bg-gray-100 overflow-hidden" role="progressbar" aria-valuenow="80" aria-valuemin="0" aria-valuemax="100" aria-label="Captaciones: 8 de 10">
    <div class="h-full rounded-full bg-green-500" style="width: 80%"></div>
</div>
```

Color de la barra por semáforo: verde ≥ 100 %, ámbar ≥ 60 %, rojo por debajo. La barra
nunca supera el 100 % visual aunque el valor sí (se indica en el texto).

## Dashboards

- Orden de lectura: KPIs arriba (lo que importa hoy), gráfica de evolución en el centro,
  tabla de detalle abajo. Los filtros (periodo, agente, empresa) en una sola fila encima
  de los KPIs y aplican a todo.
- Periodo: selector segmentado Semana / Mes / Año + flechas ‹ ›, con el rango de fechas
  visible en texto ("1 - 31 oct 2026").
- Estado vacío de una gráfica: no pintar ejes vacíos; mostrar el estado vacío estándar
  dentro del mismo contenedor.
- El dashboard de admin en `/dashboard` es hoy un placeholder; cualquier KPI que se añada
  debe venir de una consulta real, nunca de un número fijo en la plantilla.
