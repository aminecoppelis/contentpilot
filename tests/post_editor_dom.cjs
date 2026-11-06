const fs=require('fs'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {JSDOM,VirtualConsole}=require('../.cache/grid-tests/node_modules/jsdom');
execFileSync('venv/Scripts/python.exe',['-m','tests.render_editor_fixtures']);
const engine=fs.readFileSync('.cache/grid-tests/ej2.min.js','utf8'),controller=fs.readFileSync('static/js/consultation.js','utf8'),editor=fs.readFileSync('static/js/post-editor.js','utf8');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(locale,sdk=true){
 const dom=new JSDOM(fs.readFileSync('.cache/editor-'+locale+'.html','utf8'),{url:'http://localhost/app/posts/view?request_id=request',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()});
 const w=dom.window,catalog=JSON.parse(fs.readFileSync('translations/'+locale+'.json','utf8')),calls=[];let scrolled;
 w.t=(key,params)=>{let s=catalog[key]||key;for(const k in params||{})s=s.replace('{'+k+'}',params[k]);return s;};w.__DIR=locale==='ar'?'rtl':'ltr';w.__LOCALE=locale;
 w.__PG_VIEW={requestId:'request',readOnly:false,ideas:[{idea_id:'idea-0',media:[]},{idea_id:'idea-1',media:[]}],backgroundJobs:[],generationInProgress:false,generationFailed:false};
 w.pgToast=()=>{};w.fetch=async(url)=>{calls.push(url);throw new Error('No real API calls in this test');};
 w.matchMedia=()=>({matches:false,addListener(){},removeListener(){}});
 w.HTMLElement.prototype.scrollIntoView=function(){scrolled=this.id;};w.HTMLElement.prototype.getBoundingClientRect=()=>({top:0,left:0,right:1000,bottom:500,width:1000,height:500,x:0,y:0});
 Object.defineProperty(w.HTMLElement.prototype,'offsetWidth',{get(){return 1000;}});Object.defineProperty(w.HTMLElement.prototype,'offsetHeight',{get(){return 60;}});
 if(sdk){w.eval(engine);if(process.env.TEST_LICENSE)w.ej.base.registerLicense(process.env.TEST_LICENSE);}
 w.eval(controller);w.eval(editor);
 w.setPostDisplayMode('editor',0);assert(w.document.querySelector('[data-post-workspace="0"]').classList.contains('mode-editor'));assert(w.document.querySelector('[data-post-workspace="1"]').classList.contains('mode-split'),'Changing one preview leaves the other unchanged');
 w.setPostDisplayMode('preview',1);assert(w.document.querySelector('[data-post-workspace="0"]').classList.contains('mode-editor'));assert.equal(w.localStorage.getItem('contentpilot-post-display:idea-0'),'editor');
 const host=w.document.getElementById('postVariantToolbar');
 if(sdk){assert(host.ej2_instances[0],'Real Toolbar initialized');host.querySelectorAll('.e-tbar-btn')[1].click();}
 else w.document.querySelectorAll('#postVariantFallback a')[1].click();
 assert.equal(scrolled,'card-1');assert.equal(w.document.activeElement.id,'card-1');
 const card=w.document.createElement('article');card.id='card-2';card.dataset.ideaIndex='2';card.dataset.ideaId='idea-2';card.innerHTML='<h2 id="post-title-2">New content</h2>';w.document.getElementById('posts-view-grid').appendChild(card);await wait(50);
 if(sdk)assert.equal(host.ej2_instances[0].items.length,3);else assert.equal(w.document.querySelectorAll('#postVariantFallback a').length,3);
 assert.equal(calls.length,0,'Navigation and preview mode changes never call generation or publication APIs');
 w.dispatchEvent(new w.Event('pagehide'));w.close();
}
(async()=>{for(const locale of ['fr','en','de','es','it','ru','ar'])await run(locale);await run('fr',false);console.log('PASS: full editor controller, real Toolbar, seven locales, per-card preview modes, scoped persistence, variant navigation, dynamically added cards and native fallback; no API calls');})().catch(e=>{console.error(e.stack?.slice(0,1800));process.exit(1);});
