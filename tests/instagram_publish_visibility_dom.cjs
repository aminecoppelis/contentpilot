const fs=require('fs'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {JSDOM,VirtualConsole}=require('../.cache/grid-tests/node_modules/jsdom');
execFileSync('venv/Scripts/python.exe',['-m','tests.render_editor_fixtures']);
async function run(provider,mediaType){
 const dom=new JSDOM(fs.readFileSync('.cache/editor-fr.html','utf8'),{url:'http://localhost/app/posts/view',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()}),w=dom.window;
 const catalog=JSON.parse(fs.readFileSync('translations/fr.json','utf8'));w.t=k=>catalog[k]||k;w.pgToast=()=>{};
 const idea={idea_id:'idea-0',media:mediaType?[{id:'media',media_type:mediaType,status:'ready',public_url:'https://example.com/media'}]:[],selected_media_id:mediaType?'media':null};
 w.__PG_VIEW={ideas:[idea],backgroundJobs:[],generationInProgress:false};
 const account={id:'instagram-account',provider,platform:'instagram',service:provider==='buffer'?'instagram':'',connection_provider:provider==='buffer'?'buffer':'meta_direct',is_active:true,display_name:'Instagram test'};
 let reads=0;w.fetch=async(url,options)=>{assert.equal(url,'/app/networks/publishable');assert(!options.method||options.method==='GET');reads++;return {ok:true,json:async()=>({success:true,data:{accounts:[account]}})};};
 w.eval(fs.readFileSync('static/js/consultation.js','utf8'));await w.openPublishModal(0);
 const options=[...w.document.querySelectorAll('.publishAccountOption')];assert(options.length>0,'Connected Instagram remains visible without a selected media');
 assert(options.every(button=>button.textContent.includes('Instagram test')));
 if(!mediaType){assert.equal(options.length,1);assert(options[0].disabled);assert(options[0].textContent.includes(catalog['js.pub.media_none_selected']));assert(w.document.querySelector('.publishAccountSummary').textContent.includes(catalog['js.pub.media_none_selected']));}
 else assert(options.every(button=>!button.disabled),'Valid selected media enables compatible publication types');
 assert.equal(reads,1);w.close();
}
(async()=>{for(const provider of ['instagram','buffer'])for(const media of [null,'image','video'])await run(provider,media);console.log('PASS: Instagram direct and Buffer accounts stay visible without media, explain disabled state, and enable matching image/video targets; only mocked account reads, no publication requests');})().catch(e=>{console.error(e.stack?.slice(0,1400));process.exit(1);});
