/**
 * Configuración de Tailwind 3 para compilar app/static/css/tailwind.css.
 *
 * El CSS se genera en el build de Docker (etapa `css` del Dockerfile) o en local
 * con `scripts/build_css.sh`. Solo entran las clases que aparecen escritas
 * literalmente en los archivos de `content`: una clase construida por partes
 * (p. ej. "bg-" + color + "-100") NO se genera. Ver TAILWIND_BUILD.md.
 *
 * @type {import('tailwindcss').Config}
 */
module.exports = {
  content: [
    "./app/web/templates/**/*.html",
    // Clases en strings de JS (alert-duplicates.js, ui.js, dashboard.js…)
    "./app/static/js/**/*.js",
    // Librerías de terceros: no tienen clases nuestras y solo añadirían ruido
    "!./app/static/js/tailwind.js",
    "!./app/static/js/chart.umd.js",
    // Clases devueltas desde Python (constants.py stage_badge_color…)
    "./app/**/*.py",
  ],
  theme: { extend: {} },
  plugins: [],
};
