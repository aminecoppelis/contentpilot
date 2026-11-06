const fs=require('fs'),assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('../.cache/grid-tests/node_modules/jsdom');
const engine=fs.readFileSync('.cache/grid-tests/ej2.min.js','utf8'),script=fs.readFileSync('static/js/dashboard-layout.js','utf8');
const ids=['upcoming','attention','activity','distribution'].map(n=>'dashPanel-'+n),key='pg_dashboard_order_v1:user:workspace';
for(const locale of ['fr','en','de','es','it','ru','ar']){
 const catalog=JSON.parse(fs.readFileSync('translations/'+locale+'.json','utf8'));
 const dom=new JSDOM(`<html><body><p id="dashboardLayoutHint"></p><button id="dashboardCustomize" hidden></button><button id="dashboardLayoutReset" hidden></button><div id="dashboardLayout" class="dashLayoutFallback" data-user="user" data-workspace="workspace">${ids.map((id,i)=>`<div class="e-panel" id="${id}" data-row="${Math.floor(i/2)}" data-col="${i%2}" data-sizex="1" data-sizey="1"><div class="e-panel-container"><div class="dashPanelHandle">Handle<button data-panel-move="-1">Up</button><button data-panel-move="1">Down</button></div><article class="panel"><a href="/app/posts" id="link-${i}">Content ${i}</a><select><option>14</option></select></article></div></div>`).join('')}</div></body></html>`,{url:'http://localhost/app/dashboard',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()});
 const w=dom.window;let mobile=false;w.t=k=>catalog[k]||k;w.__DIR=locale==='ar'?'rtl':'ltr';w.matchMedia=()=>({matches:mobile,addListener(){},removeListener(){}});
 w.HTMLElement.prototype.getBoundingClientRect=()=>({top:0,left:0,right:1200,bottom:500,width:1200,height:500,x:0,y:0});
 Object.defineProperty(w.HTMLElement.prototype,'offsetWidth',{get(){return this.id==='dashboardLayout'?1200:590;}});Object.defineProperty(w.HTMLElement.prototype,'offsetHeight',{get(){return 470;}});
 w.eval(engine);if(process.env.TEST_LICENSE)w.ej.base.registerLicense(process.env.TEST_LICENSE);
 const content=w.document.getElementById('link-0');let clicks=0;content.onclick=e=>{e.preventDefault();clicks++;};
 w.eval(script);
 const host=w.document.getElementById('dashboardLayout'),layout=host.ej2_instances?.[0];
 assert(layout,'Dashboard Layout initialized for '+locale);assert.equal(layout.panels.length,4);assert.equal(layout.allowDragging,false);assert(!w.document.getElementById('dashboardCustomize').hidden);
 content.click();assert.equal(clicks,1,'Original link listener preserved');
 w.document.getElementById('dashboardCustomize').click();assert.equal(layout.allowDragging,true);assert(host.classList.contains('is-customizing'));
 host.querySelector('[data-panel-move="1"]').click();
 const saved=JSON.parse(w.localStorage.getItem(key));assert.equal(saved.length,4);assert.notEqual(saved[0],ids[0],'Keyboard move changes panel order');
 assert.equal(w.document.getElementById('link-0'),content,'Reorder preserves original content nodes');
 w.document.getElementById('dashboardLayoutReset').click();
 assert.deepEqual(JSON.parse(w.localStorage.getItem(key)),ids,'Reset restores default panel order');
 w.document.getElementById('dashboardCustomize').click();assert.equal(layout.allowDragging,false);
 w.dispatchEvent(new w.Event('pagehide'));w.close();
}
console.log('PASS: real Dashboard Layout in seven locales, explicit edit mode, keyboard movement, reset, scoped storage and original event listeners preserved');
