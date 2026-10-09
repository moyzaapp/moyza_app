/*
 * Inicio (/dashboard). PLAN_DASHBOARD_INICIO.md.
 *
 *  - Gráficas de tendencia: cada <canvas data-trend-kind> tiene su JSON en
 *    <script type="application/json" id="{canvasId}Data">. "lines" = una
 *    línea por serie (agente); "bars" = barras apiladas por serie + línea de
 *    total (equipo). Paleta y opciones de references/charts.md del skill.
 *    Si Chart.js no carga: banner ámbar y la tabla de datos queda abierta.
 *  - Ventana de compradores sin atender: se abre al entrar y, una vez cerrada,
 *    no vuelve a abrirse ese día en este navegador (localStorage con la
 *    fecha de Madrid). Si localStorage no está disponible, se muestra siempre.
 */
(function () {
  'use strict';

  var INK = '#374151';
  var MUTED = '#6B7280';
  var GRID = '#F3F4F6';
  var TOTAL = '#111827';

  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  function chartFallback(canvas) {
    var section = canvas.closest('section');
    var banner = document.createElement('div');
    banner.className = 'mb-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900';
    banner.setAttribute('role', 'status');
    banner.textContent = 'No se pudieron cargar las gráficas. Los datos están en la tabla.';
    var wrap = canvas.parentElement;
    wrap.parentElement.insertBefore(banner, wrap);
    wrap.classList.add('hidden');
    if (section) section.querySelectorAll('details').forEach(function (d) { d.open = true; });
  }

  function baseOptions(stacked) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 12, boxHeight: 12, usePointStyle: true, color: INK, font: { size: 12 } } },
        tooltip: { backgroundColor: '#111827', titleColor: '#F9FAFB', bodyColor: '#F9FAFB', padding: 10, cornerRadius: 8 }
      },
      scales: {
        x: { stacked: stacked, grid: { display: false }, ticks: { color: MUTED, font: { size: 11 } } },
        y: { stacked: stacked, beginAtZero: true, suggestedMax: 4, grid: { color: GRID }, ticks: { color: MUTED, font: { size: 11 }, precision: 0 }, border: { display: false } }
      }
    };
  }

  function mountTrend(canvas) {
    var data = readJson(canvas.id + 'Data');
    if (!data) return;
    if (typeof window.Chart === 'undefined') { chartFallback(canvas); return; }

    var datasets;
    if (canvas.dataset.trendKind === 'bars') {
      datasets = data.series.filter(function (s) { return s.key !== 'total'; }).map(function (s) {
        return {
          type: 'bar', label: s.label, data: s.data, backgroundColor: s.color,
          borderRadius: 4, maxBarThickness: 28, categoryPercentage: 0.7, stack: 'team', order: 2
        };
      });
      var total = data.series.filter(function (s) { return s.key === 'total'; })[0];
      if (total) {
        datasets.push({
          type: 'line', label: total.label, data: total.data, borderColor: TOTAL, backgroundColor: TOTAL,
          borderWidth: 2, pointRadius: 3, tension: 0.3, order: 1, yAxisID: 'y'
        });
      }
    } else {
      datasets = data.series.map(function (s, i) {
        return {
          type: 'line', label: s.label, data: s.data, borderColor: s.color, backgroundColor: s.color,
          borderWidth: 2, tension: 0.3, pointRadius: i === 0 ? 3 : 0, pointHoverRadius: 5
        };
      });
    }

    new window.Chart(canvas, {
      data: { labels: data.labels, datasets: datasets },
      options: baseOptions(data.stacked)
    });
  }

  document.querySelectorAll('canvas[data-trend-kind]').forEach(mountTrend);

  // ---- Ventana de compradores sin atender (una vez al día) ---------------

  function madridToday() {
    try {
      return new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Madrid' });
    } catch (e) {
      return new Date().toISOString().slice(0, 10);
    }
  }

  function storageGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }

  function storageSet(key, value) {
    try {
      // Limpia las marcas de días anteriores
      var prefix = key.replace(/_\d{4}-\d{2}-\d{2}$/, '_');
      for (var i = window.localStorage.length - 1; i >= 0; i--) {
        var k = window.localStorage.key(i);
        if (k && k.indexOf(prefix) === 0 && k !== key) window.localStorage.removeItem(k);
      }
      window.localStorage.setItem(key, value);
    } catch (e) { /* sin almacenamiento: se volverá a mostrar */ }
  }

  document.querySelectorAll('[data-dismiss-daily]').forEach(function (marker) {
    var modal = marker.closest('[role="dialog"]');
    if (!modal || !window.UI) return;
    var key = marker.getAttribute('data-dismiss-daily') + '_' + madridToday();

    function remember() { storageSet(key, '1'); }

    // Cualquier cierre (X, fondo, "Lo reviso después", Escape) cuenta como visto hoy
    modal.addEventListener('click', function (e) {
      if (e.target.closest('[data-modal-close]')) remember();
    });
    // En captura: ui.js cierra el modal con Escape en su propio listener
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.classList.contains('hidden')) remember();
    }, true);

    if (!storageGet(key)) window.UI.openModal(modal.id);
  });
})();
