---
name: moyza-ui-ux-pro
description: Sistema de diseño y guía de UX de la app MOYZA / MOES PREMIUM (FastAPI + Jinja2 + Tailwind local + JS vanilla + Chart.js). Úsalo SIEMPRE que haya que crear, modificar, revisar o "mejorar" cualquier pantalla, plantilla .html, modal, formulario, tabla, badge, tarjeta KPI, gráfica, dashboard, banner, flash, sidebar o estilo de esta app, aunque el usuario no diga "diseño" ni "UX" (por ejemplo "añade un botón", "pon un aviso", "haz esta tabla más clara", "que se vea bien en el móvil", "cambia los colores", "una gráfica de ventas"). También cuando se pida auditar o unificar la interfaz, elegir colores o iconos, o escribir JS de interfaz (modales, autocompletado, tabs). No aplica a PDFs generados ni a lógica de negocio.
---

# MOYZA UI/UX Pro

Sistema de diseño propio de la app inmobiliaria MOYZA / MOES PREMIUM. El objetivo es que
cada pantalla nueva o retocada salga **igual que el resto**, sea **intuitiva** para un
agente que la usa desde el móvil en la calle, y no haga falta recordar cómo está hecho
lo demás.

Stack real: FastAPI + Jinja2 renderizado en servidor, Tailwind 3 cargado en local como
Play CDN (`/static/js/tailwind.js`, genera clases en el navegador), JS vanilla en línea o
en `/static/js/`, Chart.js 4 en local. No hay React, ni build de CSS, ni librería de
componentes. Las clases Tailwind escritas desde Python o `innerHTML` funcionan.

## Cómo trabajar con este skill

1. **Lee `references/tokens.md`** antes de escribir una sola clase. Ahí están los colores,
   radios, tipografía, espaciado y el mapa de colores por estado. Si una decisión de color
   no está ahí, añádela ahí, no la inventes en la plantilla.
2. **Copia los componentes de `references/components.md`** (botón, tarjeta, tabla, badge,
   modal, formulario, autocompletado, banner, tabs, estado vacío). Si ya existe el macro en
   `components/ui_macros.html` del proyecto, úsalo. Si no existe y vas a repetir el mismo
   HTML en dos sitios, crea el macro desde `assets/ui_macros.html`.
3. **Gráficas y KPIs**: lee `references/charts.md`. Tiene la paleta de series, la tarjeta
   KPI, los umbrales de semáforo y el patrón de datos JSON embebido + tabla de respaldo.
4. **Antes de dar por terminada una pantalla**, pasa la checklist de `references/ux-rules.md`
   (accesibilidad, formularios, modales, móvil, feedback) y ejecuta el linter:
   `python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates`.
5. **Verifica en la app real**: el contenedor `moyza_backend` no recarga solo. Tras cambiar
   Python hace falta `docker restart moyza_backend`; las plantillas y estáticos se leen del
   disco (bind mount) pero Jinja cachea, así que también conviene reiniciar. Para ver el
   HTML renderizado como admin sin navegador:
   `python .claude/skills/moyza-ui-ux-pro/scripts/fetch_page.py /alerts --company MOES`.
6. Si el cambio toca algo que el audit marca como deuda (ver `references/audit-2026-10.md`),
   aprovecha para arreglarlo en esa pantalla, pero no reformes el resto de la app sin que
   lo pidan.

## Principios (el porqué de las reglas)

- **Una sola acción primaria por vista.** El botón principal es oscuro neutro
  (`bg-gray-900`) y hay como mucho uno por bloque. El resto son secundarios o de texto.
  Hoy conviven negro, azul e índigo; eso hace que el usuario no sepa qué es "lo importante".
- **El color significa estado, no decoración.** Verde = bien / completado, ámbar = atención /
  pendiente, rojo = problema / alta prioridad / destructivo, azul = información / en curso.
  Nunca se usa un color semántico para un elemento que no tenga ese significado.
- **La marca se nota, pero no manda.** El color de empresa (negro MOYZA, dorado MOES) va en
  la franja del sidebar, el avatar, el punto junto al nombre y la serie "venta" de gráficas.
  No en botones: el negro de MOYZA ya es el primario y el dorado como botón pierde contraste.
- **Mobile first de verdad.** Los agentes usan la app en el móvil. Toda tabla tiene
  `overflow-x-auto`, todo botón tiene un área táctil de 40 px, los modales no superan el
  alto de pantalla y nada depende de hover.
- **Feedback inmediato y en contexto.** Validación junto al campo, aviso dentro del modal
  (como el banner de alertas duplicadas), flash arriba solo para el resultado de una acción
  completa. Nunca `alert()` para algo que el usuario deba leer con calma.
- **Accesible por defecto.** `label for`, `role="dialog"`, Escape cierra, foco visible,
  contraste AA. No porque lo pida una norma, sino porque un formulario navegable con teclado
  es también más rápido para quien lo usa cien veces al día.
- **Copiar menos, macro más.** Si el mismo HTML aparece en tres plantillas, es un macro.
  Cambiar un radio en cuarenta sitios es cómo se llegó a la inconsistencia actual.

## Reglas rápidas (lo que más se repite)

| Elemento | Regla |
|---|---|
| Botón primario | `bg-gray-900 hover:bg-gray-800 text-white rounded-xl px-4 py-2.5 text-sm font-medium` |
| Botón secundario | `bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 rounded-xl` |
| Botón destructivo | Solo en confirmación: `bg-red-600 hover:bg-red-700 text-white` |
| Acción de fila | Icono + texto en `sm:`, solo icono en móvil, tono suave (`bg-blue-50 text-blue-700`) |
| Tarjeta | `bg-white rounded-2xl border border-gray-200` sin sombra; `p-4 sm:p-6` |
| Input / select | `rounded-xl border-gray-300 px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500` |
| Badge | `rounded-full px-2.5 py-0.5 text-xs font-medium` + tono del mapa de estados |
| Aviso | ámbar (`amber-*`), nunca `yellow-*` |
| H1 de página | `text-2xl sm:text-3xl font-bold text-gray-900` + subtítulo `text-sm text-gray-500` |
| Contenido | El `<main>` ya trae `p-4 sm:p-6 lg:p-8`; no añadas otro padding igual dentro |
| Iconos | Heroicons outline 24, `stroke-width="1.5"`, `w-5 h-5`. Nada de emojis como icono |
| Modal | `role="dialog" aria-modal="true"`, cierre con Escape y clic en el fondo, foco al abrir |
| Datos a JS | `{{ valor | tojson }}` o `data-*`; nunca `'{{ texto }}'` dentro de `onclick` |

## Cuándo preguntar y cuándo decidir

Decide tú cuando la respuesta está en `tokens.md` o `components.md`. Pregunta solo si el
cambio implica una decisión de producto (por ejemplo, qué métrica va en un KPI, qué estados
se muestran a un agente o si una acción se abre a agentes además de admin).

## Estructura del skill

- `references/tokens.md`: colores, marca por empresa, tipografía, radios, espaciado, mapa de estados.
- `references/components.md`: HTML canónico de cada componente y el JS mínimo que lo acompaña.
- `references/charts.md`: Chart.js, paleta de series, KPIs, dashboards, umbrales.
- `references/ux-rules.md`: checklist de accesibilidad, formularios, modales, móvil, feedback, roles.
- `references/audit-2026-10.md`: estado real de la interfaz en octubre de 2026 y hoja de ruta de refactor.
- `assets/ui_macros.html`: macros Jinja listos para copiar a `backend/app/web/templates/components/`.
- `assets/ui.js`: helper de modales accesibles y guardia de doble envío, para `/static/js/`.
- `scripts/ui_lint.py`: detecta desviaciones del sistema (colores fuera del mapa, modales sin `role`, tablas sin scroll, `yellow`, emojis, interpolación insegura).
- `scripts/fetch_page.py`: descarga una página renderizada como admin desde el contenedor.
