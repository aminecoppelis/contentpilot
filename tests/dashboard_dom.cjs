const fs=require('fs'),assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('../.cache/grid-tests/node_modules/jsdom');
const engine=fs.readFileSync('.cache/grid-tests/ej2.min.js','utf8'),script=fs.readFileSync('static/js/dashboard.js','utf8');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(locale,empty=false,sdk=true){
 const catalog=JSON.parse(fs.readFileSync('translations/'+locale+'.json','utf8'));
 const history=Array.from({length:14},(_,i)=>({day:'2026-11-'+String(i+1).padStart(2,'0'),total:empty?0:i%4}));
 const data={history,statuses:empty?{}:{published:12,scheduled:3,failed:1}};
 const dom=new JSDOM(`<html><body><select id="dashboardPeriod"><option value="14">14</option><option value="7">7</option></select><div data-dashboard-chart-shell><div class="dashChartSkeleton"></div><div id="dashboardActivityChart"></div></div><div data-dashboard-chart-shell><div id="dashboardStatusChart"></div><p id="dashboardNoPublications" hidden></p></div><details id="dashboardHistoryData">${history.map(d=>`<div data-dashboard-day="${d.day}"></div>`).join('')}</details><script id="dashboardMetrics" type="application/json">${JSON.stringify(data)}</script></body></html>`,{url:'http://localhost/app/dashboard',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()});
 const w=dom.window,style=w.getComputedStyle.bind(w);w.getComputedStyle=e=>style(e);
 w.__LOCALE=locale;w.__DIR=locale==='ar'?'rtl':'ltr';w.t=k=>catalog[k]||k;
 w.matchMedia=()=>({matches:true,addListener(){},removeListener(){}});
 w.HTMLElement.prototype.getBoundingClientRect=()=>({top:0,left:0,right:600,bottom:300,width:600,height:300,x:0,y:0});
 w.HTMLCanvasElement.prototype.getContext=()=>({measureText:s=>({width:String(s).length*7})});
 if(sdk){w.eval(engine);if(process.env.TEST_LICENSE)w.ej.base.registerLicense(process.env.TEST_LICENSE);}
 w.eval(script);await wait(200);
 const chart=w.document.getElementById('dashboardActivityChart').ej2_instances?.[0];
 if(sdk){
  assert(chart,'Activity chart initialized');assert.equal(chart.series[0].dataSource.length,14);
  assert(w.document.querySelector('#dashboardActivityChart svg'),'Real Syncfusion SVG rendered');
  assert(w.document.querySelector('.dashChartSkeleton').hidden);
  if(empty)assert(!w.document.getElementById('dashboardNoPublications').hidden);
  else assert.equal(w.document.getElementById('dashboardStatusChart').ej2_instances[0].series[0].dataSource.length,3);
 }else{assert(w.document.getElementById('dashboardHistoryData').open);assert(w.document.querySelector('[data-dashboard-chart-shell]').hidden);}
 const period=w.document.getElementById('dashboardPeriod');period.value='7';period.onchange();await wait(100);
 if(sdk)assert.equal(chart.series[0].dataSource.length,7);
 assert.equal([...w.document.querySelectorAll('[data-dashboard-day]')].filter(e=>!e.hidden).length,7);
 w.dispatchEvent(new w.Event('pagehide'));w.close();
}
(async()=>{for(const locale of ['fr','en','de','es','it','ru','ar'])await run(locale);await run('fr',true);await run('fr',false,false);console.log('PASS: real Syncfusion dashboard charts, seven locales, 7/14-day selection, empty data, readable fallback and cleanup');})().catch(e=>{console.error(e.stack?.slice(0,1400));process.exit(1);});
