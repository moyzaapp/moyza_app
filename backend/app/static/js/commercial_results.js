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
