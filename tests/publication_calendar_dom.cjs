const fs=require('fs'),assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('../.cache/grid-tests/node_modules/jsdom');
const root=process.cwd(),engine=fs.readFileSync(root+'/.cache/grid-tests/ej2.min.js','utf8'),script=fs.readFileSync(root+'/static/js/publication-calendar.js','utf8');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(locale,interaction){
  const html=`<html><body><div id="publicationScheduler"></div><p id="publicationCalendarStatusText"></p><p id="publicationCalendarFilterScope"></p><button id="publicationCalendarResetFilters" hidden></button><select id="publicationCalendarStatus"><option value="all">All</option><option value="scheduled">Scheduled</option><option value="published">Published</option></select><select id="publicationCalendarPlatform"><option value="all">All</option><option value="linkedin">LinkedIn</option></select><aside id="publicationCalendarDetails" hidden><h2 id="publicationCalendarDetailTitle"></h2><p id="publicationCalendarDetailStatus"></p><p id="publicationCalendarDetailTime"></p><a id="publicationCalendarPostLink"></a><form id="publicationCalendarForm"><input type="datetime-local" id="publicationCalendarDate"><button type="submit">Save</button></form><p id="publicationCalendarReadonly"></p></aside><button id="publicationCalendarClose"></button><button id="publicationCalendarRefresh"></button></body></html>`;
  const dom=new JSDOM(html,{url:'http://localhost/app/publication-calendar',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()});
  const w=dom.window,style=w.getComputedStyle.bind(w),catalog=JSON.parse(fs.readFileSync(root+'/translations/'+locale+'.json','utf8'));
  w.getComputedStyle=element=>style(element);w.matchMedia=()=>({matches:false,addListener(){},removeListener(){}});
  w.HTMLElement.prototype.getBoundingClientRect=()=>({top:0,left:0,right:180,bottom:40,width:180,height:40,x:0,y:0});
  w.HTMLElement.prototype.scrollIntoView=function(){};w.HTMLCanvasElement.prototype.getContext=()=>({measureText:s=>({width:String(s).length*8})});
  w.ResizeObserver=class{observe(){}disconnect(){}unobserve(){}};
  w.__PG_PUBLICATION_CALENDAR={timezone:'America/New_York',strategyId:'22222222-2222-4222-8222-222222222222'};w.__LOCALE=locale;w.__DIR=locale==='ar'?'rtl':'ltr';
  w.t=(key,params)=>{let text=catalog[key]||key;for(const k in params||{})text=text.replace('{'+k+'}',params[k]);return text;};
  let originalStart=null,puts=[],saved=[],toasts=[],confirmed=true;
  w.pgToast=message=>toasts.push(message);w.pgConfirm=async()=>confirmed;
  w.pgTablePreferences={load:async()=>{},create:()=>({state:{kind:'calendar',version:1,activeView:'Week',status:'all',platform:'all'},saveState:state=>saved.push(state)})};
  let currentInstant,eventRequests=0;
  if(interaction){
    const panel=w.document.createElement('section');panel.dataset.strategyPanel='calendar';panel.hidden=true;
    const root=w.document.createElement('div');root.id='strategyPublicationCalendarRoot';while(w.document.body.firstChild)root.appendChild(w.document.body.firstChild);
    const actions=w.document.createElement('div');actions.id='strategyActionCalendarRoot';actions.hidden=true;
    const navigation=w.document.createElement('div');navigation.innerHTML='<button data-strategy-calendar-kind="actions"></button><button data-strategy-calendar-kind="publications"></button>';
    panel.append(navigation,root,actions);w.document.body.append(panel);
  }
  const revision='2026-01-01T10:00:00.123456+00:00';
  w.fetch=async(url,options={})=>{
    if(url.startsWith('/static/'))return {ok:true,json:async()=>w.JSON.parse(fs.readFileSync(root+url,'utf8'))};
    if(options.method==='PUT'){
      puts.push(JSON.parse(options.body));assert.equal(puts.at(-1).strategy_id,w.__PG_PUBLICATION_CALENDAR.strategyId);currentInstant=new Date(puts.at(-1).scheduled_at||puts.at(-1).planned_for);
      return {ok:true,status:200,json:async()=>({success:true})};
    }
    eventRequests++;const query=new URL(url,'http://localhost').searchParams;assert.equal(query.get('strategy_id'),w.__PG_PUBLICATION_CALENDAR.strategyId);
    if(!currentInstant){currentInstant=new Date(query.get('start'));currentInstant.setUTCDate(currentInstant.getUTCDate()+2);currentInstant.setUTCHours(15,0,0,0);originalStart=new Date(currentInstant);}
    const event={Id:'scheduled',Subject:'Example post',StartTime:currentInstant.toISOString(),EndTime:new Date(+currentInstant+1800000).toISOString(),IsReadonly:false,Status:'scheduled',Platform:'linkedin',Account:'Example',Revision:revision,PostUrl:'/app/posts/view?idea_id=example'};
    let data=url.startsWith('/app/strategy-calendar/actions')?[{...event,Id:'action:task',ActionId:'task',Kind:'action',Platform:'',PostUrl:''}]:[event,{...event,Id:'published',Status:'published',IsReadonly:true}];
    if(query.get('status')!=='all')data=data.filter(e=>e.Status===query.get('status'));
    return {ok:true,json:async()=>w.JSON.parse(JSON.stringify({success:true,data}))};
  };
  w.eval(engine);if(process.env.TEST_LICENSE)w.ej.base.registerLicense(process.env.TEST_LICENSE);w.eval(script);
  if(interaction){await wait(100);assert.equal(eventRequests,0,'Hidden strategy calendar is not initialized');w.document.querySelector('[data-strategy-panel]').hidden=false;}
  await wait(1000);
  const instance=w.document.getElementById('publicationScheduler').ej2_instances?.[0];
  assert(instance,'Scheduler initialized for '+locale+'; status='+w.document.getElementById('publicationCalendarStatusText').textContent);
  await wait(250);assert.equal(instance.currentView,'Week');assert.equal(instance.eventsData.length,3,'Events loaded for '+locale);
  assert.equal(instance.timezone,'America/New_York');assert.equal(instance.eventSettings.allowAdding,false);assert.equal(instance.eventSettings.allowDeleting,false);
  if(interaction){
    const scheduled=instance.eventsProcessed.find(e=>e.Id==='scheduled');
    instance.eventClick({cancel:false,event:scheduled});
    assert(!w.document.getElementById('publicationCalendarDetails').hidden);
    assert.equal(w.document.getElementById('publicationCalendarDate').value.slice(-5),new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(originalStart),'Profile timezone shown rather than UTC browser timezone');
    instance.saveEvent({...scheduled,StartTime:new w.Date(+scheduled.StartTime+3600000),EndTime:new w.Date(+scheduled.EndTime+3600000)});
    await wait(700);
    assert.equal(puts.length,1,'Dragging schedules exactly one update');
    assert.equal(new Date(puts[0].scheduled_at).getTime(),+originalStart+3600000,'Drag converted back to UTC correctly');
    assert.equal(puts[0].expected_updated_at,revision,'Microsecond revision preserved');
    const published=instance.eventsProcessed.find(e=>e.Id==='published');
    instance.eventClick({cancel:false,event:published});assert(w.document.getElementById('publicationCalendarForm').hidden);
    instance.saveEvent({...published,StartTime:new w.Date(+published.StartTime+3600000),EndTime:new w.Date(+published.EndTime+3600000)});await wait(200);
    assert.equal(puts.length,1,'Published post cannot be moved');
    confirmed=false;
    const next=instance.eventsProcessed.find(e=>e.Id==='scheduled');
    instance.saveEvent({...next,StartTime:new w.Date(+next.StartTime+3600000),EndTime:new w.Date(+next.EndTime+3600000)});await wait(500);
    assert.equal(puts.length,1,'Cancelling confirmation does not update the publication');
    w.document.getElementById('publicationCalendarStatus').value='published';w.document.getElementById('publicationCalendarStatus').onchange();await wait(500);
    assert.equal(instance.eventsData.length,1);assert.equal(saved.at(-1).status,'published');assert(!w.document.getElementById('publicationCalendarResetFilters').hidden);assert.equal(w.document.getElementById('publicationCalendarFilterScope').textContent,catalog['js.calendar.filtered_hint']);
    instance.currentView='Month';instance.dataBind();await wait(500);
    assert.equal(saved.at(-1).activeView,'Month','Calendar view saved on navigation');
    w.document.querySelector('[data-strategy-calendar-kind=actions]').click();await wait(400);assert(!w.document.getElementById('strategyPublicationCalendarRoot').hidden);assert.equal(instance.eventsData.length,1);assert.equal(instance.eventsData[0].Kind,'action');assert.equal(w.document.getElementById('publicationScheduler').ej2_instances[0],instance,'Same Scheduler for both types');
    confirmed=true;const task=instance.eventsProcessed[0];instance.saveEvent({...task,StartTime:new w.Date(+task.StartTime+3600000),EndTime:new w.Date(+task.EndTime+3600000)});await wait(500);assert.equal(puts.length,2);assert.equal(puts[1].calendar_id,'task');assert(puts[1].planned_for);assert(!puts[1].scheduled_at,'Action rescheduling is separate from publication scheduling');
    w.document.querySelector('[data-strategy-calendar-kind=publications]').click();await wait(300);assert(!w.document.getElementById('strategyPublicationCalendarRoot').hidden);
    assert.equal(instance.eventsData.length,2);assert.equal(toasts.length,2);
    const editable=instance.eventsProcessed.find(e=>e.Id==='scheduled');instance.eventClick({cancel:false,event:editable});
    const picker=w.document.getElementById('publicationCalendarDateControl').ej2_instances[0];assert(picker,'Real Syncfusion DateTimePicker initialized');
    picker.value=new w.Date(2099,0,10,9,0);picker.dataBind();w.document.getElementById('publicationCalendarForm').dispatchEvent(new w.Event('submit',{cancelable:true}));await wait(500);
    assert.equal(puts.length,3);assert.equal(puts[2].scheduled_at,'2099-01-10T09:00','Date picker sends account wall-clock time for server timezone conversion');assert.equal(puts[2].expected_updated_at,revision);
    w.document.getElementById('publicationCalendarClose').click();assert(w.document.getElementById('publicationCalendarDetails').hidden);

  }
  w.dispatchEvent(new w.Event('pagehide'));instance.destroy();w.close();
}
(async()=>{for(const locale of ['fr','en','de','es','it','ru','ar'])await run(locale,locale==='fr');console.log('PASS: real strategy-embedded Scheduler in seven locales, lazy initialization, strategy-scoped requests, saved view, filters, UTC drag conversion, precise revisions, DateTimePicker account wall-clock submission, explicit filter scope, confirmation cancellation and published read-only guards');})().catch(error=>{console.error(error.stack?.slice(0,1600)||String(error));process.exitCode=1;setTimeout(()=>process.exit(1),50);});
