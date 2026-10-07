/**
 * Filtres multi-sélection + scroll infini — port VERBATIM du script partagé
 * des pages Historique / Publications / Sujets du workflow original.
 * Seule adaptation : le préfixe de routes /webhook/V0 devient /app.
 */
(function(){
  function panelById(panelId){ return document.getElementById(panelId); }
  function statusInputs(panel){ return Array.prototype.slice.call(panel.querySelectorAll('input[data-status-option]')); }
  function getStatusSelectValues(panelId){
    var panel=panelById(panelId);
    if(!panel) return ['all'];
    var values=statusInputs(panel).filter(function(i){return i.checked;})
      .map(function(i){return String(i.value||'').toLowerCase();}).filter(Boolean);
    if(!values.length || values.indexOf('all')>=0) return ['all'];
    return values;
  }
  function labelForInput(input){ return input ? (input.getAttribute('data-label') || input.value || '') : ''; }

  window.toggleStatusDropdown=function(panelId){
    var panel=panelById(panelId);
    if(!panel) return false;
    var menu=panel.querySelector('[data-select2-menu]');
    var button=panel.querySelector('[data-select2-button]');
    var willOpen=!(menu && menu.classList.contains('open'));
    document.querySelectorAll('[data-select2-menu].open').forEach(function(m){m.classList.remove('open');});
    document.querySelectorAll('[data-select2-button].open').forEach(function(b){b.classList.remove('open');});
    if(menu && willOpen) menu.classList.add('open');
    if(button && willOpen) button.classList.add('open');
    return false;
  };

  window.syncStatusSelect=function(panelId, changed){
    var panel=panelById(panelId);
    if(!panel) return;
    var inputs=statusInputs(panel);
    var allInput=inputs.find(function(i){return i.value==='all';});
    var others=inputs.filter(function(i){return i.value!=='all';});
    if(changed && changed.value==='all' && changed.checked){ others.forEach(function(i){i.checked=false;}); }
    if(changed && changed.value!=='all' && changed.checked && allInput){ allInput.checked=false; }
    if(!others.some(function(i){return i.checked;}) && allInput){ allInput.checked=true; }
    var values=getStatusSelectValues(panelId);
    var labelsEl=panel.querySelector('[data-selected-labels]');
    if(labelsEl){
      if(values.indexOf('all')>=0){
        labelsEl.innerHTML='<span class="select2Placeholder">'+window.t('common.all')+'</span>';
      } else {
        labelsEl.innerHTML=inputs.filter(function(i){return i.checked && i.value!=='all';})
          .map(function(i){return '<span class="select2Chip">'+labelForInput(i).replace(/[&<>"']/g,function(c){
            return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];})+'</span>';}).join('');
      }
    }
  };

  window.applyStatusFilter=function(panelId){
    var panel=panelById(panelId);
    if(!panel) return false;
    var basePath=panel.getAttribute('data-base-path') || '/history';
    var values=getStatusSelectValues(panelId);
    var base='/app';
    var url=values.indexOf('all')>=0 ? (base + basePath)
      : (base + basePath + '?filter=' + encodeURIComponent(values.join(',')));
    window.location.href=url;
    return false;
  };

  document.addEventListener('click', function(event){
    if(event.target.closest('.select2Like')) return;
    document.querySelectorAll('[data-select2-menu].open').forEach(function(m){m.classList.remove('open');});
    document.querySelectorAll('[data-select2-button].open').forEach(function(b){b.classList.remove('open');});
  });
  document.addEventListener('DOMContentLoaded', function(){
    document.querySelectorAll('.filterPanel[id]').forEach(function(panel){ window.syncStatusSelect(panel.id); });
  });

  /* Scroll infini : charge la page suivante quand la sentinelle devient visible. */
  window.initInfiniteTable=function(opts){
    var tbody=document.getElementById(opts.tbodyId);
    var sentinel=document.getElementById(opts.sentinelId);
    var loadState=document.getElementById(opts.loadStateId);
    if(!tbody||!sentinel) return;
    var offset=Number(opts.initialOffset||0);
    var hasMore=Boolean(opts.hasMore);
    var loading=false;
    function render(rows){
      rows.forEach(function(html){
        var tmp=document.createElement('tbody');
        tmp.innerHTML=html;
        while(tmp.firstChild) tbody.appendChild(tmp.firstChild);
      });
    }
    async function loadMore(){
      if(loading||!hasMore) return;
      loading=true;
      if(loadState) loadState.textContent=window.t('common.loading');
      try{
        var url=new URL(opts.endpoint, window.location.origin);
        url.searchParams.set('offset', String(offset));
        var params=new URLSearchParams(window.location.search);
        if(params.get('filter')) url.searchParams.set('filter', params.get('filter'));
        var resp=await fetch(url.toString(), {credentials:'same-origin'});
        var data=await resp.json();
        var payload=data.data||data;
        render([payload.rows_html||'']);
        offset=Number(payload.next_offset||offset);
        hasMore=Boolean(payload.has_more);
        if(loadState) loadState.style.display=hasMore?'block':'none';
        if(loadState&&hasMore) loadState.textContent=window.t('common.scroll_more');
      }catch(e){
        if(loadState) loadState.textContent=window.t('common.load_error');
      }finally{ loading=false; }
    }
    var observer=new IntersectionObserver(function(entries){
      entries.forEach(function(entry){ if(entry.isIntersecting) loadMore(); });
    },{rootMargin:'240px'});
    observer.observe(sentinel);
  };
})();
