/* pg-ui — boîtes de dialogue jolies (remplacent window.confirm / window.alert).
   window.pgConfirm(message, opts?) -> Promise<boolean>
     opts : { title, confirmText, cancelText, danger:true }
   window.pgAlert(message, opts?)   -> Promise<void>
   Thème clair + sombre via ui-kit, piégeage du focus, Échap = annuler. */
(function () {
  'use strict';

  function tr(key, fallback) {
    var v = window.t ? window.t(key) : null;
    return (v && v !== key) ? v : fallback;
  }

  function build(opts) {
    var overlay = document.createElement('div');
    overlay.className = 'pgDialogOverlay';
    overlay.setAttribute('role', 'presentation');

    var box = document.createElement('div');
    box.className = 'pgDialog' + (opts.danger ? ' isDanger' : '');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');

    var h = document.createElement('h2');
    h.className = 'pgDialogTitle';
    h.id = 'pgDialogTitle_' + Date.now();
    h.textContent = opts.title || tr(opts.danger ? 'js.confirm.title_danger' : 'js.confirm.title', 'Confirmation');
    box.setAttribute('aria-labelledby', h.id);

    var p = document.createElement('p');
    p.className = 'pgDialogText';
    p.textContent = String(opts.message == null ? '' : opts.message);

    var actions = document.createElement('div');
    actions.className = 'pgDialogActions';

    var cancelBtn = null;
    if (opts.mode !== 'alert') {
      cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'pgDialogBtn ghost';
      cancelBtn.textContent = opts.cancelText || tr('js.cancel', 'Annuler');
      actions.appendChild(cancelBtn);
    }

    var okBtn = document.createElement('button');
    okBtn.type = 'button';
    okBtn.className = 'pgDialogBtn ' + (opts.danger ? 'danger' : 'primary');
    okBtn.textContent = opts.confirmText || tr(opts.mode === 'alert' ? 'js.ok' : 'js.confirm', 'Confirmer');
    actions.appendChild(okBtn);

    box.appendChild(h);
    box.appendChild(p);
    box.appendChild(actions);
    overlay.appendChild(box);

    return { overlay: overlay, box: box, okBtn: okBtn, cancelBtn: cancelBtn };
  }

  function open(opts) {
    return new Promise(function (resolve) {
      var parts = build(opts);
      var lastActive = document.activeElement;
      document.body.appendChild(parts.overlay);
      requestAnimationFrame(function () { parts.overlay.classList.add('show'); });
      (opts.mode === 'alert' ? parts.okBtn : (parts.cancelBtn || parts.okBtn)).focus();

      function done(value) {
        parts.overlay.classList.remove('show');
        document.removeEventListener('keydown', onKey, true);
        setTimeout(function () {
          if (parts.overlay.parentNode) parts.overlay.parentNode.removeChild(parts.overlay);
          try { if (lastActive && lastActive.focus) lastActive.focus(); } catch (e) {}
        }, 200);
        resolve(value);
      }
      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); done(opts.mode === 'alert' ? undefined : false); }
        else if (e.key === 'Tab') {
          var f = parts.box.querySelectorAll('button');
          if (!f.length) return;
          var first = f[0], last = f[f.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      }
      document.addEventListener('keydown', onKey, true);
      parts.okBtn.addEventListener('click', function () { done(opts.mode === 'alert' ? undefined : true); });
      if (parts.cancelBtn) parts.cancelBtn.addEventListener('click', function () { done(false); });
      parts.overlay.addEventListener('click', function (e) {
        if (e.target === parts.overlay) done(opts.mode === 'alert' ? undefined : false);
      });
    });
  }

  window.pgConfirm = function (message, opts) {
    opts = opts || {};
    return open({
      message: message, mode: 'confirm',
      title: opts.title, confirmText: opts.confirmText, cancelText: opts.cancelText,
      danger: !!opts.danger
    });
  };

  window.pgAlert = function (message, opts) {
    opts = opts || {};
    return open({ message: message, mode: 'alert', title: opts.title, confirmText: opts.confirmText });
  };
})();
