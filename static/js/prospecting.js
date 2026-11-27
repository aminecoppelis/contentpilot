(() => {
  document.querySelectorAll('[data-prospecting-avatar]').forEach(image => {
    image.addEventListener('error', () => { image.hidden = true; });
    if (image.complete && !image.naturalWidth) image.hidden = true;
  });
  const detail = document.querySelector('[data-prospecting-detail]');
  const dashboard = document.querySelector('[data-prospecting-dashboard]');
  const active = status => status === 'queued' || status === 'running';
  let latest = new Map();
  let edited = false;

  document.querySelector('[data-select-prospects]')?.addEventListener('click', event => {
    const boxes = [...event.currentTarget.form.querySelectorAll('input[name="slugs"]:not(:disabled)')];
    const select = boxes.some(box => !box.checked);
    boxes.forEach(box => { box.checked = select; });
    edited = true;
  });

  function renderStats() {
    document.querySelectorAll('[data-prospecting-id]').forEach(row => {
      const stats = latest.get(row.dataset.prospectingId);
      if (!stats) return;
      const wasActive = active(row.dataset.searchStatus);
      row.dataset.searchStatus = stats.search_status;
      const values = { ...stats, status: stats.status_label, progress: `${stats.search_progress}%` };
      row.querySelectorAll('[data-stat]').forEach(cell => {
        const value = values[cell.dataset.stat];
        if (value !== undefined) cell.textContent = value;
      });
      row.querySelector('[data-meter]').value = stats.search_progress;
      if (row !== detail) return;
      detail.querySelector('[data-search-result]').textContent = stats.result_label;
      if (wasActive && !active(stats.search_status)) {
        if (!edited) window.location.replace(detail.querySelector('[data-prospecting-refresh]').href);
        else detail.querySelector('[data-prospecting-refresh]').hidden = false;
      }
    });
  }

  if (detail) {
    document.querySelector('main')?.addEventListener('input', () => { edited = true; });
    const search = detail.querySelector('[data-prospecting-search]');
    search?.addEventListener('submit', () => {
      search.querySelector('button[type="submit"]').disabled = true;
      search.querySelector('[data-prospecting-progress]').hidden = false;
    });
  }
  if (!detail && !dashboard) return;
  document.addEventListener('pg:grid-data-bound', renderStats);
  const query = new URLSearchParams({ lang: document.documentElement.lang });
  if (detail) query.set('campaign_id', detail.dataset.prospectingId);
  const url = `/app/prospecting/progress?${query}`;
  async function poll() {
    try {
      const response = await fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store' });
      if ([401, 403, 404].includes(response.status)) return;
      if (!response.ok) throw new Error('Progress unavailable');
      const rows = await response.json();
      latest = new Map(rows.map(row => [row.id, row]));
      renderStats();
      if (!rows.some(row => active(row.search_status))) return;
    } catch {
      // Keep polling if a transient network error interrupted an active search.
      if (!document.querySelector('[data-search-status="queued"], [data-search-status="running"]')) return;
    }
    window.setTimeout(poll, 3000);
  }
  poll();
})();
