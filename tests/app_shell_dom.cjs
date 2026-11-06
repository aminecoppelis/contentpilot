const fs=require('fs'),assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('../.cache/grid-tests/node_modules/jsdom');
for(const sdk of [false,true]){
 const dom=new JSDOM('<html class="pg-nav-collapsed"><body><aside id="pgSidebar"><button id="pgSidebarToggle"></button><a class="active" href="/app/posts">Posts</a><a href="/app/networks">Networks</a></aside><div id="pgSidebarOverlay"></div><div class="main-content"><button class="pgMobileNavToggle"></button><nav id="pgBreadcrumbFallback"></nav><nav id="pgBreadcrumb" hidden></nav><script id="pgBreadcrumbItems" type="application/json">[{"text":"Home","url":"/app/dashboard"},{"text":"Posts","url":"/app/posts"},{"text":"Prepare post","url":""}]</script></div></body></html>',{url:'http://localhost/app/posts/view',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()});
 const w=dom.window;let mobile=false;
 w.matchMedia=()=>({matches:mobile,addListener(){},removeListener(){}});w.__DIR='ltr';
 if(sdk){w.eval(fs.readFileSync('.cache/grid-tests/ej2.min.js','utf8'));if(process.env.TEST_LICENSE)w.ej.base.registerLicense(process.env.TEST_LICENSE);}
 w.eval(fs.readFileSync('static/js/app-shell.js','utf8'));
 const sidebar=w.document.getElementById('pgSidebar'),desk=w.document.getElementById('pgSidebarToggle'),toggle=w.document.querySelector('.pgMobileNavToggle'),main=w.document.querySelector('.main-content');
 assert.equal(desk.getAttribute('aria-expanded'),'false');desk.click();assert(!w.document.documentElement.classList.contains('pg-nav-collapsed'));
 assert.equal(w.document.querySelector('.sidebar-item')?.getAttribute('aria-current')||sidebar.querySelector('a').getAttribute('aria-current'),'page');
 mobile=true;w.dispatchEvent(new w.Event('resize'));assert(sidebar.inert);
 toggle.focus();toggle.click();assert(main.inert);assert(!sidebar.inert);assert.equal(toggle.getAttribute('aria-expanded'),'true');
 const last=sidebar.querySelectorAll('a')[1];last.focus();last.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));assert.equal(w.document.activeElement,desk);
 desk.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert(!main.inert);assert(sidebar.inert);assert.equal(w.document.activeElement,toggle);
 toggle.click();mobile=false;w.dispatchEvent(new w.Event('resize'));assert(!sidebar.inert);assert(!main.inert);
 if(sdk){assert(w.document.getElementById('pgBreadcrumb').ej2_instances[0],'Real Breadcrumb initialized');assert(w.document.getElementById('pgBreadcrumbFallback').hidden);}
 else assert(!w.document.getElementById('pgBreadcrumbFallback').hidden);
 w.dispatchEvent(new w.Event('pagehide'));w.close();
}
console.log('PASS: real Syncfusion Breadcrumb, native fallback, sidebar persistence, mobile inert/focus trap, Escape and responsive transitions');
