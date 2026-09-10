/**
 * Sélection groupée + modale d'erreur de la page "Posts publiés".
 * Port VERBATIM du script publishedBulkDeleteScript du workflow original
 * (seule adaptation : ${WEBHOOK_BASE} -> /app).
 */
(function(){
  if(window.__publishedBulkDeleteInstalled)return;
  window.__publishedBulkDeleteInstalled=true;

  var tableBody=document.getElementById('publishedTableBody');
  var selectAll=document.getElementById('publishedSelectAll');
  var toolbar=document.getElementById('publishedBulkToolbar');
  var deleteButton=document.getElementById('publishedBulkDeleteBtn');
  var countElement=document.getElementById('publishedBulkCount');
  var labelElement=document.getElementById('publishedBulkLabel');
  var errorModal=document.getElementById('publishedErrorModal');
  var errorModalTitle=document.getElementById('publishedErrorModalTitle');
  var errorModalMeta=document.getElementById('publishedErrorModalMeta');
  var errorModalMessage=document.getElementById('publishedErrorModalMessage');
  var selected=new Set();
  var uuidPattern=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  if(!tableBody||!selectAll||!toolbar||!deleteButton||!countElement||!labelElement||
     !errorModal||!errorModalTitle||!errorModalMeta||!errorModalMessage)return;

  var lastErrorTrigger=null;

  function openPublishedErrorModal(button){
    if(!button)return;
    lastErrorTrigger=button;
    var title=String(button.getAttribute('data-error-title')||'Publication').trim();
    var status=String(button.getAttribute('data-error-status')||'Erreur').trim();
    var publicationId=String(button.getAttribute('data-publication-id')||'').trim();
    var message=String(button.getAttribute('data-error-message')||'Aucun détail supplémentaire disponible.').trim();
    errorModalTitle.textContent=title||'Détail de l\u2019erreur';
    errorModalMeta.textContent=[status,publicationId].filter(Boolean).join(' · ');
    errorModalMessage.textContent=message||'Aucun détail supplémentaire disponible.';
    errorModal.classList.add('isOpen');
    errorModal.setAttribute('aria-hidden','false');
    document.body.classList.add('publishedErrorModalOpen');
    var closeButton=errorModal.querySelector('[data-close-published-error]');
    if(closeButton)setTimeout(function(){closeButton.focus();},0);
  }

  function closePublishedErrorModal(){
    errorModal.classList.remove('isOpen');
    errorModal.setAttribute('aria-hidden','true');
    document.body.classList.remove('publishedErrorModalOpen');
    if(lastErrorTrigger&&typeof lastErrorTrigger.focus==='function')lastErrorTrigger.focus();
    lastErrorTrigger=null;
  }

  function rowCheckboxes(){
    return Array.prototype.slice.call(tableBody.querySelectorAll('.publishedRowCheck'));
  }

  function syncSelectionUi(){
    var checks=rowCheckboxes();
    checks.forEach(function(check){
      var id=String(check.value||'').trim();
      var checked=selected.has(id);
      check.checked=checked;
      var row=check.closest('tr');
      if(row)row.classList.toggle('isBulkSelected',checked);
    });
    var selectedCount=selected.size;
    toolbar.hidden=selectedCount===0;
    toolbar.setAttribute('aria-hidden',selectedCount===0?'true':'false');
    countElement.textContent=String(selectedCount);
    labelElement.textContent=selectedCount>1?'lignes sélectionnées':'ligne sélectionnée';
    deleteButton.disabled=selectedCount===0;
    var selectedLoaded=checks.filter(function(check){
      return selected.has(String(check.value||'').trim());
    }).length;
    selectAll.checked=checks.length>0&&selectedLoaded===checks.length;
    selectAll.indeterminate=selectedLoaded>0&&selectedLoaded<checks.length;
  }

  function handleRowSelection(event){
    var target=event&&event.target?event.target:null;
    var check=target&&target.matches&&target.matches('.publishedRowCheck')
      ? target : (target&&target.closest?target.closest('.publishedRowCheck'):null);
    if(!check)return;
    var id=String(check.value||'').trim();
    if(!uuidPattern.test(id)){ check.checked=false; selected.delete(id); syncSelectionUi(); return; }
    if(check.checked)selected.add(id); else selected.delete(id);
    syncSelectionUi();
  }

  tableBody.addEventListener('change',handleRowSelection);
  tableBody.addEventListener('click',function(event){
    var target=event&&event.target?event.target:null;
    if(target&&target.matches&&target.matches('.publishedRowCheck')){
      setTimeout(function(){handleRowSelection({target:target});},0); return;
    }
    var detailsButton=target&&target.closest?target.closest('.publishedErrorDetailsBtn'):null;
    if(detailsButton){ event.preventDefault(); openPublishedErrorModal(detailsButton); }
  });

  errorModal.addEventListener('click',function(event){
    var closeTrigger=event.target&&event.target.closest?event.target.closest('[data-close-published-error]'):null;
    if(closeTrigger||event.target===errorModal){ event.preventDefault(); closePublishedErrorModal(); }
  });

  document.addEventListener('keydown',function(event){
    if(event.key==='Escape'&&errorModal.classList.contains('isOpen')){
      event.preventDefault(); closePublishedErrorModal();
    }
  });

  selectAll.addEventListener('change',function(){
    var shouldSelect=selectAll.checked;
    rowCheckboxes().forEach(function(check){
      var id=String(check.value||'').trim();
      if(!uuidPattern.test(id))return;
      if(shouldSelect)selected.add(id); else selected.delete(id);
    });
    syncSelectionUi();
  });

  deleteButton.addEventListener('click',async function(){
    var ids=Array.from(selected).filter(function(id){return uuidPattern.test(id);});
    if(!ids.length)return;
    var count=ids.length;
    var confirmed=await window.pgConfirm(window.t('js.pub.bulk_delete',{count:count}),{danger:true,confirmText:window.t('js.delete')});
    if(!confirmed)return;
    var previousLabel=deleteButton.textContent;
    deleteButton.disabled=true;
    deleteButton.textContent=window.t('js.deleting');
    try{
      var response=await fetch('/app/published/delete-bulk',{
        method:'POST',
        headers:{'Content-Type':'application/json','Accept':'application/json'},
        body:JSON.stringify({publication_ids:ids})
      });
      var text=await response.text();
      var payload={};
      try{payload=JSON.parse(text||'{}');}catch(error){}
      if(!response.ok||payload.success!==true){
        throw new Error(payload.message||payload.error||('HTTP '+response.status));
      }
      var deletedCount=Number((payload.data&&payload.data.deleted_count)||payload.deleted_count||0);
      if(deletedCount<1){ throw new Error(window.t('js.pub.none_deleted')); }
      window.pgToast(window.t('js.pub.deleted',{count:deletedCount}),'success');
      window.location.reload();
    }catch(error){
      deleteButton.disabled=false;
      deleteButton.textContent=previousLabel;
      window.pgToast(error.message||window.t('js.delete_failed'),'error');
    }
  });

  try{
    new MutationObserver(function(){ syncSelectionUi(); })
      .observe(tableBody,{childList:true,subtree:false});
  }catch(error){}

  syncSelectionUi();
})();
