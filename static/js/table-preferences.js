(function(){
  'use strict';
  var preferences={},available=false,controllers=[],warned=false;
  var pageKeys={posts:['origin','q','status'],publications:['filter'],strategies:['status','q']};
  function warning(){if(!warned&&window.pgToast){warned=true;window.pgToast(window.t('js.grid.preferences_error'),'error');}}
  function pageFilters(key){var out={},url=new URL(location.href);(pageKeys[key]||[]).forEach(function(k){if(url.searchParams.has(k))out[k]=url.searchParams.get(k);});return out;}
  async function load(){
    var controller=new AbortController(),timer=setTimeout(function(){controller.abort();},5000);
    try{
      var response=await fetch('/app/table-preferences',{signal:controller.signal,cache:'no-store'});
      var data=await response.json();if(!response.ok||data.success!==true)throw new Error('load');
      preferences=data.data||{};available=true;
    }catch(error){warning();}finally{clearTimeout(timer);}
  }
  function restorePageFilters(tables){
    var first=tables[0],key=first&&first.dataset.gridView,keys=pageKeys[key]||[];
    var saved=((preferences[key]||{}).state||{}).pageFilters||{},url=new URL(location.href);
    if(!keys.length||keys.some(function(k){return url.searchParams.has(k);}))return false;
    var changed=false;
    keys.forEach(function(k){var value=saved[k];if(value&&value!=='all'){url.searchParams.set(k,value);changed=true;}});
    if(changed){url.searchParams.delete('page');location.replace(url.href);return true;}
    return false;
  }
  function create(key,columnCount){
    if(!key)return null;
    var entry=preferences[key]||{},revision=Number(entry.revision||0),timer,pending=null,queue=Promise.resolve(),last='',first=true;
    var saved=entry.state&&entry.state.version===1&&entry.state.columnCount===columnCount?entry.state:null;
    function snapshot(grid){
      return {version:1,columnCount:columnCount,
        filters:grid.filterSettings.columns.map(function(f){var value={field:f.field,operator:f.operator,value:f.value===undefined?null:f.value,predicate:f.predicate||'and',matchCase:!!f.matchCase,ignoreAccent:f.ignoreAccent!==false};if(f.type)value.type=f.type;return value;}),
        sort:grid.sortSettings.columns.map(function(s){return {field:s.field,direction:s.direction};}),
        search:String(grid.searchSettings.key||''),pageSize:Number(grid.pageSettings.pageSize),
        columns:grid.getColumns().filter(function(c){return /^c\d+$/.test(c.field);}).map(function(c){return {field:c.field,width:Math.max(40,Math.min(2000,parseFloat(c.width)||175)),visible:c.visible!==false};}),
        pageFilters:pageFilters(key)};
    }
    async function send(job,keepalive){
      try{
        var response=await fetch('/app/table-preferences/'+encodeURIComponent(key),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(job),keepalive:!!keepalive});
        if(!response.ok)throw new Error('save');warned=false;last=JSON.stringify(job.state);return true;
      }catch(error){warning();return false;}
    }
    function flush(keepalive){
      clearTimeout(timer);if(!pending||!available)return queue;
      var job=pending;pending=null;
      if(keepalive)return send(job,true);
      queue=queue.then(function(){return send(job,false);});return queue;
    }
    function save(state,immediate){
      if(!available)return Promise.resolve(false);
      var serialized=JSON.stringify(state);if(serialized===last&&!pending)return queue;
      revision=Math.max(Date.now(),revision+1);pending={state:state,revision:revision};
      clearTimeout(timer);if(immediate)return flush(false);
      timer=setTimeout(function(){flush(false);},600);return queue;
    }
    var controller={saved:saved,state:entry.state,saveState:save,changed:function(grid){var state=snapshot(grid);if(first){first=false;if(saved&&JSON.stringify(saved.pageFilters||{})===JSON.stringify(state.pageFilters)){last=JSON.stringify(state);return;}}save(state,false);},
      reset:function(grid){var state=snapshot(grid);state.pageFilters={};return save(state,true);},
      clearPageFilters:function(){var url=new URL(location.href),changed=false;(pageKeys[key]||[]).forEach(function(k){if(url.searchParams.has(k)){url.searchParams.delete(k);changed=true;}});if(changed){url.searchParams.delete('page');location.replace(url.href);}},
      flush:flush};
    controllers.push(controller);return controller;
  }
  window.addEventListener('pagehide',function(){controllers.forEach(function(c){c.flush(true);});});
  document.addEventListener('visibilitychange',function(){if(document.visibilityState==='hidden')controllers.forEach(function(c){c.flush(true);});});
  window.pgTablePreferences={load:load,create:create,restorePageFilters:restorePageFilters};
})();
