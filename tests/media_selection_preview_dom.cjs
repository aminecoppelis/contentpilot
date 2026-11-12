const fs=require('fs'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {JSDOM,VirtualConsole}=require('../.cache/grid-tests/node_modules/jsdom');
execFileSync('venv/Scripts/python.exe',['-m','tests.render_editor_fixtures']);
const dom=new JSDOM(fs.readFileSync('.cache/editor-fr.html','utf8'),{url:'http://localhost/app/posts/view',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()}),w=dom.window;
w.t=k=>k;w.pgToast=()=>{};
const a={id:'a',media_type:'image',status:'ready',url:'https://example.com/a.jpg',media_role:'cover'},b={id:'b',media_type:'image',status:'ready',url:'https://example.com/b.jpg',media_role:null};
const idea={idea_id:'idea-0',media:[a,b],selected_media_id:null};w.__PG_VIEW={ideas:[idea],backgroundJobs:[],generationInProgress:false};
let resolveGallery,releaseSelection,delaySelection=false,failed=false,selected=[];
w.fetch=async(url,options)=>{
 if(url.startsWith('/app/posts/idea-media-json'))return new Promise(resolve=>{resolveGallery=()=>resolve({ok:true,json:async()=>({success:true,data:[{...a,media_role:'cover'},{...b,media_role:null}]})});});
 assert.equal(url,'/app/media-select');const payload=JSON.parse(options.body);selected.push(payload.media_id);
 if(delaySelection){delaySelection=false;await new Promise(resolve=>{releaseSelection=resolve;});}
 return {ok:!failed,json:async()=>({success:!failed,message:'Fixture failure'})};
};
w.eval(fs.readFileSync('static/js/consultation.js','utf8'));
const preview=w.document.querySelector('[data-live-post-media="0"]');assert(!preview.querySelector('img'),'No unrelated fallback image before selection');
(async()=>{
 const loading=w.loadIdeaMedia(0,1,null);await w.selectMedia('b',0,null);
 assert.equal(preview.querySelector('img').src,b.url);
 resolveGallery();await loading;
 assert.equal(idea.selected_media_id,'b','Stale gallery cannot restore the previous selection');
 assert.equal(preview.querySelector('img').src,b.url,'Preview uses the exact gallery URL of the chosen image');
 assert.equal(w.document.querySelectorAll('[data-media-selected-badge]').length,1);
 assert.equal(w.document.querySelector('[data-media-selected-badge]').closest('[data-media-id]').dataset.mediaId,'b');
 delaySelection=true;const first=w.selectMedia('a',0,null),second=w.selectMedia('b',0,null);await new Promise(r=>setTimeout(r,0));
 assert.deepEqual(selected,['b','a'],'Second selection waits for the first request');releaseSelection();await Promise.all([first,second]);
 assert.deepEqual(selected,['b','a','b']);assert.equal(idea.selected_media_id,'b');
 failed=true;await w.selectMedia('a',0,null);assert.equal(idea.selected_media_id,'b');assert.equal(preview.querySelector('img').src,b.url,'Failed selection preserves the confirmed image');
 w.close();console.log('PASS: selected image matches preview and gallery; stale refresh, rapid successive choices, no-selection placeholder and failed selection covered');
})().catch(e=>{console.error(e.stack?.slice(0,1600));w.close();process.exit(1);});
