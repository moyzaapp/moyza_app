/*
 * Resultados Comerciales · pestaña Evolución.
 *
 * Lee el JSON del año (#evolution-data) y monta dos gráficas con Chart.js:
 *   1. Resultados por agente: barras horizontales apiladas venta / alquiler
 *      (+ otros si existen) con una marca discontinua en el objetivo anual.
 *   2. Evolución mensual: con "Todos", barras apiladas del equipo y línea del
 *      total; con un agente, una línea por tipo.
 * Indicador y agente se cambian sin recargar. Bajo cada gráfica se rellena
 * una tabla con los mismos datos (también si Chart.js no carga).
 *
 * Pestaña Rendimiento (solo admin): panel lateral "de dónde sale el número"
 * (PLAN_TRAZABILIDAD_INDICADORES.md). La lupa de cada tarjeta lleva la URL en
 * data-metric-detail; el panel se abre con UI.openModal y carga el parcial por
 * fetch (esqueleto mientras carga, error con "Reintentar" dentro del panel).
 * "Ver más" (data-metric-more) añade la página siguiente a la tabla.
 */
(function () {
  'use strict';

  const dataEl = document.getElementById('evolution-data');
  if (!dataEl) return;

  const data = JSON.parse(dataEl.textContent);
  const colors = JSON.parse(document.getElementById('evolution-colors').textContent);
  const KINDS = ['venta', 'alquiler', 'otros'];
  const KIND_LABELS = { venta: 'Venta', alquiler: 'Alquiler', otros: 'Otros' };
  const SURFACE = '#ffffff';
  const INK = '#374151';      // gray-700
  const MUTED = '#6B7280';    // gray-500
  const GRID = '#F3F4F6';     // gray-100
  // Total y objetivo en gris-900 (skill: references/charts.md); venta es blue-600
  const ACCENT = '#111827';   // gray-900

  // El JSON llega con las claves ordenadas alfabéticamente: el orden lo da la plantilla
  const firstButton = document.querySelector('.evo-indicator[aria-checked="true"]');
  const state = { indicator: firstButton ? firstButton.dataset.indicator : Object.keys(data.indicators)[0], agent: 'all' };
  const charts = { agents: null, monthly: null };
  const hasChart = typeof window.Chart !== 'undefined';

  if (!hasChart) {
    document.getElementById('evo-chart-error').classList.remove('hidden');
    document.querySelectorAll('section details').forEach((d) => { d.open = true; });
  } else {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = MUTED;
  }

  // ------------------------------------------------------------------
  // Datos derivados
  // ------------------------------------------------------------------

  const sum = (arr) => arr.reduce((a, b) => a + b, 0);

  function agentTotals(indicator) {
    return data.agents.map((a) => a.totals[indicator]);
  }

  function monthlySeries(indicator, agentId) {
    const agents = agentId === 'all'
      ? data.agents
      : data.agents.filter((a) => String(a.id) === String(agentId));
    const series = {};
    KINDS.forEach((kind) => {
      series[kind] = data.months.map((_, m) => sum(agents.map((a) => a.monthly[indicator][kind][m])));
    });
    series.total = data.months.map((_, m) => sum(KINDS.map((k) => series[k][m])));
    return series;
  }

  // "Otros" solo aparece si hay algún valor (snapshots antiguos o tipos raros)
  function visibleKinds(valuesByKind) {
    return KINDS.filter((k) => k !== 'otros' || sum(valuesByKind[k]) > 0);
  }

  // ------------------------------------------------------------------
  // Plugin: marca del objetivo anual en cada barra de agente
  // ------------------------------------------------------------------

  const targetMarker = {
    id: 'targetMarker',
    afterDatasetsDraw(chart, _args, opts) {
      const targets = opts.targets || [];
      const { ctx, scales: { x, y } } = chart;
      const band = (y.getPixelForValue(1) - y.getPixelForValue(0)) || 40;
      ctx.save();
      targets.forEach((t, i) => {
        if (!t) return;
        const px = x.getPixelForValue(t);
        const py = y.getPixelForValue(i);
        // Halo claro + trazo discontinuo: visible sobre la barra y sobre el fondo
        [[SURFACE, 5, []], [ACCENT, 2, [4, 3]]].forEach(([color, width, dash]) => {
          ctx.strokeStyle = color;
          ctx.lineWidth = width;
          ctx.setLineDash(dash);
          ctx.beginPath();
          ctx.moveTo(px, py - band * 0.38);
          ctx.lineTo(px, py + band * 0.38);
          ctx.stroke();
        });
      });
      ctx.restore();
    },
  };

  // ------------------------------------------------------------------
  // Gráfica 1: por agente
  // ------------------------------------------------------------------

  function renderAgentsChart() {
    const indicator = state.indicator;
    const totals = agentTotals(indicator);
    const byKind = {};
    KINDS.forEach((k) => { byKind[k] = totals.map((t) => t[k]); });
    const kinds = visibleKinds(byKind);
    const targets = totals.map((t) => t.target);
    const maxValue = Math.max(0, ...totals.map((t) => t.total), ...targets.map((t) => t || 0));

    fillAgentsTable(totals);
    // Estado vacío: no se pintan ejes sin datos
    const empty = sum(totals.map((t) => t.total)) === 0;
    toggleEmpty('evo-agents', empty);
    if (empty && charts.agents) { charts.agents.destroy(); charts.agents = null; }
    if (empty) return;

    if (!hasChart) return;
    if (charts.agents) charts.agents.destroy();

    charts.agents = new Chart(document.getElementById('evo-agents-chart'), {
      type: 'bar',
      data: {
        labels: data.agents.map((a) => a.name),
        datasets: kinds.map((k, i) => ({
          label: KIND_LABELS[k],
          data: byKind[k],
          backgroundColor: colors[k],
          borderColor: SURFACE,
          borderWidth: { right: 2 },
          borderSkipped: false,
          // Solo el segmento exterior lleva el extremo redondeado
          borderRadius: i === kinds.length - 1 ? { topRight: 4, bottomRight: 4 } : 0,
          maxBarThickness: 22,
          stack: 'total',
        })),
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', axis: 'y', intersect: false },
        scales: {
          x: {
            stacked: true,
            beginAtZero: true,
            suggestedMax: maxValue ? Math.ceil(maxValue * 1.1) : 5,
            ticks: { precision: 0, color: MUTED },
            grid: { color: GRID },
            border: { display: false },
          },
          y: {
            stacked: true,
            ticks: { color: INK },
            grid: { display: false },
          },
        },
        plugins: {
          legend: { position: 'top', align: 'start', labels: { boxWidth: 12, boxHeight: 12, color: INK, sort: (a, b) => a.datasetIndex - b.datasetIndex } },
          tooltip: {
            callbacks: {
              footer: (items) => {
                const i = items[0].dataIndex;
                const t = totals[i];
                const lines = [`Total: ${t.total}`];
                lines.push(t.target ? `Objetivo anual: ${t.target}` : 'Sin objetivo anual');
                return lines;
              },
            },
          },
          targetMarker: { targets },
        },
      },
      plugins: [targetMarker],
    });
  }

  function fillAgentsTable(totals) {
    const tbody = document.querySelector('#evo-agents-table tbody');
    tbody.innerHTML = '';
    data.agents.forEach((a, i) => {
      const t = totals[i];
      tbody.appendChild(row([
        a.name, t.venta, t.alquiler, t.otros, t.total, t.target == null ? '—' : t.target,
      ], true));
    });
  }

  // ------------------------------------------------------------------
  // Gráfica 2: evolución mensual
  // ------------------------------------------------------------------

  function renderMonthlyChart() {
    const series = monthlySeries(state.indicator, state.agent);
    const kinds = visibleKinds(series);
    const team = state.agent === 'all';

    document.getElementById('evo-monthly-help').textContent = team
      ? 'Equipo: venta y alquiler apilados, con la línea negra del total'
      : 'Agente: una línea por tipo de operación';

    fillMonthlyTable(series);
    const empty = sum(series.total) === 0;
    toggleEmpty('evo-monthly', empty);
    if (empty && charts.monthly) { charts.monthly.destroy(); charts.monthly = null; }
    if (empty) return;

    if (!hasChart) return;
    if (charts.monthly) charts.monthly.destroy();

    let datasets;
    if (team) {
      datasets = kinds.map((k, i) => ({
        type: 'bar',
        label: KIND_LABELS[k],
        data: series[k],
        backgroundColor: colors[k],
        borderColor: SURFACE,
        borderWidth: { top: 2 },
        borderSkipped: false,
        borderRadius: i === kinds.length - 1 ? { topLeft: 4, topRight: 4 } : 0,
        maxBarThickness: 28,
        stack: 'team',
        order: 2,
      }));
      datasets.push({
        type: 'line',
        label: 'Total',
        data: series.total,
        borderColor: ACCENT,
        backgroundColor: ACCENT,
        borderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBackgroundColor: SURFACE,
        tension: 0,
        order: 1,
      });
    } else {
      datasets = kinds.map((k) => ({
        type: 'line',
        label: KIND_LABELS[k],
        data: series[k],
        borderColor: colors[k],
        backgroundColor: colors[k],
        borderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBorderColor: SURFACE,
        pointBorderWidth: 2,
        tension: 0,
      }));
    }

    charts.monthly = new Chart(document.getElementById('evo-monthly-chart'), {
      data: { labels: data.months, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { stacked: team, ticks: { color: INK }, grid: { display: false } },
          y: {
            stacked: team,
            beginAtZero: true,
            suggestedMax: 4,
            ticks: { precision: 0, color: MUTED },
            grid: { color: GRID },
            border: { display: false },
          },
        },
        plugins: {
          legend: { position: 'top', align: 'start', labels: { boxWidth: 12, boxHeight: 12, color: INK, sort: (a, b) => a.datasetIndex - b.datasetIndex } },
        },
      },
    });
  }

  function fillMonthlyTable(series) {
    const tbody = document.querySelector('#evo-monthly-table tbody');
    tbody.innerHTML = '';
    data.months.forEach((m, i) => {
      tbody.appendChild(row([m, series.venta[i], series.alquiler[i], series.otros[i], series.total[i]], true));
    });
  }

  // ------------------------------------------------------------------
  // Utilidades de UI
  // ------------------------------------------------------------------

  function row(cells, firstIsHeader) {
    const tr = document.createElement('tr');
    tr.className = 'border-b border-gray-100';
    cells.forEach((value, i) => {
      const cell = document.createElement(i === 0 && firstIsHeader ? 'th' : 'td');
      if (i === 0 && firstIsHeader) cell.scope = 'row';
      cell.className = i === 0 ? 'text-left px-3 py-2 font-medium text-gray-800' : 'text-right px-3 py-2 text-gray-700 tabular-nums';
      cell.textContent = value;
      tr.appendChild(cell);
    });
    return tr;
  }

  function toggleEmpty(prefix, empty) {
    document.getElementById(`${prefix}-empty`).classList.toggle('hidden', !empty);
    document.getElementById(`${prefix}-wrap`).classList.toggle('hidden', empty);
  }

  function updateLabels() {
    const label = data.indicators[state.indicator];
    document.querySelectorAll('.evo-indicator-label').forEach((el) => { el.textContent = label; });

    const select = document.getElementById('evo-agent');
    document.getElementById('evo-agent-label').textContent = select.options[select.selectedIndex].text;


    document.querySelectorAll('.evo-indicator').forEach((btn) => {
      const active = btn.dataset.indicator === state.indicator;
      btn.setAttribute('aria-checked', String(active));
      btn.classList.toggle('bg-gray-900', active);
      btn.classList.toggle('text-white', active);
      btn.classList.toggle('text-gray-600', !active);
      btn.classList.toggle('hover:bg-gray-50', !active);
    });
  }

  function render() {
    updateLabels();
    renderAgentsChart();
    renderMonthlyChart();
  }

  document.querySelectorAll('.evo-indicator').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.indicator = btn.dataset.indicator;
      render();
    });
  });

  document.getElementById('evo-agent').addEventListener('change', (e) => {
    state.agent = e.target.value;
    updateLabels();
    renderMonthlyChart();
  });

  render();
})();

(function () {
  'use strict';

  const drawer = document.getElementById('metricDrawer');
  if (!drawer || !window.UI) return;

  const body = document.getElementById('metricDrawerBody');
  const title = document.getElementById('metricDrawerTitle');
  const subtitle = document.getElementById('metricDrawerSubtitle');
  let controller = null;
  let currentUrl = null;

  const SKELETON =
    '<div class="p-4 sm:p-6 space-y-5 animate-pulse" aria-hidden="true">' +
      '<div class="space-y-2"><div class="h-3 w-24 rounded bg-gray-200"></div>' +
      '<div class="h-4 w-full rounded bg-gray-200"></div><div class="h-4 w-4/5 rounded bg-gray-200"></div></div>' +
      '<div class="h-20 rounded-xl bg-gray-100"></div>' +
      '<div class="space-y-2"><div class="h-10 rounded bg-gray-100"></div><div class="h-10 rounded bg-gray-100"></div>' +
      '<div class="h-10 rounded bg-gray-100"></div></div>' +
    '</div>' +
    '<p class="sr-only">Cargando el detalle…</p>';

  function errorHtml(message) {
    return '<div class="p-4 sm:p-6">' +
      '<div class="rounded-xl border border-red-200 bg-red-50 text-red-900 px-4 py-3" role="alert">' +
        '<p class="text-sm font-semibold">No se pudo cargar el detalle</p>' +
        '<p class="text-xs mt-1 opacity-90">' + UI.escapeHtml(message) + '</p>' +
        '<button type="button" data-metric-retry class="mt-3 inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/20">Reintentar</button>' +
      '</div>' +
    '</div>';
  }

  // Devuelve el HTML del parcial o lanza un Error con un mensaje para el usuario
  async function fetchPartial(url, signal) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'fetch' },
      signal: signal,
    });
    // Sesión caducada: el middleware redirige al login y fetch lo sigue
    if (response.redirected) throw new Error('Tu sesión ha caducado. Recarga la página e inicia sesión.');
    if (response.status === 403) throw new Error('Solo los administradores pueden ver este detalle.');
    if (response.status === 404) throw new Error('El agente o el indicador ya no existen en la empresa activa.');
    if (!response.ok) throw new Error('Error del servidor (' + response.status + '). Inténtalo de nuevo.');
    return response.text();
  }

  async function load(url) {
    if (controller) controller.abort();
    controller = new AbortController();
    currentUrl = url;
    body.innerHTML = SKELETON;
    body.setAttribute('aria-busy', 'true');
    try {
      body.innerHTML = await fetchPartial(url, controller.signal);
    } catch (err) {
      if (err.name === 'AbortError') return;
      body.innerHTML = errorHtml(err.message || 'Error de conexión. Inténtalo de nuevo.');
    } finally {
      body.setAttribute('aria-busy', 'false');
    }
    const scroller = drawer.querySelector('[data-modal-body]');
    if (scroller) scroller.scrollTop = 0;
  }

  async function loadMore(button) {
    const wrap = button.closest('[data-metric-more-wrap]');
    const tbody = body.querySelector('[data-metric-rows]');
    if (!wrap || !tbody) return;
    const label = button.textContent;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.textContent = 'Cargando…';
    try {
      const html = await fetchPartial(button.dataset.metricMore);
      const tpl = document.createElement('template');
      tpl.innerHTML = html.trim();
      const page = tpl.content.querySelector('[data-metric-page]');
      if (!page) throw new Error('Respuesta inesperada del servidor. Inténtalo de nuevo.');
      const rows = Array.from(page.querySelectorAll('tr[data-metric-row]'));
      rows.forEach((row) => tbody.appendChild(row));
      const nextWrap = page.querySelector('[data-metric-more-wrap]');
      if (nextWrap) wrap.replaceWith(nextWrap);
      // Foco en la primera fila nueva para seguir leyendo con teclado
      const firstLink = rows.length && rows[0].querySelector('a');
      if (firstLink) firstLink.focus({ preventScroll: false });
    } catch (err) {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      button.textContent = label;
      const msg = document.createElement('p');
      msg.className = 'text-xs text-red-600';
      msg.setAttribute('role', 'alert');
      msg.textContent = err.message || 'No se pudieron cargar más registros.';
      wrap.appendChild(msg);
    }
  }

  document.addEventListener('click', (e) => {
    const opener = e.target.closest('[data-metric-detail]');
    if (opener) {
      e.preventDefault();
      title.textContent = opener.dataset.metricTitle || 'Detalle del indicador';
      if (subtitle) subtitle.textContent = opener.dataset.metricSubtitle || '';
      UI.openModal('metricDrawer', opener);
      load(opener.dataset.metricDetail);
      return;
    }
    if (!drawer.contains(e.target)) return;
    const more = e.target.closest('[data-metric-more]');
    if (more) {
      e.preventDefault();
      loadMore(more);
      return;
    }
    if (e.target.closest('[data-metric-retry]') && currentUrl) {
      e.preventDefault();
      load(currentUrl);
    }
  });
})();
