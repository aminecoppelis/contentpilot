/**
 * Transport de session côté client — reproduit le mécanisme original
 * (Cahier technique §4.2) : le cookie pg_session suffit pour les
 * navigations classiques, mais les appels fetch() portent en plus les
 * en-têtes X-PG-Session-Id / X-PG-Request-Token pour les cas cross-contexte.
 * Ces valeurs sont injectées côté serveur dans window.__PG_AUTH par le
 * template de base (voir base.html si activé).
 */
(function () {
  if (window.__pgAuthTransportInstalled) return;
  window.__pgAuthTransportInstalled = true;

  var auth = window.__PG_AUTH || {};
  var originalFetch = window.fetch.bind(window);

  window.fetch = function (input, init) {
    init = init || {};
    init.headers = new Headers(init.headers || {});
    if (auth.session_id) init.headers.set('X-PG-Session-Id', auth.session_id);
    if (auth.request_token) init.headers.set('X-PG-Request-Token', auth.request_token);
    init.credentials = init.credentials || 'same-origin';
    return originalFetch(input, init);
  };
})();

// Anti-bot : timestamp de démarrage du formulaire (Cahier technique §3.3)
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('form[data-anti-bot]').forEach(function (form) {
    var hidden = form.querySelector('input[name=form_started_at]');
    if (hidden) hidden.value = Date.now();
  });
});
