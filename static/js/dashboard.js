(function(){
  var guide=document.getElementById('quickStart');
  if(!guide)return;
  var userId=String(guide.getAttribute('data-user-id')||'anonymous');
  var completed=Number(guide.getAttribute('data-completed')||0);
  var storageKey='pg_quick_start_hidden_'+userId;
  var hidden=false;
  try{hidden=localStorage.getItem(storageKey)==='1';}catch(_error){}
  if(completed>=4||hidden)guide.classList.add('isCollapsed');

  var hideButton=document.getElementById('quickStartHide');
  var openButton=document.getElementById('quickStartOpen');
  if(hideButton)hideButton.addEventListener('click',function(){
    guide.classList.add('isCollapsed');
    try{localStorage.setItem(storageKey,'1');}catch(_error){}
  });
  if(openButton)openButton.addEventListener('click',function(){
    guide.classList.remove('isCollapsed');
    try{localStorage.removeItem(storageKey);}catch(_error){}
    var title=document.getElementById('quickStartTitle');
    if(title)title.focus({preventScroll:true});
  });
})();

(function(){
  'use strict';
  var source=document.getElementById('dashboardMetrics');if(!source)return;
  var data;try{data=JSON.parse(source.textContent);}catch(error){return;}
  var historyDetails=document.getElementById('dashboardHistoryData'),period=document.getElementById('dashboardPeriod'),charts=[];
  var layoutTimer;document.addEventListener('pg:dashboard-layout',function(){clearTimeout(layoutTimer);layoutTimer=setTimeout(function(){charts.forEach(function(chart){chart.refresh();});},80);});
  var colors={published:'#579d80',scheduled:'#6699dc',failed:'#cc7979',pending:'#c7a15e',processing:'#c7a15e',cancelled:'#a3afbf'};
  function t(key){return window.t('js.dash.'+key);}
  function statusLabel(status){var key='posts.publication.'+status,value=window.t(key);return value===key?window.t('posts.publication.other'):value;}
  function fallback(){document.querySelectorAll('[data-dashboard-chart-shell]').forEach(function(shell){shell.hidden=true;});historyDetails.open=true;}
  function history(){return data.history.slice(-Number(period.value)).map(function(item){return {day:new Intl.DateTimeFormat(window.__LOCALE||'fr',{day:'2-digit',month:'short',timeZone:'UTC'}).format(new Date(item.day+'T12:00:00Z')),total:item.total};});}
  function syncTable(){var visible=new Set(data.history.slice(-Number(period.value)).map(function(item){return item.day;}));document.querySelectorAll('[data-dashboard-day]').forEach(function(row){row.hidden=!visible.has(row.dataset.dashboardDay);});}
  function interval(){return Math.max(1,Math.ceil(Math.max.apply(null,data.history.map(function(item){return item.total;}).concat([0]))/4));}
  syncTable();
  if(!window.ej||!ej.charts){fallback();period.onchange=syncTable;return;}
  var reduced=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  try{
    ej.charts.Chart.Inject(ej.charts.ColumnSeries,ej.charts.Category,ej.charts.Tooltip);
    ej.charts.AccumulationChart.Inject(ej.charts.PieSeries,ej.charts.AccumulationTooltip);
    var activity=new ej.charts.Chart({height:'290px',width:'100%',background:'transparent',enableRtl:window.__DIR==='rtl',
      chartArea:{border:{width:0}},border:{width:0},legendSettings:{visible:false},
      primaryXAxis:{valueType:'Category',majorGridLines:{width:0},majorTickLines:{width:0},labelStyle:{color:'#64748b',size:'11px'},labelIntersectAction:'Rotate45'},
      primaryYAxis:{minimum:0,interval:interval(),majorTickLines:{width:0},lineStyle:{width:0},majorGridLines:{color:'#edf2f7'},labelStyle:{color:'#64748b',size:'11px'}},
      series:[{type:'Column',dataSource:history(),xName:'day',yName:'total',name:window.t('posts.publication.published'),fill:'#6699dc',columnWidth:.45,cornerRadius:{topLeft:4,topRight:4},animation:{enable:!reduced}}],
      tooltip:{enable:true,header:'',format:'${point.x} : ${point.y}'},
      loaded:function(){document.querySelectorAll('.dashChartSkeleton').forEach(function(el){el.hidden=true;});}
    });
    charts.push(activity);activity.appendTo('#dashboardActivityChart');
    var statuses=Object.keys(data.statuses).filter(function(key){return data.statuses[key]>0;}).map(function(key){return {name:statusLabel(key),total:data.statuses[key],color:colors[key]||'#a3afbf'};});
    document.querySelectorAll('.dashStatusDot').forEach(function(dot){dot.style.backgroundColor=colors[dot.dataset.status]||'#a3afbf';});
    if(statuses.length){
      var distribution=new ej.charts.AccumulationChart({height:'290px',width:'100%',background:'transparent',enableRtl:window.__DIR==='rtl',legendSettings:{visible:false},enableSmartLabels:true,
        series:[{type:'Pie',innerRadius:'72%',radius:'88%',dataSource:statuses,xName:'name',yName:'total',pointColorMapping:'color',animation:{enable:!reduced},border:{color:'#fff',width:3}}],
        tooltip:{enable:true,header:'',format:'${point.x} : ${point.y}'}
      });charts.push(distribution);distribution.appendTo('#dashboardStatusChart');
    }else{document.getElementById('dashboardStatusChart').hidden=true;document.getElementById('dashboardNoPublications').hidden=false;}
    period.onchange=function(){syncTable();activity.series[0].dataSource=history();activity.refresh();};
  }catch(error){charts.forEach(function(chart){try{chart.destroy();}catch(ignore){}});fallback();period.onchange=syncTable;}
  window.addEventListener('pagehide',function(){clearTimeout(layoutTimer);charts.forEach(function(chart){try{chart.destroy();}catch(ignore){}});});
})();
