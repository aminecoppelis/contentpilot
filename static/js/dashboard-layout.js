(function(){
  'use strict';
  var host=document.getElementById('dashboardLayout'),customize=document.getElementById('dashboardCustomize'),reset=document.getElementById('dashboardLayoutReset');
  if(!host||!window.ej||!ej.layouts||!ej.layouts.DashboardLayout)return;
  var ids=Array.from(host.children).map(function(panel){return panel.id;}),layout,editing=false,ready=false;
  var key='pg_dashboard_order_v1:'+host.dataset.user+':'+host.dataset.workspace;
  function t(name){return window.t('js.dash.'+name);}
  function order(){return layout.panels.slice().sort(function(a,b){return a.row-b.row||a.col-b.col;}).map(function(panel){return panel.id;});}
  function notify(){document.dispatchEvent(new CustomEvent('pg:dashboard-layout'));}
  function save(){
    if(!ready)return;var current=order();
    current.forEach(function(id,index){var panel=document.getElementById(id);if(panel)panel.style.order=index;});
    try{localStorage.setItem(key,JSON.stringify(current));}catch(ignore){}
    notify();
  }
  function setEditing(value){
    editing=!!value&&!window.matchMedia('(max-width: 900px)').matches;
    host.classList.toggle('is-customizing',editing);layout.allowDragging=editing;layout.dataBind();
    customize.setAttribute('aria-pressed',String(editing));customize.textContent=t(editing?'finish_layout':'customize');reset.hidden=!editing;
    document.getElementById('dashboardLayoutHint').textContent=t(editing?'edit_layout_hint':'layout_hint');
  }
  try{
    var saved;try{saved=JSON.parse(localStorage.getItem(key));}catch(ignore){}
    if(Array.isArray(saved)&&saved.length===ids.length&&new Set(saved).size===ids.length&&saved.every(function(id){return ids.includes(id);})){
      saved.forEach(function(id,index){var panel=document.getElementById(id);panel.dataset.row=Math.floor(index/2);panel.dataset.col=index%2;panel.style.order=index;});
    }
    var width=host.getBoundingClientRect().width||1000;
    layout=new ej.layouts.DashboardLayout({columns:2,cellSpacing:[20,20],cellAspectRatio:Math.max(.5,(width-20)/2/470),
      allowDragging:false,allowResizing:false,allowFloating:false,draggableHandle:'.dashPanelHandle',mediaQuery:'(max-width: 900px)',enableRtl:window.__DIR==='rtl',
      change:save,dragStop:save
    });
    layout.appendTo(host);host.classList.remove('dashLayoutFallback');ready=true;customize.hidden=false;
    customize.onclick=function(){setEditing(!editing);notify();};
    host.querySelectorAll('[data-panel-move]').forEach(function(button){button.onclick=function(){
      if(!editing)return;var id=button.closest('.e-panel').id,current=order(),index=current.indexOf(id),target=index+Number(button.dataset.panelMove);
      if(target<0||target>=current.length)return;
      var model=layout.panels.find(function(panel){return panel.id===current[target];});
      layout.movePanel(id,model.row,model.col);save();button.focus();
    };});
    reset.onclick=function(){
      // Move from the end so SDK collision handling leaves the requested order intact.
      ids.slice().reverse().forEach(function(id){var index=ids.indexOf(id);layout.movePanel(id,Math.floor(index/2),index%2);});save();
    };
    var timer,lastWidth=width,observer;
    function refresh(){clearTimeout(timer);timer=setTimeout(function(){
      if(window.matchMedia('(max-width: 900px)').matches&&editing)setEditing(false);
      var width=host.getBoundingClientRect().width;if(width){lastWidth=width;layout.cellAspectRatio=Math.max(.5,(width-20)/2/470);layout.dataBind();layout.refresh();}notify();
    },160);}
    window.addEventListener('resize',refresh);
    if(window.ResizeObserver){observer=new ResizeObserver(function(entries){var width=entries[0].contentRect.width;if(Math.abs(width-lastWidth)>2)refresh();});observer.observe(host);}
    window.addEventListener('pagehide',function(){clearTimeout(timer);if(observer)observer.disconnect();ready=false;layout.destroy();});
  }catch(error){
    ready=false;if(layout)try{layout.destroy();}catch(ignore){}
    host.classList.add('dashLayoutFallback');customize.hidden=true;reset.hidden=true;
  }
})();
