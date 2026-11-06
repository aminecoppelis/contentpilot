(function(){
  'use strict';
  var config=window.__PG_PUBLICATION_CALENDAR;if(!config)return;
  var host=document.getElementById('publicationScheduler'),statusText=document.getElementById('publicationCalendarStatusText');
  var statusFilter=document.getElementById('publicationCalendarStatus'),platformFilter=document.getElementById('publicationCalendarPlatform');
  var details=document.getElementById('publicationCalendarDetails'),form=document.getElementById('publicationCalendarForm');
  var mode="all";
  var scheduler,preferences,datePicker,lastEventElement,selected=null,busy=false,loadId=0,requestController;
  function t(key,params){return window.t('js.pub_calendar.'+key,params);}
  function loading(active){var shell=document.getElementById('publicationCalendarShell');if(shell){shell.classList.toggle('is-loading',active);shell.setAttribute('aria-busy',String(active));}statusText.hidden=active;}
  function message(text,error){statusText.textContent=text;statusText.className=error?'publicationCalendarStatusError':'';if(error)loading(false);}
  function eventLabel(event){var key="js.cal.status."+event.Status,value=window.t(key);return event.Kind==="action"?(value===key?statusLabel(event.Status):value):statusLabel(event.Status);}
  function kindLabel(event){return window.t(event.Kind==="action"?"js.calendar.action":"js.calendar.publication");}
  function statusLabel(status){var key='posts.publication.'+status,value=window.t(key);return value===key?window.t('posts.publication.other'):value;}
  function format(value){return new Intl.DateTimeFormat(window.__LOCALE||'fr',{timeZone:config.timezone,dateStyle:'medium',timeStyle:'short'}).format(new Date(value));}
  function localInput(value){var parts=new Intl.DateTimeFormat('en-GB',{timeZone:config.timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)),p={};parts.forEach(function(part){p[part.type]=part.value;});return p.year+'-'+p.month+'-'+p.day+'T'+p.hour+':'+p.minute;}
  function showDetails(event,focus){
    selected=event;details.hidden=false;
    document.getElementById('publicationCalendarDetailTitle').textContent=event.Subject||t('untitled');
    document.getElementById('publicationCalendarDetailStatus').textContent=[kindLabel(event),event.Platform,event.Account,eventLabel(event)].filter(Boolean).join(' · ');
    document.getElementById('publicationCalendarDetailTime').textContent=format(event.UtcStart)+' · '+config.timezone;
    document.getElementById('publicationCalendarPostLink').href=event.PostUrl||'#';
    document.getElementById('publicationCalendarPostLink').hidden=!event.PostUrl;
    var dateLabel=form.querySelector('label');if(dateLabel)dateLabel.textContent=window.t(event.Kind==='action'?'sd.task.date':'pm.pub.datetime');
    form.querySelector('button[type=submit]').textContent=event.Kind==='action'?window.t('sd.task.title'):t('change');
    form.hidden=!!event.IsReadonly;document.getElementById('publicationCalendarReadonly').hidden=!event.IsReadonly;
    document.getElementById('publicationCalendarReadonly').textContent=event.Kind==='action'?window.t('js.calendar.action_readonly'):t('readonly');
    document.getElementById('publicationCalendarDate').value=localInput(event.UtcStart);
    if(datePicker){datePicker.value=new Date(localInput(event.UtcStart));datePicker.dataBind();}
    if(focus){var title=document.getElementById('publicationCalendarDetailTitle');title.tabIndex=-1;title.focus({preventScroll:true});}
  }
  function filterHint(){
    var restricted=statusFilter.value!=='all'||platformFilter.value!=='all',hint=document.getElementById('publicationCalendarFilterScope'),reset=document.getElementById('publicationCalendarResetFilters');
    if(hint)hint.textContent=window.t(mode==='actions'?'js.calendar.actions_hint':restricted?'js.calendar.filtered_hint':'js.calendar.filter_hint');
    if(reset)reset.hidden=!restricted;
  }
  function savePreferences(){if(preferences)preferences.saveState({kind:'calendar',version:1,mode:mode,activeView:scheduler.currentView,status:statusFilter.value,platform:platformFilter.value},false);}
  async function load(){
    if(!scheduler)return;
    var current=++loadId;if(requestController)requestController.abort();requestController=new AbortController();
    var dates=scheduler.getCurrentViewDates(),start=dates.length?new Date(dates[0]):new Date(scheduler.selectedDate),end=dates.length?new Date(dates[dates.length-1]):new Date(start);
    if(!dates.length){start.setDate(1);end=new Date(start);end.setDate(end.getDate()+42);}else end.setDate(end.getDate()+1);
    var zone=new ej.schedule.Timezone();
    var query=new URLSearchParams({start:zone.remove(start,config.timezone).toISOString(),end:zone.remove(end,config.timezone).toISOString(),status:statusFilter.value,platform:platformFilter.value,strategy_id:config.strategyId});
    loading(true);
    try{
      var urls=[];if(mode!=='actions')urls.push('/app/publication-calendar/events?'+query);
      if(mode!=='publications'&&statusFilter.value==='all'&&platformFilter.value==='all')urls.push('/app/strategy-calendar/actions?'+query);
      var bodies=await Promise.all(urls.map(async function(url){var response=await fetch(url,{signal:requestController.signal,cache:'no-store'});var data=await response.json();if(!response.ok||data.success!==true)throw new Error('load');return data;}));
      var body={data:bodies.flatMap(function(data){return data.data;})};
      if(current!==loadId)return;
      var events=body.data.map(function(event){return Object.assign({},event,{UtcStart:event.StartTime,StartTime:new Date(event.StartTime),EndTime:new Date(event.EndTime)});});
      scheduler.eventSettings.dataSource=events;scheduler.dataBind();
      message(events.length?window.t('js.cal.n_visible',{count:events.length}):window.t('js.cal.no_item'));
      if(selected){var fresh=events.find(function(event){return event.Id===selected.Id;});if(fresh)showDetails(fresh);else{selected=null;details.hidden=true;}}
    }catch(error){if(error.name!=='AbortError'&&current===loadId)message(t('error'),true);}
    finally{if(current===loadId)loading(false);}
  }
  async function move(event,value){
    if(busy||!event||event.IsReadonly)return;
    busy=true;var submit=form.querySelector('button[type="submit"]');submit.disabled=true;statusFilter.disabled=true;platformFilter.disabled=true;
    try{
      var display=/Z$|[+-]\d\d:\d\d$/.test(value)?format(value):value.replace('T',' ');
      var changeLabel=event.Kind==='action'?window.t('sd.task.title'):t('change');
      var prompt=event.Kind==='action'?changeLabel+' : '+display+' · '+config.timezone:t('confirm',{date:display+' · '+config.timezone});
      var confirmed=await window.pgConfirm(prompt+'\n\n'+[event.Subject,event.Platform,event.Account].filter(Boolean).join(' · '),{confirmText:changeLabel,cancelText:window.t('js.cancel')});
      if(!confirmed)return;
      message(t('saving'));
      var action=event.Kind==='action';
      var response=await fetch(action?'/app/strategies/calendar/reschedule':'/app/publication-calendar/'+encodeURIComponent(event.Id),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(action?{calendar_id:event.ActionId,planned_for:value,strategy_id:config.strategyId}:{scheduled_at:value,expected_updated_at:event.Revision,strategy_id:config.strategyId})});
      if(!response.ok){if(response.status===409)throw new Error(t('conflict'));if(response.status===422)throw new Error(t('future'));throw new Error(t('error'));}
      window.pgToast(action?window.t('js.saved'):t('saved'),'success');
    }catch(error){window.pgToast(error.message||t('error'),'error');}
    finally{busy=false;submit.disabled=false;statusFilter.disabled=platformFilter.disabled=mode==='actions';await load();}
  }
  async function init(){
    if(!window.ej||!ej.schedule){message(t('unavailable'),true);return;}
    var locale=window.__LOCALE||'fr',localeController=new AbortController(),timer=setTimeout(function(){localeController.abort();},5000);
    try{
      var ready=window.pgTablePreferences?window.pgTablePreferences.load():Promise.resolve();
      var resources=await Promise.all([
        fetch('/static/vendor/syncfusion/locales/'+locale+'.json',{signal:localeController.signal}).then(function(r){if(!r.ok)throw new Error('locale');return r.json();}),
        fetch('/static/vendor/syncfusion/cldr/'+locale+'.json',{signal:localeController.signal}).then(function(r){if(!r.ok)throw new Error('culture');return r.json();}),ready
      ]);
      ej.base.L10n.load(resources[0]);ej.base.loadCldr.apply(ej.base,resources[1]);
    }catch(error){locale='en-US';}finally{clearTimeout(timer);}
    if(ready)await ready;
    if(window.pgTablePreferences)preferences=window.pgTablePreferences.create('publication_calendar',0);
    var saved=preferences&&preferences.state&&preferences.state.kind==='calendar'?preferences.state:null;
    if(saved){mode=saved.mode||'all';statusFilter.value=saved.status;platformFilter.value=saved.platform;if(!platformFilter.value)platformFilter.value='all';}
    ej.schedule.Schedule.Inject(ej.schedule.Day,ej.schedule.Week,ej.schedule.Month,ej.schedule.Agenda,ej.schedule.DragAndDrop);
    scheduler=new ej.schedule.Schedule({width:'100%',height:'680px',locale:locale,enableRtl:window.__DIR==='rtl',timezone:config.timezone,
      currentView:saved?saved.activeView:'Month',views:['Day','Week','Month','Agenda'],firstDayOfWeek:1,timeFormat:'HH:mm',
      allowDragAndDrop:true,allowResizing:false,showQuickInfo:false,enableHtmlSanitizer:true,
      eventSettings:{dataSource:[],allowAdding:false,allowDeleting:false,allowEditing:true,
        template:function(data){var element=document.createElement('div');element.className='publicationEventCard';var title=document.createElement('strong'),info=document.createElement('small');title.textContent=data.Subject||t('untitled');info.textContent=[kindLabel(data),data.Platform,eventLabel(data)].filter(Boolean).join(' · ');element.append(title,info);return [element];}},
      created:function(){load();},
      actionComplete:function(args){if(['dateNavigate','viewNavigate'].includes(args.requestType)){load();savePreferences();}},
      actionBegin:function(args){
        if(args.requestType==='eventCreate'||args.requestType==='eventRemove'){args.cancel=true;return;}
        if(args.requestType==='eventChange'){
          args.cancel=true;var event=Array.isArray(args.data)?args.data[0]:args.data;
          if(event&&!event.IsReadonly){var instant=new ej.schedule.Timezone().remove(new Date(event.StartTime),config.timezone);move(event,instant.toISOString());}
        }
      },
      dragStart:function(args){if(busy||args.data.IsReadonly)args.cancel=true;},
      eventClick:function(args){args.cancel=true;lastEventElement=args.element;showDetails(args.event,true);},
      eventDoubleClick:function(args){args.cancel=true;},cellClick:function(args){args.cancel=true;},cellDoubleClick:function(args){args.cancel=true;},
      popupOpen:function(args){args.cancel=true;},
      eventRendered:function(args){args.element.classList.add('pubEvent--'+args.data.Status);if(args.data.Kind==='action')args.element.classList.add('strategyActionEvent');args.element.title=(args.data.Subject||t('untitled'))+' · '+eventLabel(args.data);}
    });
    showKind(mode);
    scheduler.appendTo(host);
    statusFilter.onchange=platformFilter.onchange=function(){filterHint();savePreferences();load();};
    var resetFilters=document.getElementById('publicationCalendarResetFilters');if(resetFilters)resetFilters.onclick=function(){statusFilter.value=platformFilter.value='all';filterHint();savePreferences();load();};
    document.getElementById('publicationCalendarRefresh').onclick=load;
    document.getElementById('publicationCalendarClose').onclick=function(){selected=null;details.hidden=true;if(lastEventElement&&lastEventElement.isConnected)lastEventElement.focus();else{host.tabIndex=0;host.focus();}};
    var nativeDate=document.getElementById('publicationCalendarDate');
    if(ej.calendars&&ej.calendars.DateTimePicker){
      var input=document.createElement('input');input.id='publicationCalendarDateControl';nativeDate.after(input);
      try{
        datePicker=new ej.calendars.DateTimePicker({locale:locale,enableRtl:window.__DIR==='rtl',format:'yyyy-MM-dd HH:mm',step:15,strictMode:true,showClearButton:false});
        datePicker.appendTo(input);nativeDate.hidden=true;nativeDate.required=false;
        var label=form.querySelector('label');if(label)label.htmlFor=input.id;
      }catch(error){if(datePicker)try{datePicker.destroy();}catch(ignore){}datePicker=null;input.remove();}
    }
    form.onsubmit=function(event){event.preventDefault();if(!selected)return;
      var value=nativeDate.value;
      if(datePicker){var date=datePicker.value;if(!(date instanceof Date)||isNaN(date.getTime())){window.pgToast(t('future'),'error');return;}var pad=function(n){return String(n).padStart(2,'0');};value=date.getFullYear()+'-'+pad(date.getMonth()+1)+'-'+pad(date.getDate())+'T'+pad(date.getHours())+':'+pad(date.getMinutes());}
      move(selected,value);
    };
    var interval=setInterval(function(){if(!busy&&!host.closest('[hidden]')&&document.visibilityState==='visible')load();},60000);
    window.addEventListener('pagehide',function(){clearInterval(interval);if(requestController)requestController.abort();if(datePicker)datePicker.destroy();});
  }
  var publicationRoot=document.getElementById('strategyPublicationCalendarRoot'),started=false;
  function activate(){
    if(host.closest('[hidden]'))return;
    if(started){if(scheduler){scheduler.refreshLayout();load();}return;}
    started=true;loading(true);init().catch(function(){message(t('error'),true);});
  }
  function showKind(kind){
    if(busy)return;
    mode=kind;selected=null;details.hidden=true;
    if(mode==='actions'){statusFilter.value='all';platformFilter.value='all';}
    statusFilter.disabled=platformFilter.disabled=mode==='actions';
    filterHint();
    document.querySelectorAll('[data-strategy-calendar-kind]').forEach(function(button){var active=button.dataset.strategyCalendarKind===mode;button.setAttribute('aria-pressed',String(active));button.classList.toggle('primary',active);button.classList.toggle('secondary',!active);});
    if(scheduler&&scheduler.element){savePreferences();load();}
  }
  document.querySelectorAll('[data-strategy-calendar-kind]').forEach(function(button){button.onclick=function(){showKind(button.dataset.strategyCalendarKind);};});
  document.querySelectorAll('[data-strategy-jump="calendar"]').forEach(function(button){button.addEventListener('click',function(){showKind('actions');});});
  var observer=new MutationObserver(activate),panel=host.closest('[data-strategy-panel]');
  if(panel)observer.observe(panel,{attributes:true,attributeFilter:['hidden']});
  window.addEventListener('pagehide',function(){observer.disconnect();});
  activate();
})();
