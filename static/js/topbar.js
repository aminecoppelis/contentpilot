/**
 * Topbar partagée — port VERBATIM du script `const script` de
 * authDropdownHtml() (présent à l'identique dans toutes les pages du
 * workflow original) : bascule de workspace, modale de création de
 * workspace, recherche dans la liste, et navigation mobile.
 *
 * Seule adaptation : le préfixe de routes `${WEBHOOK_BASE}` (/webhook/V0)
 * est remplacé par /app, préfixe équivalent du portage Python.
 */
(function(){
if(window.__pgWorkspaceSwitchInstalled)return;window.__pgWorkspaceSwitchInstalled=true;

function pgSetMobileNav(open){
  var nav=document.querySelector('.pgMainNav');
  var toggle=document.querySelector('.pgMobileNavToggle');
  if(!nav||!toggle)return;
  var shouldOpen=Boolean(open);
  nav.classList.toggle('isOpen',shouldOpen);
  toggle.classList.toggle('isOpen',shouldOpen);
  toggle.setAttribute('aria-expanded',shouldOpen?'true':'false');
  toggle.setAttribute('aria-label',shouldOpen?window.t('js.close_menu'):window.t('js.open_menu'));
  if(!shouldOpen){
    nav.querySelectorAll('details[open]').forEach(function(details){details.removeAttribute('open');});
  }
}
document.addEventListener('click',function(event){
  var toggle=event.target&&event.target.closest?event.target.closest('.pgMobileNavToggle'):null;
  if(toggle){
    event.preventDefault();
    var nav=document.querySelector('.pgMainNav');
    pgSetMobileNav(!(nav&&nav.classList.contains('isOpen')));
    return;
  }
  if(window.matchMedia&&window.matchMedia('(max-width:900px)').matches){
    var link=event.target&&event.target.closest?event.target.closest('.pgMainNav>.nav'):null;
    if(link)pgSetMobileNav(false);
  }
});
document.addEventListener('keydown',function(event){if(event.key==='Escape')pgSetMobileNav(false);});
window.addEventListener('resize',function(){if(window.innerWidth>900)pgSetMobileNav(false);});

window.pgSwitchWorkspace=async function(workspaceId,trigger){
  if(!workspaceId)return;
  var buttons=Array.prototype.slice.call(document.querySelectorAll('.pgWorkspaceItem[data-workspace-id]'));
  var menu=trigger&&trigger.closest?trigger.closest('details.pgWorkspaceMenu'):null;
  buttons.forEach(function(button){button.disabled=true;});
  if(trigger){trigger.classList.add('isLoading');trigger.setAttribute('aria-busy','true');}
  try{
    var r=await fetch('/app/workspace/switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace_id:workspaceId})});
    var d=await r.json();
    if(!r.ok||!d.success)throw new Error(d.message||'Changement impossible');
    window.pgToast(window.t('js.tb.switching'),'info');
    location.reload();
  }catch(e){
    buttons.forEach(function(button){button.disabled=button.getAttribute('aria-checked')==='true';});
    if(trigger){trigger.classList.remove('isLoading');trigger.removeAttribute('aria-busy');}
    if(menu)menu.open=true;
    window.pgToast(e.message||window.t('js.tb.switch_failed'),'error');
  }
};
var pgWorkspaceCreateTrigger=null;
function pgEnsureWorkspaceCreateModal(){
  var existing=document.getElementById('pgWorkspaceCreateModal');
  if(existing)return existing;
  var overlay=document.createElement('div');
  overlay.id='pgWorkspaceCreateModal';
  overlay.className='pgWorkspaceCreateOverlay';
  overlay.setAttribute('aria-hidden','true');
  overlay.innerHTML=''
    +'<div class="pgWorkspaceCreateDialog" role="dialog" aria-modal="true" aria-labelledby="pgWorkspaceCreateTitle">'
      +'<div class="pgWorkspaceCreateHeader">'
        +'<div><h3 id="pgWorkspaceCreateTitle">'+window.t('js.tb.create_title')+'</h3><p>'+window.t('js.tb.create_desc')+'</p></div>'
        +'<button type="button" class="pgWorkspaceCreateClose" aria-label="'+window.t('js.close')+'">×</button>'
      +'</div>'
      +'<form id="pgWorkspaceCreateForm">'
        +'<label class="pgWorkspaceCreateField"><span>'+window.t('js.tb.name_label')+'</span><input id="pgWorkspaceCreateName" name="name" type="text" maxlength="120" autocomplete="organization" placeholder="'+window.t('js.tb.name_ph')+'" required></label>'
        +'<div class="pgWorkspaceCreateStatus" id="pgWorkspaceCreateStatus" role="status" aria-live="polite"></div>'
        +'<div class="pgWorkspaceCreateActions">'
          +'<button type="button" class="pgWorkspaceCreateCancel">'+window.t('js.cancel')+'</button>'
          +'<button type="submit" class="pgWorkspaceCreateSubmit">'+window.t('js.tb.create_btn')+'</button>'
        +'</div>'
      +'</form>'
    +'</div>';
  document.body.appendChild(overlay);

  function closeFromModal(){
    window.pgCloseWorkspaceCreateModal();
  }
  var closeButton=overlay.querySelector('.pgWorkspaceCreateClose');
  var cancelButton=overlay.querySelector('.pgWorkspaceCreateCancel');
  var form=overlay.querySelector('#pgWorkspaceCreateForm');
  if(closeButton)closeButton.addEventListener('click',closeFromModal);
  if(cancelButton)cancelButton.addEventListener('click',closeFromModal);
  overlay.addEventListener('click',function(event){
    if(event.target===overlay)closeFromModal();
  });
  if(form)form.addEventListener('submit',function(event){
    event.preventDefault();
    window.pgCreateWorkspaceFromDropdown();
  });
  return overlay;
}
window.pgOpenWorkspaceCreateModal=function(trigger){
  pgWorkspaceCreateTrigger=trigger||null;
  var modal=pgEnsureWorkspaceCreateModal();
  var input=modal.querySelector('#pgWorkspaceCreateName');
  var status=modal.querySelector('#pgWorkspaceCreateStatus');
  if(status){status.textContent='';status.classList.remove('isError');}
  if(input)input.value='';
  modal.classList.add('isOpen');
  modal.setAttribute('aria-hidden','false');
  document.body.style.overflow='hidden';
  document.querySelectorAll('details.pgWorkspaceMenu[open]').forEach(function(menu){menu.removeAttribute('open');});
  setTimeout(function(){if(input)input.focus();},0);
};
window.pgCloseWorkspaceCreateModal=function(){
  var modal=document.getElementById('pgWorkspaceCreateModal');
  if(!modal)return;
  modal.classList.remove('isOpen');
  modal.setAttribute('aria-hidden','true');
  document.body.style.overflow='';
  var trigger=pgWorkspaceCreateTrigger;
  pgWorkspaceCreateTrigger=null;
  if(trigger&&typeof trigger.focus==='function')setTimeout(function(){trigger.focus();},0);
};
window.pgCreateWorkspaceFromDropdown=async function(){
  var modal=pgEnsureWorkspaceCreateModal();
  var input=modal.querySelector('#pgWorkspaceCreateName');
  var status=modal.querySelector('#pgWorkspaceCreateStatus');
  var submit=modal.querySelector('.pgWorkspaceCreateSubmit');
  var name=String(input&&input.value||'').replace(/\s+/g,' ').trim();
  if(!name){
    if(status){status.textContent=window.t('js.tb.name_required');status.classList.add('isError');}
    if(input)input.focus();
    return;
  }
  if(submit)submit.disabled=true;
  if(input)input.disabled=true;
  if(status){status.textContent=window.t('js.tb.creating');status.classList.remove('isError');}
  try{
    var body=new URLSearchParams();
    body.set('action','create');
    body.set('name',name);
    var response=await fetch('/app/workspace/action',{
      method:'POST',
      headers:{
        'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8',
        'Accept':'text/html,application/xhtml+xml,application/json'
      },
      body:body,
      credentials:'same-origin'
    });
    var finalUrl=null;
    try{finalUrl=new URL(response.url||window.location.href,window.location.href);}catch(error){}
    var errorMessage=finalUrl?String(finalUrl.searchParams.get('error')||'').trim():'';
    var successMessage=finalUrl?String(finalUrl.searchParams.get('success')||'').trim():'';
    if(!response.ok||errorMessage){
      throw new Error(errorMessage||('HTTP '+response.status));
    }
    if(status)status.textContent=successMessage||window.t('js.tb.created_activating');
    window.pgToast(successMessage||window.t('js.tb.created'),'success');
    window.setTimeout(function(){window.location.reload();},250);
  }catch(error){
    if(status){
      status.textContent=error&&error.message?error.message:window.t('js.tb.create_failed');
      status.classList.add('isError');
    }
    if(submit)submit.disabled=false;
    if(input){input.disabled=false;input.focus();}
  }
};
document.addEventListener('keydown',function(event){
  if(event.key!=='Escape')return;
  var modal=document.getElementById('pgWorkspaceCreateModal');
  if(modal&&modal.classList.contains('isOpen')){
    event.preventDefault();
    window.pgCloseWorkspaceCreateModal();
  }
});
function pgNormalizeWorkspaceSearch(value){
  var text=String(value||'').toLowerCase().trim();
  try{text=text.normalize('NFD').replace(/[\u0300-\u036f]/g,'');}catch(e){}
  return text.replace(/\s+/g,' ');
}
function pgFilterWorkspaceMenu(menu){
  if(!menu)return;
  var input=menu.querySelector('.pgWorkspaceSearch');
  var list=menu.querySelector('.pgWorkspaceList');
  var empty=menu.querySelector('.pgWorkspaceEmpty');
  if(!input||!list)return;
  var query=pgNormalizeWorkspaceSearch(input.value);
  var visibleCount=0;
  Array.prototype.forEach.call(list.children,function(item){
    var label=item.querySelector('.pgWorkspaceItemText b');
    var searchable=pgNormalizeWorkspaceSearch(label?label.textContent:item.textContent);
    var visible=!query||searchable.indexOf(query)!==-1;
    item.hidden=!visible;
    if(visible)visibleCount++;
  });
  if(empty)empty.classList.toggle('isVisible',visibleCount===0);
}
document.querySelectorAll('details.pgWorkspaceMenu').forEach(function(menu){
  var input=menu.querySelector('.pgWorkspaceSearch');
  if(!input)return;
  input.addEventListener('input',function(){pgFilterWorkspaceMenu(menu);});
  input.addEventListener('keydown',function(event){
    if(event.key==='Enter'){
      var firstVisible=Array.prototype.find.call(menu.querySelectorAll('.pgWorkspaceItem[data-workspace-id]'),function(item){return !item.hidden&&!item.disabled;});
      if(firstVisible){event.preventDefault();firstVisible.click();}
    }
  });
  menu.addEventListener('toggle',function(){
    if(menu.open){setTimeout(function(){input.focus();input.select();pgFilterWorkspaceMenu(menu);},0);}
    else{input.value='';pgFilterWorkspaceMenu(menu);}
  });
});
document.addEventListener('click',function(event){
  var addWorkspaceButton=event.target&&event.target.closest?event.target.closest('.pgWorkspaceAddButton'):null;
  if(addWorkspaceButton){
    event.preventDefault();
    event.stopPropagation();
    window.pgOpenWorkspaceCreateModal(addWorkspaceButton);
    return;
  }
  var workspaceButton=event.target&&event.target.closest?event.target.closest('.pgWorkspaceItem[data-workspace-id]'):null;
  if(workspaceButton&&!workspaceButton.disabled){event.preventDefault();window.pgSwitchWorkspace(workspaceButton.getAttribute('data-workspace-id'),workspaceButton);return;}
  document.querySelectorAll('details.userMenu[open],details.pgWorkspaceMenu[open]').forEach(function(menu){if(!menu.contains(event.target))menu.removeAttribute('open');});
});
document.addEventListener('keydown',function(event){if(event.key==='Escape'){document.querySelectorAll('details.userMenu[open],details.pgWorkspaceMenu[open]').forEach(function(menu){menu.removeAttribute('open');});}});
})();