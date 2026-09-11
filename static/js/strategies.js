/**
 * Page "Stratégies" — port des interactions du workflow original :
 * activation conditionnelle du bouton de soumission (compte + durée +
 * instructions requis), génération d'instruction par IA, création de
 * stratégie, suppression, édition d'un créneau de calendrier.
 */
(function(){
  var WEBHOOK_BASE='/app';
  var form=document.getElementById('strategyForm');
  var submitBtn=document.getElementById('submitStrategyBtn');
  var aiBtn=document.getElementById('generateInstructionsBtn');
  var loader=document.getElementById('loader');
  var modal=document.getElementById('strategyModal');

  function toast(msg,type){
    window.pgToast(msg,type||'success');
  }
  function closeModal(){
    if(!modal)return;
    modal.classList.remove('isOpen');
    modal.setAttribute('aria-hidden','true');
    document.body.classList.remove('modalOpen');
  }
  var cancelBtn=document.getElementById('cancelFormBtn');
  if(cancelBtn)cancelBtn.addEventListener('click',closeModal);
  if(modal)modal.addEventListener('click',function(e){ if(e.target===modal)closeModal(); });

  /* Le bouton "Analyser" ne s'active que si compte + durée + instructions sont remplis
     (STRATEGY_ACCOUNT_DURATION_REQUIRED_UI). "Générer avec l'IA" ne dépend que du compte. */
  function syncFormState(){
    if(!form)return;
    var account=String(form.social_account_id&&form.social_account_id.value||'').trim();
    var duration=String(form.duration_days&&form.duration_days.value||'').trim();
    var instructions=String(form.instructions&&form.instructions.value||'').trim();
    if(submitBtn) submitBtn.disabled=!(account&&duration&&instructions);
    if(aiBtn) aiBtn.disabled=!account;
  }
  if(form){
    form.addEventListener('input',syncFormState);
    form.addEventListener('change',syncFormState);
    syncFormState();
  }

  if(aiBtn)aiBtn.addEventListener('click',async function(){
    if(!form)return;
    var previous=aiBtn.textContent;
    aiBtn.disabled=true; aiBtn.textContent=window.t('js.generating');
    try{
      var r=await fetch(WEBHOOK_BASE+'/strategies/instructions/generate',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          social_account_id:form.social_account_id.value,
          duration_days:Number(form.duration_days.value||0)||null,
          language:form.language.value
        })});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      var text=(d.data&&d.data.instructions)||d.instructions||'';
      if(text){ form.instructions.value=text; syncFormState(); }
      else toast(window.t('js.strat.no_instructions'),'error');
    }catch(e){ toast(e.message||window.t('js.strat.gen_failed'),'error'); }
    finally{ aiBtn.textContent=previous; syncFormState(); }
  });

  if(form)form.addEventListener('submit',async function(event){
    event.preventDefault();
    if(submitBtn&&submitBtn.disabled)return;
    var previous=submitBtn?submitBtn.textContent:'';
    if(submitBtn){ submitBtn.disabled=true; submitBtn.textContent=window.t('js.strat.analyzing'); }
    if(loader)loader.classList.add('show');
    try{
      var payload={
        social_account_id:form.social_account_id.value,
        objective_type:form.objective_type.value,
        duration_days:Number(form.duration_days.value||30),
        language:form.language.value,
        instructions:form.instructions.value,
        research_depth:form.research_depth.value,
        country:form.country.value
      };
      var r=await fetch(WEBHOOK_BASE+'/strategies/analyze',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      var strategyId=(d.data&&d.data.strategy_id)||d.strategy_id||'';
      window.pgToast(window.t('js.strat.created'),'success');
      window.location.href=WEBHOOK_BASE+'/strategies'+(strategyId?('?strategy_id='+encodeURIComponent(strategyId)):'');
    }catch(e){
      toast('Analyse impossible : '+e.message,'error');
      if(submitBtn){ submitBtn.disabled=false; submitBtn.textContent=previous; }
      if(loader)loader.classList.remove('show');
    }
  });

  /* Suppression depuis la liste */
  document.addEventListener('click',async function(event){
    var btn=event.target&&event.target.closest?event.target.closest('.strategyListDeleteBtn'):null;
    if(!btn)return;
    event.preventDefault();
    var id=btn.getAttribute('data-strategy-id');
    var title=btn.getAttribute('data-strategy-title')||window.t('js.strat.this_one');
    if(!(await window.pgConfirm(window.t('js.strat.confirm_delete',{title:title}),{danger:true,confirmText:window.t('js.delete')})))return;
    btn.disabled=true;
    try{
      var r=await fetch(WEBHOOK_BASE+'/strategies/action',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({strategy_id:id,action:'delete'})});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      var row=btn.closest('tr'); if(row)row.remove();
      toast(window.t('js.strat.deleted'));
    }catch(e){ toast(e.message||window.t('js.delete_failed'),'error'); btn.disabled=false; }
  });

  /* Modale d'édition d'un créneau de calendrier */
  var calendarModal=document.getElementById('calendarTaskModal');
  var currentCalendarId='';
  function userNowParts(){
    var parts=new Intl.DateTimeFormat('fr-FR',{timeZone:(window.pgUserTimezone?window.pgUserTimezone():(window.__PG_TIMEZONE||Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC')),year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date());
    var out={}; parts.forEach(function(p){if(p.type!=='literal')out[p.type]=p.value;});
    return {date:(out.year||'')+'-'+(out.month||'')+'-'+(out.day||''),time:(out.hour||'00')+':'+(out.minute||'00')};
  }
  function userPartsFromIso(isoDate){
    var d=isoDate?new Date(isoDate):new Date();
    if(Number.isNaN(d.getTime()))return userNowParts();
    var parts=new Intl.DateTimeFormat('fr-FR',{timeZone:(window.pgUserTimezone?window.pgUserTimezone():(window.__PG_TIMEZONE||Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC')),year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(d);
    var out={}; parts.forEach(function(p){if(p.type!=='literal')out[p.type]=p.value;});
    return {date:(out.year||'')+'-'+(out.month||'')+'-'+(out.day||''),time:(out.hour||'00')+':'+(out.minute||'00')};
  }
  window.openCalendarTaskModal=function(calendarId,isoDate,plannedDay,plannedHour){
    currentCalendarId=String(calendarId||'');
    if(!calendarModal)return;
    var values=plannedDay?{date:String(plannedDay),time:String(plannedHour||'09:00').slice(0,5)}:userPartsFromIso(isoDate);
    var dateEl=document.getElementById('calendarTaskDate');
    var timeEl=document.getElementById('calendarTaskTime');
    var now=userNowParts();
    if(dateEl){dateEl.min=now.date;dateEl.value=values.date;}
    if(timeEl)timeEl.value=values.time||'09:00';
    calendarModal.classList.add('isOpen');
    calendarModal.setAttribute('aria-hidden','false');
  };
  function closeCalendarModal(){
    if(!calendarModal)return;
    calendarModal.classList.remove('isOpen');
    calendarModal.setAttribute('aria-hidden','true');
  }
  var calCancel=document.getElementById('calendarTaskCancelBtn');
  if(calCancel)calCancel.addEventListener('click',closeCalendarModal);
  if(calendarModal)calendarModal.addEventListener('click',function(event){if(event.target===calendarModal)closeCalendarModal();});
  var calSave=document.getElementById('calendarTaskSaveBtn');
  if(calSave)calSave.addEventListener('click',async function(){
    var dateEl=document.getElementById('calendarTaskDate');
    var timeEl=document.getElementById('calendarTaskTime');
    if(!dateEl||!timeEl||!dateEl.value||!timeEl.value){toast(window.t('js.strat.pick_datetime'),'error');return;}
    var now=userNowParts();
    var selectedKey=dateEl.value+'T'+timeEl.value;
    var nowKey=now.date+'T'+now.time;
    if(selectedKey<=nowKey){toast(window.t('js.strat.future_datetime'),'error');return;}
    var detailWorkspace=document.querySelector('.strategyWorkspace[data-strategy-id]');
    var detailStrategyId=detailWorkspace?String(detailWorkspace.getAttribute('data-strategy-id')||''):'';
    if(!detailStrategyId||!currentCalendarId){toast(window.t('js.strat.task_not_found'),'error');return;}
    calSave.disabled=true;
    try{
      // datetime-local n'a pas d'offset : le backend l'interprète dans le fuseau IANA de l'utilisateur.
      var plannedFor=dateEl.value+'T'+timeEl.value+':00';
      var payload={strategy_id:detailStrategyId,calendar_id:currentCalendarId,planned_for:plannedFor,timezone:(window.pgUserTimezone?window.pgUserTimezone():window.__PG_TIMEZONE||'UTC')};
      var r=await fetch(WEBHOOK_BASE+'/strategies/calendar/reschedule',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      // Compatibilité avec un backend intermédiaire qui ne posséderait pas encore
      // l'endpoint dédié, sans jamais utiliser une méthode non autorisée.
      if(r.status===404||r.status===405){
        r=await fetch(WEBHOOK_BASE+'/strategies/action',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(Object.assign({action:'reschedule'},payload))});
      }
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      toast(window.t('js.strat.slot_updated'));
      closeCalendarModal();
      setTimeout(function(){location.reload();},250);
    }catch(e){ toast('Modification impossible : '+e.message,'error'); }
    finally{ calSave.disabled=false; }
  });
})();

/* Détail stratégie : navigation interne et actions réellement supportées. */
(function(){
  var workspace=document.querySelector('.strategyWorkspace[data-strategy-id]');
  if(!workspace)return;
  var strategyId=String(workspace.getAttribute('data-strategy-id')||'').trim();
  function detailToast(msg,type){ window.pgToast(msg,type||'success'); }
  async function detailApi(payload){
    var r=await fetch('/app/strategies/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json().catch(function(){return {};});
    if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
    return d;
  }

  var tabButtons=Array.prototype.slice.call(document.querySelectorAll('[data-strategy-tab]'));
  var panels=Array.prototype.slice.call(document.querySelectorAll('[data-strategy-panel]'));
  function showTab(name){
    tabButtons.forEach(function(btn){
      var active=btn.getAttribute('data-strategy-tab')===name;
      btn.classList.toggle('active',active);
      btn.setAttribute('aria-selected',active?'true':'false');
    });
    panels.forEach(function(panel){
      var active=panel.getAttribute('data-strategy-panel')===name;
      panel.classList.toggle('active',active);
      panel.hidden=!active;
    });
    try{history.replaceState(null,'',window.location.pathname+window.location.search+'#'+name);}catch(e){}
  }
  tabButtons.forEach(function(btn){btn.addEventListener('click',function(){showTab(btn.getAttribute('data-strategy-tab'));});});
  var initialHash=String(window.location.hash||'').replace(/^#/,'');
  var hasCalendarQuery=false;
  try{hasCalendarQuery=new URL(window.location.href).searchParams.has('cal_view');}catch(e){}
  if(hasCalendarQuery)showTab('calendar');
  else if(['summary','actions','calendar'].indexOf(initialHash)!==-1)showTab(initialHash);

  document.querySelectorAll('.strategyStatusBtn[data-strategy-action],.strategyScheduleBtn[data-strategy-action]').forEach(function(btn){
    btn.addEventListener('click',async function(){
      var action=btn.getAttribute('data-strategy-action');
      if(action==='archive'&&!(await window.pgConfirm(window.t('js.strat.confirm_archive'))))return;
      btn.disabled=true;
      try{
        await detailApi({strategy_id:strategyId,action:action});
        detailToast(action==='archive'?window.t('js.strat.archived'):(action==='schedule'?window.t('js.strat.actions_planned'):window.t('js.strat.activated')));
        setTimeout(function(){window.location.reload();},300);
      }catch(e){detailToast(e.message||window.t('js.update_failed'),'error');btn.disabled=false;}
    });
  });

  async function schedulePostsFromActions(actionIds,trigger){
    actionIds=(actionIds||[]).filter(Boolean);
    if(!strategyId){detailToast(window.t('js.strat.not_found'),'error');return;}
    if(!actionIds.length){detailToast(window.t('js.strat.pick_action'),'error');return;}
    var controls=Array.prototype.slice.call(document.querySelectorAll('.actionBulkBox,.actionRun,#bulkLaunchActions,#selectAllActions,#toggleBulkMode'));
    if(trigger)controls.push(trigger);
    controls.forEach(function(el){if(el){el.disabled=true;el.classList.add('isSaving');}});
    try{
      var result=await detailApi({
        action:actionIds.length>1?'bulk_schedule_action_posts':'schedule_action_posts',
        strategy_id:strategyId,
        action_id:actionIds.length===1?actionIds[0]:'',
        action_ids:actionIds,
        auto_plan:true
      });
      detailToast((result&&result.message)||window.t('js.strat.gen_planned'),'success');
      setTimeout(function(){location.reload();},450);
    }catch(error){
      controls.forEach(function(el){if(el){el.disabled=false;el.classList.remove('isSaving');}});
      detailToast(error.message||window.t('js.strat.plan_failed'),'error');
    }
  }

  function isBulkMode(){
    var list=document.getElementById('actionsList');
    return Boolean(list&&list.classList.contains('bulkMode'));
  }
  function selectedBulkActionIds(){
    if(!isBulkMode())return [];
    return Array.prototype.slice.call(document.querySelectorAll('.actionBulkBox'))
      .filter(function(input){return input&&input.checked&&!input.disabled;})
      .map(function(input){return input.getAttribute('data-action-id')||'';})
      .filter(Boolean);
  }
  function refreshBulkToolbar(){
    var bulk=isBulkMode();
    var count=selectedBulkActionIds().length;
    var label=document.getElementById('bulkActionCount');
    var bulkBtn=document.getElementById('bulkLaunchActions');
    var selectBtn=document.getElementById('selectAllActions');
    var toggleBtn=document.getElementById('toggleBulkMode');
    if(label){label.textContent=bulk?window.t('js.strat.n_selected',{count:count}):'';label.style.display=bulk?'':'none';}
    if(bulkBtn)bulkBtn.disabled=!bulk||count===0;
    if(selectBtn)selectBtn.disabled=!bulk;
    if(toggleBtn)toggleBtn.textContent=bulk?window.t('js.strat.exit_selection'):window.t('js.strat.select_many');
  }
  function setBulkMode(enabled){
    var list=document.getElementById('actionsList');
    if(!list)return;
    list.classList.toggle('bulkMode',Boolean(enabled));
    if(!enabled){document.querySelectorAll('.actionBulkBox').forEach(function(box){box.checked=false;});}
    refreshBulkToolbar();
  }
  async function clearPendingCalendarTasks(trigger){
    var button=trigger||document.getElementById('clearPendingCalendarTasks');
    var clearableCount=Math.max(0,Number(button&&button.getAttribute('data-clearable-count')||0));
    if(!clearableCount){detailToast(window.t('js.strat.no_clearable'),'error');return;}
    if(!(await window.pgConfirm(window.t('js.strat.confirm_clear',{count:clearableCount}),{danger:true})))return;
    try{
      var result=await detailApi({action:'clear_pending_calendar_tasks',strategy_id:strategyId});
      detailToast((result&&result.message)||window.t('js.strat.cleared',{count:Number(result&&result.cleared_calendar_count||0)}),'success');
      setTimeout(function(){location.reload();},450);
    }catch(error){detailToast(error&&error.message?error.message:window.t('js.strat.clear_failed'),'error');}
  }

  document.addEventListener('change',function(event){
    if(event.target&&event.target.classList&&event.target.classList.contains('actionBulkBox'))refreshBulkToolbar();
  });
  document.addEventListener('click',function(event){
    var toggle=event.target&&event.target.closest?event.target.closest('#toggleBulkMode'):null;
    if(toggle){event.preventDefault();setBulkMode(!isBulkMode());return;}
    var selectAll=event.target&&event.target.closest?event.target.closest('#selectAllActions'):null;
    if(selectAll){
      event.preventDefault();if(!isBulkMode())return;
      var boxes=Array.prototype.slice.call(document.querySelectorAll('.actionBulkBox')).filter(function(box){return !box.disabled;});
      var shouldCheck=boxes.some(function(box){return !box.checked;});
      boxes.forEach(function(box){box.checked=shouldCheck;});refreshBulkToolbar();return;
    }
    var clearPending=event.target&&event.target.closest?event.target.closest('#clearPendingCalendarTasks'):null;
    if(clearPending){event.preventDefault();clearPendingCalendarTasks(clearPending);return;}
    var bulkLaunch=event.target&&event.target.closest?event.target.closest('#bulkLaunchActions'):null;
    if(bulkLaunch){event.preventDefault();schedulePostsFromActions(selectedBulkActionIds(),bulkLaunch);return;}
    var actionRun=event.target&&event.target.closest?event.target.closest('.actionRun'):null;
    if(actionRun){event.preventDefault();schedulePostsFromActions([actionRun.getAttribute('data-action-id')],actionRun);return;}
    var actionComplete=event.target&&event.target.closest?event.target.closest('.actionComplete'):null;
    if(actionComplete){
      event.preventDefault();
      var nextStatus=actionComplete.getAttribute('data-next-status')||'done';
      actionComplete.disabled=true;
      detailApi({action:'set_action_status',strategy_id:strategyId,action_id:actionComplete.getAttribute('data-action-id')||'',status:nextStatus})
        .then(function(result){detailToast((result&&result.message)||window.t('js.strat.action_updated'));setTimeout(function(){location.reload();},300);})
        .catch(function(error){actionComplete.disabled=false;detailToast(error.message||window.t('js.update_failed'),'error');});
      return;
    }
  });
  refreshBulkToolbar();

  var deleteBtn=document.querySelector('.strategyDetailDeleteBtn[data-strategy-id]');
  if(deleteBtn)deleteBtn.addEventListener('click',async function(){
    var title=deleteBtn.getAttribute('data-strategy-title')||window.t('js.strat.this_one');
    if(!(await window.pgConfirm(window.t('js.strat.confirm_delete',{title:title}),{danger:true,confirmText:window.t('js.delete')})))return;
    deleteBtn.disabled=true;
    try{
      await detailApi({strategy_id:strategyId,action:'delete'});
      window.pgToast(window.t('js.strat.deleted'),'success');
      window.location.href='/app/strategies';
    }catch(e){detailToast(e.message||window.t('js.delete_failed'),'error');deleteBtn.disabled=false;}
  });

  document.addEventListener('click',function(event){
    var btn=event.target&&event.target.closest?event.target.closest('.strategyCalendarEditBtn[data-calendar-id]'):null;
    if(!btn)return;
    event.preventDefault();
    if(typeof window.openCalendarTaskModal==='function'){
      window.openCalendarTaskModal(
        btn.getAttribute('data-calendar-id'),
        btn.getAttribute('data-planned-for'),
        btn.getAttribute('data-planned-day'),
        btn.getAttribute('data-planned-time')
      );
    }
  });
})();


/* Vue calendrier stratégie — parité de navigation avec le V90 :
   Mois / Semaine / Semaine travail / Jour / Planning. */
(function(){
  var panel=document.getElementById('strategyCalendarPanel');
  var body=document.getElementById('strategyCalendarBody');
  var dataNode=document.getElementById('strategyCalendarItemsJson');
  if(!panel||!body||!dataNode)return;
  var items=[];
  try{items=JSON.parse(dataNode.textContent||'[]');}catch(e){items=[];}
  if(!Array.isArray(items))items=[];

  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function pad(n){return String(n).padStart(2,'0');}
  function dayKey(d){return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());}
  function dateFromKey(k){var m=String(k||'').match(/^(\d{4})-(\d{2})-(\d{2})$/);return m?new Date(Number(m[1]),Number(m[2])-1,Number(m[3]),12,0,0,0):new Date();}
  function startOfDay(d){return new Date(d.getFullYear(),d.getMonth(),d.getDate(),12,0,0,0);}
  function addDays(d,n){var x=startOfDay(d);x.setDate(x.getDate()+Number(n||0));return x;}
  function addMonths(d,n){var x=new Date(d.getFullYear(),d.getMonth()+Number(n||0),1,12,0,0,0);return x;}
  function startOfWeek(d){var x=startOfDay(d);var delta=(x.getDay()+6)%7;return addDays(x,-delta);}
  function startOfMonth(d){return new Date(d.getFullYear(),d.getMonth(),1,12,0,0,0);}
  function sameDay(a,b){return dayKey(a)===dayKey(b);}
  function itemsForDay(d){var k=dayKey(d);return items.filter(function(i){return String(i.planned_day||'')===k;});}
  function itemsForRange(start,end){var a=dayKey(start),b=dayKey(end);return items.filter(function(i){var k=String(i.planned_day||'');return k>=a&&k<b;});}
  function calLocale(){return {fr:'fr-FR',en:'en-US',ar:'ar'}[window.__LOCALE]||'fr-FR';}
  function fmt(d,opts){return new Intl.DateTimeFormat(calLocale(),opts).format(d);}
  function fullDay(d){return fmt(d,{weekday:'long',day:'numeric',month:'long',year:'numeric'});}
  function monthTitle(d){return fmt(d,{month:'long',year:'numeric'});}
  function weekTitle(d,work){var start=startOfWeek(d),end=addDays(start,work?4:6);return fmt(start,{day:'numeric',month:'short'})+' – '+fmt(end,{day:'numeric',month:'short',year:'numeric'});}
  function statusDone(i){return ['generated','done','completed','published'].indexOf(String(i.status||'').toLowerCase())!==-1;}
  function statusLabel(i){var s=String(i&&i.status||'scheduled').toLowerCase();return {scheduled:window.t('js.cal.status.scheduled'),retry:window.t('js.cal.status.retry'),failed:window.t('js.status.failed'),processing:window.t('js.status.running'),generating:window.t('js.status.running'),pending_reschedule:window.t('js.cal.status.pending_reschedule'),generated:window.t('js.cal.status.generated'),done:window.t('js.status.completed'),completed:window.t('js.status.completed'),published:window.t('js.cal.status.published'),skipped:window.t('js.cal.status.skipped')}[s]||String(i&&i.status||'scheduled');}
  function isPast(i){if(statusDone(i))return false;var now=new Date();var d=i.planned_for?new Date(i.planned_for):null;return d&&!Number.isNaN(d.getTime())&&d<now;}
  function itemClass(i){return 'calendarEventDetail '+(i.kind==='checkpoint'?'checkpoint ':'action ')+(statusDone(i)?'generated ':'')+(isPast(i)?'overdue ':'')+esc(i.status||'scheduled');}
  function editButton(i){
    if(!i.editable)return '';
    var time=String(i.planned_time||'').slice(0,5)||pad(Number(i.planned_hour||9))+':00';
    return '<button type="button" class="btn secondary tiny strategyCalendarEditBtn" data-calendar-id="'+esc(i.id)+'" data-planned-for="'+esc(i.planned_for)+'" data-planned-day="'+esc(i.planned_day)+'" data-planned-time="'+esc(time)+'">'+window.t('js.edit')+'</button>';
  }
  function subjectButton(i){
    if(!i.active_request_exists||!i.request_id)return '';
    return '<a class="btn secondary tiny" href="/app/posts/view?request_id='+encodeURIComponent(String(i.request_id))+'">'+window.t('js.cal.view_subject')+'</a>';
  }
  function chip(i){var time=String(i.planned_time||'').slice(0,5)||pad(Number(i.planned_hour||0))+':00';return '<div class="calendarEventChip '+(statusDone(i)?'generated ':'')+(isPast(i)?'overdue ':'')+'" title="'+esc(i.title)+'"><b>'+esc(i.title)+'</b><small>'+esc(time)+'</small></div>';}
  function detail(i,compact){var time=String(i.planned_time||'').slice(0,5)||pad(Number(i.planned_hour||0))+':00';return '<article class="'+itemClass(i)+'" data-calendar-id="'+esc(i.id)+'">'
    +'<div class="calendarEventTop"><span class="calendarEventTime">'+esc(time)+'</span><span class="statusPill '+esc(i.status||'scheduled')+'">'+esc(statusLabel(i))+'</span></div>'
    +'<h3>'+esc(i.title||window.t('js.cal.planned_task'))+'</h3>'
    +(i.category?'<p class="calendarMetaLine"><small>'+window.t('js.cal.category')+'</small><span>'+esc(i.category)+'</span></p>':'')
    +(i.error_message?'<p class="strategyCalendarError">'+esc(i.error_message)+'</p>':'')
    +(isPast(i)&&i.editable?'<p class="calendarOverdueNote">'+window.t('js.cal.overdue_note')+'</p>':'')
    +(isPast(i)&&i.active_request_exists?'<p class="calendarOverdueNote">'+window.t('js.cal.overdue_exists')+'</p>':'')
    +(compact?'':('<p class="calendarMetaLine"><small>'+window.t('js.cal.date')+'</small><span>'+esc(i.planned_label||i.planned_day)+'</span></p>'))
    +'<div class="calendarEventActions">'+editButton(i)+subjectButton(i)+'</div>'
    +'</article>';}

  var url=new URL(window.location.href);
  var mode=String(url.searchParams.get('cal_view')||'month').toLowerCase();
  if(['month','week','workweek','day','schedule'].indexOf(mode)===-1)mode='month';
  var current=dateFromKey(url.searchParams.get('cal_date')||dayKey(new Date()));

  function setUrl(){
    try{
      var u=new URL(window.location.href);
      u.searchParams.set('cal_view',mode);u.searchParams.set('cal_date',dayKey(current));u.hash='calendar';
      history.replaceState(null,'',u.pathname+'?'+u.searchParams.toString()+u.hash);
    }catch(e){}
  }
  function toolbarTitle(){if(mode==='day')return fullDay(current);if(mode==='week')return weekTitle(current,false);if(mode==='workweek')return weekTitle(current,true);if(mode==='schedule')return window.t('js.cal.schedule');return monthTitle(current);}
  function monthView(){
    var start=startOfMonth(current);var gridStart=addDays(start,-((start.getDay()+6)%7));var today=startOfDay(new Date());var labels=[0,1,2,3,4,5,6].map(function(n){return fmt(addDays(startOfWeek(new Date()),n),{weekday:'short'});});var cells='';
    for(var i=0;i<42;i++){
      var day=addDays(gridStart,i),list=itemsForDay(day);
      cells+='<button type="button" class="calendarMonthCell '+(day.getMonth()!==current.getMonth()?'outside ':'')+(sameDay(day,today)?'today ':'')+'" data-calendar-day="'+dayKey(day)+'"><span class="calendarCellDate">'+day.getDate()+'</span><div class="calendarCellEvents">'+list.slice(0,3).map(chip).join('')+(list.length>3?'<em>+'+(list.length-3)+'</em>':'')+'</div></button>';
    }
    return '<div class="calendarMonthView"><div class="calendarWeekHeader">'+labels.map(function(l){return '<span>'+l+'</span>';}).join('')+'</div><div class="calendarMonthGrid">'+cells+'</div></div>';
  }
  function dayView(){var list=itemsForDay(current),rows='';for(var h=7;h<=21;h++){var hourItems=list.filter(function(i){return Number(i.planned_hour)===h;});rows+='<div class="calendarHourRow"><div class="calendarHourLabel">'+pad(h)+':00</div><div class="calendarHourEvents">'+(hourItems.length?hourItems.map(function(i){return detail(i,true);}).join(''):'<span class="calendarNoEvent">'+window.t('js.cal.no_item')+'</span>')+'</div></div>';}return '<div class="calendarDayView">'+rows+'</div>';}
  function weekView(work){
    var start=startOfWeek(current),days=[],len=work?5:7;for(var i=0;i<len;i++)days.push(addDays(start,i));
    var today=startOfDay(new Date());var header=days.map(function(d){var c=itemsForDay(d).length;return '<button type="button" class="calendarWeekDayHead '+(sameDay(d,today)?'today':'')+'" data-calendar-day="'+dayKey(d)+'"><b>'+esc(fmt(d,{weekday:'short'}))+'</b><span>'+pad(d.getDate())+'</span>'+(c?'<em>'+c+'</em>':'')+'</button>';}).join('');
    var rows='';for(var h=7;h<=21;h++){rows+='<div class="calendarWeekHourRow"><div class="calendarWeekHourLabel">'+pad(h)+':00</div><div class="calendarWeekHourCells">'+days.map(function(d){var hi=itemsForDay(d).filter(function(i){return Number(i.planned_hour)===h;});return '<button type="button" class="calendarWeekHourCell" data-calendar-day="'+dayKey(d)+'">'+hi.map(chip).join('')+'</button>';}).join('')+'</div></div>';}
    var rangeItems=itemsForRange(start,addDays(start,len));return '<div class="calendarWeekView '+(work?'workweek':'fullweek')+'"><div class="calendarWeekHeaderGrid"><div class="calendarWeekCorner"></div><div class="calendarWeekDaysGrid">'+header+'</div></div><div class="calendarWeekBody">'+rows+'</div>'+(rangeItems.length?'<div class="calendarWeekList"><h4>'+(work?window.t('js.cal.detail_workweek'):window.t('js.cal.detail_week'))+'</h4>'+rangeItems.map(function(i){return detail(i,false);}).join('')+'</div>':'')+'</div>';
  }
  function scheduleView(){if(!items.length)return '<div class="strategyEmptyState">'+window.t('js.cal.none_planned')+'</div>';var groups={};items.slice().sort(function(a,b){return String(a.planned_for).localeCompare(String(b.planned_for));}).forEach(function(i){var k=i.planned_day||'sans-date';(groups[k]=groups[k]||[]).push(i);});return '<div class="calendarScheduleView">'+Object.keys(groups).sort().map(function(k){return '<div class="calendarScheduleDay"><h4>'+esc(k==='sans-date'?window.t('js.cal.no_date'):fullDay(dateFromKey(k)))+'</h4>'+groups[k].map(function(i){return detail(i,false);}).join('')+'</div>';}).join('')+'</div>';}
  function visibleItems(){if(mode==='schedule')return items;if(mode==='day')return itemsForDay(current);if(mode==='week')return itemsForRange(startOfWeek(current),addDays(startOfWeek(current),7));if(mode==='workweek')return itemsForRange(startOfWeek(current),addDays(startOfWeek(current),5));return itemsForRange(startOfMonth(current),addMonths(startOfMonth(current),1));}
  function render(){
    var html=mode==='month'?monthView():mode==='day'?dayView():mode==='week'?weekView(false):mode==='workweek'?weekView(true):scheduleView();body.innerHTML=html;
    var visible=visibleItems();var title=document.getElementById('strategyCalTitle');if(title)title.textContent=toolbarTitle();var count=document.getElementById('strategyCalVisible');if(count)count.textContent=String(visible.length);var label=document.getElementById('strategyCalVisibleLabel');if(label)label.textContent=window.t('js.cal.n_visible',{count:visible.length});
    var upcoming=document.getElementById('strategyCalUpcoming');if(upcoming)upcoming.textContent=String(items.filter(function(i){return !statusDone(i)&&!isPast(i);}).length);var completed=document.getElementById('strategyCalCompleted');if(completed)completed.textContent=String(items.filter(statusDone).length);
    document.querySelectorAll('.calendarModeBtn[data-cal-mode]').forEach(function(b){b.classList.toggle('active',b.getAttribute('data-cal-mode')===mode);});setUrl();
  }
  document.querySelectorAll('.calendarModeBtn[data-cal-mode]').forEach(function(btn){btn.addEventListener('click',function(){mode=btn.getAttribute('data-cal-mode')||'month';render();});});
  document.querySelectorAll('[data-cal-nav]').forEach(function(btn){btn.addEventListener('click',function(){var nav=btn.getAttribute('data-cal-nav');if(nav==='today'){current=startOfDay(new Date());}else{var step=nav==='prev'?-1:1;if(mode==='day')current=addDays(current,step);else if(mode==='week'||mode==='workweek')current=addDays(current,7*step);else current=addMonths(current,step);}render();});});
  body.addEventListener('click',function(event){var dayBtn=event.target&&event.target.closest?event.target.closest('[data-calendar-day]'):null;if(!dayBtn)return;if(event.target.closest('.strategyCalendarEditBtn'))return;current=dateFromKey(dayBtn.getAttribute('data-calendar-day'));mode='day';render();});
  render();
})();
