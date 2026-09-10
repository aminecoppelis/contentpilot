/* Toasts — notification flottante unifiée (thème clair + sombre via ui-kit).
   API : window.pgToast(message, type)  où type ∈ success | error | info | warning
   Empilement, icône par type, fermeture au clic, auto-masquage. */
(function () {
  'use strict';

  var ICONS = {
    success: '<path d="M20 6 9 17l-5-5"/>',
    error:   '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    info:    '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    warning: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>'
  };

  function getContainer() {
    var c = document.getElementById('pgToastContainer');
    if (!c) {
      c = document.createElement('div');
      c.id = 'pgToastContainer';
      c.className = 'pgToastContainer';
      c.setAttribute('aria-live', 'polite');
      c.setAttribute('aria-atomic', 'true');
      document.body.appendChild(c);
    }
    return c;
  }

  window.pgToast = function (message, type) {
    var text = String(message == null ? '' : message).trim();
    if (!text) return;
    var kind = (type === 'error' || type === 'info' || type === 'warning') ? type : 'success';
    var c = getContainer();

    var el = document.createElement('div');
    el.className = 'pgToast ' + kind;
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');

    var icon = document.createElement('span');
    icon.className = 'pgToastIcon';
    icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[kind] || ICONS.success) + '</svg>';

    var body = document.createElement('span');
    body.className = 'pgToastBody';
    body.textContent = text;

    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'pgToastClose';
    close.setAttribute('aria-label', (window.t ? window.t('js.close') : 'Fermer'));
    close.innerHTML = '&times;';

    el.appendChild(icon);
    el.appendChild(body);
    el.appendChild(close);
    c.appendChild(el);

    requestAnimationFrame(function () { el.classList.add('show'); });

    var timer = setTimeout(dismiss, kind === 'error' ? 6000 : 4000);
    function dismiss() {
      clearTimeout(timer);
      el.classList.remove('show');
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 240);
    }
    close.addEventListener('click', dismiss);
    el.addEventListener('click', function (e) { if (e.target === el || e.target === body) dismiss(); });
    return dismiss;
  };
})();
