const fs=require('fs'),assert=require('node:assert/strict');
const {JSDOM,VirtualConsole}=require('../.cache/grid-tests/node_modules/jsdom');
const {execFileSync}=require('node:child_process');
execFileSync('venv/Scripts/python.exe',['-m','tests.render_creation_fixtures']);
const engine=fs.readFileSync('.cache/grid-tests/ej2.min.js','utf8'),presentation=fs.readFileSync('static/js/creation-form.js','utf8'),controller=fs.readFileSync('static/js/form.js','utf8');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(locale,sdk=true){
 const dom=new JSDOM(fs.readFileSync('.cache/creation-'+locale+'.html','utf8'),{url:'http://localhost/app/posts/new',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()});
 const w=dom.window,catalog=JSON.parse(fs.readFileSync('translations/'+locale+'.json','utf8')),calls=[],toasts=[];
 w.t=k=>catalog[k]||k;w.__DIR=locale==='ar'?'rtl':'ltr';w.pgToast=msg=>toasts.push(msg);w.HTMLElement.prototype.scrollIntoView=function(){};
 w.matchMedia=()=>({matches:false,addListener(){},removeListener(){}});
 w.HTMLElement.prototype.getBoundingClientRect=()=>({top:0,left:0,right:900,bottom:500,width:900,height:500,x:0,y:0});
 function hidden(element){return element.classList.contains('e-content-hide')||element.classList.contains('e-hide')||element.style.display==='none';}
 Object.defineProperty(w.HTMLElement.prototype,'offsetWidth',{get(){return hidden(this)?0:900;}});Object.defineProperty(w.HTMLElement.prototype,'offsetHeight',{get(){return hidden(this)?0:500;}});
 w.fetch=async(url,options)=>{calls.push({url,payload:JSON.parse(options.body)});return {ok:false,status:503,json:async()=>({success:false,message:'Fixture error'})};};
 if(sdk){w.eval(engine);if(process.env.TEST_LICENSE)w.ej.base.registerLicense(process.env.TEST_LICENSE);}
 w.eval(presentation);w.eval(controller);await wait(80);
 const form=w.document.getElementById('ideasForm'),options=w.document.getElementById('creationOptions'),accordion=options.ej2_instances?.[0];
 if(sdk){assert(accordion,'Real Accordion initialized');assert.equal(options.querySelectorAll('.e-acrdn-header[aria-expanded="true"]').length,0,'Advanced settings start collapsed');}
 assert.equal(form.querySelectorAll('[name=content_domains]').length,10,'Default domains preserved while collapsed');
 assert.equal(form.querySelectorAll('[name=preferred_formats]').length,3);
 form.dispatchEvent(new w.Event('submit',{cancelable:true}));await wait(30);assert.equal(calls.length,0);assert.equal(w.document.activeElement.id,'subjectInput');
 w.document.getElementById('subjectInput').value='Content about solar panels';
 const domains=w.document.getElementById('contentDomainsSelect');while(domains.querySelector('.msTag button'))domains.querySelector('.msTag button').click();
 form.dispatchEvent(new w.Event('submit',{cancelable:true}));await wait(30);assert.equal(calls.length,0);
 if(sdk){assert.equal(options.querySelector('.e-acrdn-header').getAttribute('aria-expanded'),'true','Invalid targeting section is revealed; ancestors='+domains.parentElement.className+'; closest='+domains.closest('.e-acrdn-item')?.className+'; children='+[...options.children].map(e=>e.className).join('|')+'; active='+w.document.activeElement.id);}
 const domainInput=domains.querySelector('.msSearch');assert.equal(w.document.activeElement,domainInput);
 domainInput.value='Solar';domainInput.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
 const company=form.querySelector('[name=company]');company.value='Example company';
 form.querySelector('[name=post_count]').value='2';w.document.getElementById('themeInput').value='Use a practical tone';w.document.getElementById('useMacaronCheckbox').checked=false;
 if(sdk)accordion.expandItem(false);
 form.dispatchEvent(new w.Event('submit',{cancelable:true}));await wait(50);
 assert.equal(calls.length,1);assert.equal(calls[0].url,'/app/post-ideas-generate');const payload=calls[0].payload;
 assert.equal(payload.company,'Example company');assert.equal(payload.prompt,'Use a practical tone');assert.equal(payload.post_count,2);assert.equal(payload.use_macaron,false);assert.equal(payload.content_domains.length,1);assert.equal(payload.preferred_formats.length,3);
 assert.deepEqual(Object.keys(payload).sort(),['subject','prompt','commercial_objective','target_sector','language','constraints','post_count','company','website','solution','default_tags','content_domains','target_audience','preferred_formats','use_macaron'].sort());
 assert(!w.document.getElementById('submitBtn').disabled,'Failed generation allows retry');assert(!w.document.getElementById('loaderOverlay').classList.contains('isVisible'));assert.equal(company.value,'Example company');assert.equal(toasts.length,1);
 w.dispatchEvent(new w.Event('pagehide'));w.close();
}
(async()=>{for(const locale of ['fr','en','de','es','it','ru','ar'])await run(locale);await run('fr',false);console.log('PASS: real Accordion in seven locales, collapsed fields retain defaults and payload, invalid section revealed, focus restored, failed request retry and native fallback; no publication calls');})().catch(e=>{console.error(e.stack?.slice(0,1600));process.exit(1);});
