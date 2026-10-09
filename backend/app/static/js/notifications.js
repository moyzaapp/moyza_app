/*
 * Campana de notificaciones in-app (navbar). PLAN_DASHBOARD_INICIO.md §4.4.
 *
 *  - Contador de no leídas: /api/notifications/unread-count al cargar y cada
 *    2 minutos (mismo patrón que el badge de compradores).
 *  - Al abrir: las 8 últimas (/api/notifications/recent) y "Marcar todas
 *    como leídas" (/api/notifications/mark-read). Escape y clic fuera cierran.
 *  - Todo el texto se inserta con textContent (sin innerHTML con datos).
 */
(function () {
  'use strict';

  var root = document.getElementById('notifBell');
  if (!root) return;

  var btn = document.getElementById('notifBellBtn');
  var panel = document.getElementById('notifPanel');
  var list = document.getElementById('notifList');
  var badge = document.getElementById('notifBadge');
  var sr = document.getElementById('notifSr');
  var markAll = document.getElementById('notifMarkAll');

  var TONES = {
    blue: 'bg-blue-100 text-blue-600', green: 'bg-green-100 text-green-600',
    amber: 'bg-amber-100 text-amber-600', red: 'bg-red-100 text-red-600', gray: 'bg-gray-100 text-gray-600'
  };
  // Mismo icono por tipo que en el Inicio (dashboard/components/icons.html)
  var ICONS = {
    home: 'm2.25 12 8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25',
    users: 'M15 19.128a9.38 9.38 0 0 0 2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 0 1 8.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0 1 11.964-3.07M12 6.375a3.375 3.375 0 1 1-6.75 0 3.375 3.375 0 0 1 6.75 0Zm8.25 2.25a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z',
    document: 'M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 0 1 9 9v.375M10.125 2.25A3.375 3.375 0 0 1 13.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 0 1 3.375 3.375M9 15l2.25 2.25L15 12',
    chat: 'M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z',
    clock: 'M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z'
  };
  var BELL = 'M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0';

  function setCount(n) {
    n = n || 0;
    badge.textContent = n > 99 ? '99+' : String(n);
    badge.classList.toggle('hidden', n === 0);
    btn.setAttribute('aria-label', n ? 'Notificaciones, ' + n + ' sin leer' : 'Notificaciones');
    markAll.classList.toggle('hidden', n === 0);
  }

  function refreshCount() {
    fetch('/api/notifications/unread-count', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) setCount(data.unread_count); })
      .catch(function () { /* sin red: se reintenta en el siguiente ciclo */ });
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function relative(iso) {
    var diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return 'ahora';
    if (diff < 3600) return 'hace ' + Math.floor(diff / 60) + ' min';
    if (diff < 86400) return 'hace ' + Math.floor(diff / 3600) + ' h';
    if (diff < 172800) return 'ayer';
    return new Date(iso).toLocaleDateString('es-ES', { timeZone: 'Europe/Madrid', day: '2-digit', month: '2-digit' });
  }

  function message(text) {
    list.textContent = '';
    var li = el('li', 'px-4 py-6 text-center text-sm text-gray-500', text);
    list.appendChild(li);
  }

  function render(items) {
    list.textContent = '';
    if (!items.length) { message('Aún no tienes notificaciones'); return; }
    items.forEach(function (n) {
      var li = el('li');
      var a = el('a', 'flex items-start gap-3 px-4 py-3 transition-colors ' + (n.read ? 'hover:bg-gray-50' : 'bg-blue-50/60 hover:bg-blue-50'));
      a.href = n.url;
      var box = el('span', 'w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ' + (TONES[n.tone] || TONES.gray));
      box.setAttribute('aria-hidden', 'true');
      var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class', 'w-5 h-5'); svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '1.5'); svg.setAttribute('viewBox', '0 0 24 24');
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('stroke-linecap', 'round'); path.setAttribute('stroke-linejoin', 'round'); path.setAttribute('d', ICONS[n.icon] || BELL);
      svg.appendChild(path); box.appendChild(svg);
      var body = el('span', 'min-w-0 flex-1');
      body.appendChild(el('span', 'block text-sm ' + (n.read ? 'text-gray-700' : 'font-semibold text-gray-900'), n.title));
      if (n.body) body.appendChild(el('span', 'block text-xs text-gray-500 mt-0.5 truncate', n.body));
      body.appendChild(el('span', 'block text-xs text-gray-500 mt-0.5', relative(n.created_at)));
      a.appendChild(box); a.appendChild(body);
      if (!n.read) {
        var dot = el('span', 'w-2 h-2 rounded-full bg-blue-600 shrink-0 mt-2');
        dot.setAttribute('aria-hidden', 'true');
        a.appendChild(dot);
      }
      li.appendChild(a);
      list.appendChild(li);
    });
  }

  function load() {
    fetch('/api/notifications/recent?limit=8', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) { render(data.items || []); setCount(data.unread_count); })
      .catch(function () { message('No se pudieron cargar las notificaciones'); });
  }

  function toggle(open) {
    var isOpen = open !== undefined ? open : panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !isOpen);
    btn.setAttribute('aria-expanded', String(isOpen));
    if (isOpen) load();
  }

  btn.addEventListener('click', function (e) { e.stopPropagation(); toggle(); });
  document.addEventListener('click', function (e) { if (!root.contains(e.target)) toggle(false); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.classList.contains('hidden')) { toggle(false); btn.focus(); }
  });

  markAll.addEventListener('click', function () {
    markAll.disabled = true;
    fetch('/api/notifications/mark-read', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ all: true })
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data) { setCount(data.unread_count); sr.textContent = 'Notificaciones marcadas como leídas'; load(); }
      })
      .finally(function () { markAll.disabled = false; });
  });

  refreshCount();
  setInterval(refreshCount, 120000);
})();
