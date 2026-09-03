/**
 * Page "Mes réseaux" — port des interactions du workflow original :
 * menu kebab par ligne, actions (toggle/delete/remove_workspace/share/rename),
 * modale Buffer (nom interne + clé API + channel ID) et modale de partage.
 * Adaptation : ${WEBHOOK_BASE} -> /app.
 */
(function(){
  var WEBHOOK_BASE='/app';

  function networkClientEsc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }

  function toast(message,type){
    if(window.pgToast){ window.pgToast(message,type||'success'); return; }
    var el=document.getElementById('networkToast');
    if(!el){ alert(message); return; }
    el.textContent=message;
    el.style.background=type==='error'?'#fee2e2':'#dcfce7';
    el.style.color=type==='error'?'#991b1b':'#166534';
    el.style.display='block';
    clearTimeout(el.__t);
    el.__t=setTimeout(function(){el.style.display='none';},3600);
  }
  window.__networkToast=toast;

  async function action(payload){
    var r=await fetch(WEBHOOK_BASE+'/networks/action',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json().catch(function(){return {};});
    if(!r.ok||d.success===false) throw new Error(d.message||('HTTP '+r.status));
    return d.data||d;
  }

  function restoreNetworkKebabMenu(menu){
    if(!menu)return;
    menu.classList.remove('open','isPortal');
    menu.style.removeProperty('left');
    menu.style.removeProperty('right');
    menu.style.removeProperty('top');
    menu.style.removeProperty('bottom');
    menu.style.removeProperty('visibility');
    if(menu.__networkKebabOwner && menu.parentNode!==menu.__networkKebabOwner){
      menu.__networkKebabOwner.appendChild(menu);
    }
  }

  function closeNetworkKebabs(){
    document.querySelectorAll('.networkKebabMenu.open').forEach(restoreNetworkKebabMenu);
    document.querySelectorAll('.networkKebabBtn[aria-expanded="true"]').forEach(function(b){
      b.setAttribute('aria-expanded','false'); b.classList.remove('isOpen');});
  }
  window.closeNetworkKebabs=closeNetworkKebabs;

  function positionNetworkKebab(menu,btn){
    if(!menu||!btn)return;
    var gap=8;
    var margin=8;
    var buttonRect=btn.getBoundingClientRect();
    var menuRect=menu.getBoundingClientRect();
    var left=buttonRect.right-menuRect.width;
    left=Math.max(margin,Math.min(left,window.innerWidth-menuRect.width-margin));
    var below=buttonRect.bottom+gap;
    var above=buttonRect.top-menuRect.height-gap;
    var top=(below+menuRect.height<=window.innerHeight-margin || above<margin)?below:above;
    top=Math.max(margin,Math.min(top,window.innerHeight-menuRect.height-margin));
    menu.style.left=Math.round(left)+'px';
    menu.style.top=Math.round(top)+'px';
    menu.style.visibility='visible';
  }

  window.toggleNetworkKebab=function(id,btn,event){
    if(event)event.stopPropagation();
    var menu=document.getElementById('network-menu-'+id);
    if(!menu)return;
    var willOpen=!menu.classList.contains('open');
    closeNetworkKebabs();
    if(willOpen){
      menu.__networkKebabOwner=menu.parentNode;
      document.body.appendChild(menu);
      menu.classList.add('open','isPortal');
      menu.style.visibility='hidden';
      if(btn){ btn.classList.add('isOpen'); btn.setAttribute('aria-expanded','true'); }
      positionNetworkKebab(menu,btn);
    }
  };
  document.addEventListener('click',function(e){
    if(!e.target.closest || (!e.target.closest('.networkKebabWrap')&&!e.target.closest('.networkKebabMenu'))) closeNetworkKebabs();
  });
  window.addEventListener('resize',closeNetworkKebabs);
  window.addEventListener('scroll',closeNetworkKebabs,true);
  document.addEventListener('keydown',function(e){if(e.key==='Escape')closeNetworkKebabs();});

  window.toggleNetwork=async function(id,btn){
    closeNetworkKebabs(); btn.disabled=true;
    try{
      var d=await action({action:'toggle',id:id});
      var tr=document.getElementById('network-'+id);
      var s=tr&&tr.querySelector('[data-status]');
      if(s){ s.textContent=d.account.is_active?'Actif':'Désactivé';
             s.className='status '+(d.account.is_active?'on':'off'); }
      btn.textContent=d.account.is_active?'Désactiver':'Activer';
      toast('Statut mis à jour.');
    }catch(e){ toast('Modification impossible : '+e.message,'error'); }
    finally{ btn.disabled=false; }
  };

  window.deleteNetwork=async function(id,btn){
    closeNetworkKebabs();
    if(!confirm('Supprimer cette connexion ? Les publications existantes restent conservées.'))return;
    btn.disabled=true;
    try{
      await action({action:'delete',id:id});
      var row=document.getElementById('network-'+id); if(row)row.remove();
      adjustNetworkTotal(-1);
      toast('Connexion supprimée.');
    }catch(e){ toast('Suppression impossible : '+e.message,'error'); btn.disabled=false; }
  };

  window.removeNetworkFromWorkspace=async function(id,btn){
    closeNetworkKebabs();
    if(!confirm('Retirer ce compte du workspace actif ?'))return;
    btn.disabled=true;
    try{
      var d=await action({action:'remove_workspace',id:id});
      toast(d.message||'Compte retiré de ce workspace.','success');
      setTimeout(function(){location.reload();},500);
    }catch(e){ toast('Retrait impossible : '+e.message,'error'); btn.disabled=false; }
  };

  function adjustNetworkTotal(delta){
    var totals=Array.prototype.slice.call(document.querySelectorAll('[data-total]'));
    var current=totals.length?Number(totals[0].textContent||0):0;
    var next=Math.max(0,current+Number(delta||0));
    totals.forEach(function(el){el.textContent=String(next);});
  }

  /* --- Modale de partage --- */
  var currentShareNetworkId='';
  window.openShareNetworkModal=function(id,label){
    closeNetworkKebabs();
    var targets=Array.isArray(window.__shareTargets)?window.__shareTargets:[];
    var modal=document.getElementById('shareNetworkModal');
    var select=document.getElementById('shareNetworkWorkspaceSelect');
    var subtitle=document.getElementById('shareNetworkSubtitle');
    currentShareNetworkId=String(id||'');
    if(!modal||!select)return;
    if(!targets.length){ toast('Aucun autre workspace disponible.','error'); return; }
    select.innerHTML=targets.map(function(w){
      return '<option value="'+networkClientEsc(w.id)+'">'+networkClientEsc(w.name)+'</option>';}).join('');
    if(subtitle)subtitle.textContent='Partager '+String(label||'ce compte')+' avec un workspace spécifique.';
    modal.classList.add('isOpen'); modal.setAttribute('aria-hidden','false');
  };
  function closeShareModal(){
    var m=document.getElementById('shareNetworkModal');
    if(m){ m.classList.remove('isOpen'); m.setAttribute('aria-hidden','true'); }
  }
  document.addEventListener('DOMContentLoaded',function(){
    var cancel=document.getElementById('cancelShareNetworkBtn');
    if(cancel)cancel.addEventListener('click',closeShareModal);
    var confirmBtn=document.getElementById('confirmShareNetworkBtn');
    if(confirmBtn)confirmBtn.addEventListener('click',async function(){
      var select=document.getElementById('shareNetworkWorkspaceSelect');
      if(!select||!select.value)return;
      confirmBtn.disabled=true;
      try{
        await action({action:'share',id:currentShareNetworkId,target_workspace_id:select.value});
        toast('Compte partagé.'); closeShareModal();
      }catch(e){ toast('Partage impossible : '+e.message,'error'); }
      finally{ confirmBtn.disabled=false; }
    });

    var cancelEdit=document.getElementById('cancelEditNetworkBtn');
    if(cancelEdit)cancelEdit.addEventListener('click',closeEditModal);

    // BUG CORRIGÉ : ce bouton n'avait aucun handler — la modale de renommage
    // s'ouvrait (via openEditNetworkModal) mais « Enregistrer » ne faisait rien.
    var confirmEdit=document.getElementById('confirmEditNetworkBtn');
    if(confirmEdit)confirmEdit.addEventListener('click',async function(){
      var input=document.getElementById('editNetworkDisplayName');
      var name=String(input&&input.value||'').trim();
      if(!name){ toast('Le nom ne peut pas être vide.','error'); return; }
      confirmEdit.disabled=true;
      try{
        await action({action:'rename',id:currentEditNetworkId,display_name:name});
        var row=document.getElementById('network-'+currentEditNetworkId);
        var nameEl=row&&row.querySelector('[data-name]');
        if(nameEl)nameEl.textContent=name;
        toast('Nom mis à jour.');
        closeEditModal();
      }catch(e){ toast('Modification impossible : '+e.message,'error'); }
      finally{ confirmEdit.disabled=false; }
    });
  });

  /* --- Modale de renommage (fallback quand aucune reconnexion n'est possible) --- */
  var currentEditNetworkId='';
  function closeEditModal(){
    var m=document.getElementById('editNetworkModal');
    if(m){ m.classList.remove('isOpen'); m.setAttribute('aria-hidden','true'); }
  }
  window.openEditNetworkModal=function(id,label){
    closeNetworkKebabs();
    currentEditNetworkId=String(id||'');
    var m=document.getElementById('editNetworkModal');
    var input=document.getElementById('editNetworkDisplayName');
    if(!m)return false;
    if(input){ input.value=String(label||''); }
    m.classList.add('isOpen'); m.setAttribute('aria-hidden','false');
    if(input)setTimeout(function(){input.focus();input.select();},60);
    return false;
  };

  /* --- Modale Buffer --- */
  window.openBufferModal=function(accountId,displayName,channelId){
    var modal=document.getElementById('bufferModal');
    if(!modal)return false;
    document.getElementById('bufferAccountId').value=accountId||'';
    document.getElementById('bufferDisplayName').value=displayName||'';
    document.getElementById('bufferChannelId').value=channelId||'';
    var apiKeyInput=document.getElementById('bufferApiKey');
    if(apiKeyInput){
      apiKeyInput.value='';
      // Ajout : clé obligatoire. Édition : vide = conserver la clé chiffrée existante.
      apiKeyInput.required=!accountId;
      apiKeyInput.placeholder=accountId
        ? 'Laisser vide pour conserver la clé enregistrée'
        : 'Clé créée dans Buffer > Settings > API';
    }
    document.getElementById('bufferFormStatus').textContent='';
    modal.classList.add('isOpen');
    return false;
  };
  window.openBufferModalFromButton=function(btn){
    return window.openBufferModal(btn.getAttribute('data-id'),
      btn.getAttribute('data-name'), btn.getAttribute('data-channel'));
  };
  window.closeBufferModal=function(){
    var m=document.getElementById('bufferModal');
    if(m)m.classList.remove('isOpen');
    return false;
  };
  window.saveBufferAccount=async function(event){
    event.preventDefault();
    var status=document.getElementById('bufferFormStatus');
    var btn=document.getElementById('bufferSaveBtn');
    var payload={
      account_id:document.getElementById('bufferAccountId').value||'',
      display_name:document.getElementById('bufferDisplayName').value||'',
      api_key:document.getElementById('bufferApiKey').value||'',
      channel_id:document.getElementById('bufferChannelId').value||''
    };
    btn.disabled=true; status.className='bufferStatus'; status.textContent='Test de la clé Buffer…';
    try{
      var r=await fetch(WEBHOOK_BASE+'/networks/buffer/save',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false) throw new Error(d.message||('HTTP '+r.status));
      status.className='bufferStatus success'; status.textContent='Enregistré.';
      setTimeout(function(){location.reload();},600);
    }catch(e){
      status.className='bufferStatus error'; status.textContent=e.message||'Enregistrement impossible.';
      btn.disabled=false;
    }
    return false;
  };


  /* BUFFER_QUOTA_N8N_V90_PARITY */
  var QUOTA_CACHE_TTL=2*60*1000;
  var quotaQueue=[];
  var quotaRequestsActive=0;
  var QUOTA_MAX_CONCURRENCY=3;

  function quotaCacheKey(id){return 'pgNetworkQuota:v90-buffer:'+String(id||'');}
  function readQuotaCache(id){
    try{
      var raw=localStorage.getItem(quotaCacheKey(id));
      if(!raw)return null;
      var value=JSON.parse(raw);
      if(!value||Date.now()-Number(value.cached_at||0)>QUOTA_CACHE_TTL)return null;
      return value.payload||null;
    }catch(e){return null;}
  }
  function writeQuotaCache(id,payload){
    try{localStorage.setItem(quotaCacheKey(id),JSON.stringify({cached_at:Date.now(),payload:payload}));}catch(e){}
  }
  function clearQuotaCache(id){try{localStorage.removeItem(quotaCacheKey(id));}catch(e){}}

  function renderBufferQueue(cell,payload){
    var queue=cell.querySelector('.quotaQueue');
    if(!queue)return;
    if(cell.dataset.active!=='1'){
      queue.textContent='File d’attente indisponible';
      return;
    }
    var q=payload&&payload.queue&&typeof payload.queue==='object'?payload.queue:null;
    if(!q||q.available!==true){
      queue.textContent='File d’attente : '+String(q&&q.message||'contrôle indisponible');
      return;
    }
    var total=Number(q.total);
    var scheduled=Number(q.scheduled);
    var remaining=Number(q.remaining);
    var exact=q.exact!==false;
    if(!Number.isFinite(total)||total<0){
      queue.textContent='File d’attente : limite non chiffrée';
      return;
    }
    if(!exact){
      queue.textContent='File d’attente : au moins '+String(Math.max(0,Number.isFinite(scheduled)?scheduled:0))+' programmée(s) sur '+String(total);
    }else{
      var safeScheduled=Math.max(0,Number.isFinite(scheduled)?scheduled:0);
      var safeRemaining=Math.max(0,Number.isFinite(remaining)?remaining:(total-safeScheduled));
      queue.textContent='File d’attente : '+String(safeRemaining)+' / '+String(total)+' place(s) restante(s) · '+String(safeScheduled)+' programmée(s)';
    }
    if(q.is_at_limit===true||(exact&&Number.isFinite(remaining)&&remaining<=0))cell.classList.add('isDanger');
    else if(exact&&total>0&&Number.isFinite(remaining)&&remaining/total<=0.2)cell.classList.add('isWarning');
  }

  function renderQuotaCell(cell,payload){
    if(!cell)return;
    var provider=String(cell.dataset.provider||'').trim().toLowerCase();
    if(provider!=='buffer')return;
    var value=cell.querySelector('.quotaValue');
    var detail=cell.querySelector('.quotaDetail');
    var refresh=cell.querySelector('.quotaRefresh');
    cell.classList.remove('isLoading','isWarning','isDanger','isUnavailable','isDisabled');
    if(refresh)refresh.disabled=false;
    if(cell.dataset.active!=='1'){
      cell.classList.add('isDisabled');
      if(value)value.textContent='Désactivé';
      if(detail)detail.textContent='Connexion inactive';
      renderBufferQueue(cell,payload);
      return;
    }
    if(!payload||payload.available!==true){
      cell.classList.add('isUnavailable');
      if(value)value.textContent='Non disponible';
      if(detail)detail.textContent=String(payload&&payload.message||'Compteur indisponible');
      renderBufferQueue(cell,payload);
      cell.title=String(payload&&payload.message||'Compteur indisponible');
      return;
    }
    var total=payload.total===null||payload.total===undefined?null:Number(payload.total);
    var remaining=payload.remaining===null||payload.remaining===undefined?null:Number(payload.remaining);
    if(payload.unlimited===true||total===null||!Number.isFinite(total)){
      if(value)value.textContent='Illimité';
      if(detail)detail.textContent='Aucune limite quotidienne chiffrée signalée par Buffer';
      renderBufferQueue(cell,payload);
      cell.title=String(payload.message||'');
      return;
    }
    var safeRemaining=Number.isFinite(remaining)?Math.max(0,remaining):0;
    if(value)value.textContent=String(safeRemaining)+' / '+String(Math.max(0,total));
    var used=payload.used!==null&&payload.used!==undefined&&Number.isFinite(Number(payload.used))?' · '+Number(payload.used)+' utilisée(s)':'';
    if(detail)detail.textContent='restantes sur une période de 24 h'+used;
    if(safeRemaining<=0)cell.classList.add('isDanger');
    else if(total>0&&safeRemaining/total<=0.2)cell.classList.add('isWarning');
    renderBufferQueue(cell,payload);
    var queueMessage=payload.queue&&payload.queue.message?' · '+String(payload.queue.message):'';
    cell.title=String(payload.message||'')+queueMessage;
  }

  async function fetchQuota(id,force){
    var row=document.getElementById('network-'+String(id));
    var cell=row?row.querySelector('[data-quota-account-id]'):null;
    if(!cell||String(cell.dataset.provider||'').toLowerCase()!=='buffer')return;
    if(cell.dataset.active!=='1'){renderQuotaCell(cell,null);return;}
    if(!force){
      var cached=readQuotaCache(id);
      if(cached){renderQuotaCell(cell,cached);return;}
    }
    var refresh=cell.querySelector('.quotaRefresh');
    cell.classList.remove('isUnavailable','isWarning','isDanger');
    cell.classList.add('isLoading');
    if(refresh)refresh.disabled=true;
    var value=cell.querySelector('.quotaValue');if(value)value.textContent='Calcul…';
    var detail=cell.querySelector('.quotaDetail');if(detail)detail.textContent='Lecture du quota en cours';
    var queue=cell.querySelector('.quotaQueue');if(queue)queue.textContent='File d’attente : calcul…';
    try{
      var u=new URL(WEBHOOK_BASE+'/networks/quota',location.origin);
      u.searchParams.set('account_id',String(id));
      var r=await fetch(u,{headers:{'Accept':'application/json'},cache:'no-store',credentials:'same-origin'});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok)throw new Error(d.message||('HTTP '+r.status));
      writeQuotaCache(id,d);
      renderQuotaCell(cell,d);
    }catch(e){
      renderQuotaCell(cell,{available:false,provider:'buffer',message:'Lecture impossible : '+String(e&&e.message||e)});
    }
  }
  function pumpQuotaQueue(){
    while(quotaRequestsActive<QUOTA_MAX_CONCURRENCY&&quotaQueue.length){
      var task=quotaQueue.shift();
      quotaRequestsActive++;
      fetchQuota(task.id,task.force).finally(function(){quotaRequestsActive--;pumpQuotaQueue();});
    }
  }
  function queueQuota(id,force){
    id=String(id||'');if(!id)return;
    var row=document.getElementById('network-'+id);
    var cell=row?row.querySelector('[data-quota-account-id]'):null;
    if(!cell||String(cell.dataset.provider||'').toLowerCase()!=='buffer')return;
    if(cell.dataset.active!=='1'){renderQuotaCell(cell,null);return;}
    if(!force&&quotaQueue.some(function(task){return task.id===id;}))return;
    quotaQueue.push({id:id,force:Boolean(force)});pumpQuotaQueue();
  }
  function queueVisibleBufferQuotas(force){
    document.querySelectorAll('[data-quota-account-id][data-provider="buffer"]').forEach(function(cell){
      queueQuota(cell.dataset.quotaAccountId,force);
    });
  }

  document.addEventListener('click',function(event){
    var btn=event.target.closest&&event.target.closest('[data-network-action="quota-refresh"]');
    if(!btn)return;
    event.preventDefault();event.stopPropagation();
    var id=String(btn.getAttribute('data-id')||'');
    clearQuotaCache(id);queueQuota(id,true);
  });


  function initNetworkInfiniteScroll(){
    var tbody=document.getElementById('networkRows');
    var sentinel=document.getElementById('networkSentinel');
    var loader=document.getElementById('networkLoader');
    var paging=window.__networkPaging||{};
    if(!tbody||!sentinel)return;
    var hasMore=Boolean(paging.has_more);
    var cursorAt=String(paging.cursor_at||'');
    var cursorId=String(paging.cursor_id||'');
    var loading=false;
    if(loader)loader.style.display=hasMore?'block':'none';
    async function loadMore(){
      if(loading||!hasMore)return;loading=true;
      if(loader){loader.style.display='block';loader.textContent='Chargement…';}
      try{
        var url=new URL(WEBHOOK_BASE+'/networks/list-page',location.origin);
        url.searchParams.set('limit','20');
        if(cursorAt)url.searchParams.set('cursor_at',cursorAt);
        if(cursorId)url.searchParams.set('cursor_id',cursorId);
        var r=await fetch(url,{credentials:'same-origin'});var d=await r.json();
        if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
        var empty=document.getElementById('emptyNetworks');if(empty)empty.remove();
        if(d.rows_html){tbody.insertAdjacentHTML('beforeend',d.rows_html);queueVisibleBufferQuotas(false);}
        hasMore=Boolean(d.has_more);cursorAt=String(d.next_cursor_at||'');cursorId=String(d.next_cursor_id||'');
        if(loader){loader.style.display=hasMore?'block':'none';loader.textContent=hasMore?'Fais défiler pour charger plus de comptes.':'Toutes les lignes sont affichées.';}
      }catch(e){if(loader){loader.style.display='block';loader.textContent='Chargement impossible. Réessaie en faisant défiler.';}}
      finally{loading=false;}
    }
    new IntersectionObserver(function(entries){entries.forEach(function(entry){if(entry.isIntersecting)loadMore();});},{rootMargin:'240px'}).observe(sentinel);
  }
  function initNetworksPage(){queueVisibleBufferQuotas(false);initNetworkInfiniteScroll();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initNetworksPage);else initNetworksPage();

})();
