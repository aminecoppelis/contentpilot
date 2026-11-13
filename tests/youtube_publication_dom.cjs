// Network responses are fixtures: no Google authorization or real publication.
const fs=require('fs'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {JSDOM,VirtualConsole}=require('../.cache/grid-tests/node_modules/jsdom');
execFileSync('venv/Scripts/python.exe',['-m','tests.render_editor_fixtures']);
async function run(mediaType){
 const dom=new JSDOM(fs.readFileSync('.cache/editor-fr.html','utf8'),{url:'http://localhost/app/posts/view',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()}),w=dom.window;
 const catalog=JSON.parse(fs.readFileSync('translations/fr.json','utf8'));w.t=k=>catalog[k]||k;w.pgToast=()=>{};
 const idea={idea_id:'idea-0',version_id:'version',title:'My video',media:mediaType?[{id:'media',media_type:mediaType,status:'ready',public_url:'https://example.com/video.mp4'}]:[],selected_media_id:mediaType?'media':null};
 w.__PG_VIEW={ideas:[idea],backgroundJobs:[],publicationJobs:[]};
 const account={id:'yt',provider:'youtube',platform:'youtube',service:'youtube',connection_provider:'google',is_active:true,display_name:'My channel'};
 let sent=null;
 w.fetch=async(url,options)=>{
  if(url==='/app/networks/publishable')return {ok:true,json:async()=>({success:true,data:{accounts:[account]}})};
  if(url==='/app/post-ideas-publish'){
   sent=JSON.parse(options.body);
   return {ok:true,json:async()=>({success:true,data:{results:[{platform:'youtube',status:'processing',publication_id:'pub'}]}})};
  }
  assert.equal(url,'/app/posts/publication-progress/pub');
  return {ok:true,json:async()=>({success:true,data:{status:'processing',upload_bytes:262144,upload_total_bytes:524288}})};
 };
 w.eval(fs.readFileSync('static/js/consultation.js','utf8'));await w.openPublishModal(0);
 const choices=[...w.document.querySelectorAll('.publishAccountOption')];assert(choices.length>0);
 if(mediaType!=='video'){assert(choices.every(b=>b.disabled));assert(w.document.getElementById('youtubeFields').hidden);}
 else{
  assert.equal(choices.length,2);assert(choices[0].textContent.includes(catalog['yt.video']));assert(choices[1].textContent.includes('Short'));
  choices[0].dispatchEvent(new w.MouseEvent('mousedown',{bubbles:true,cancelable:true}));
  assert(!w.document.getElementById('youtubeFields').hidden);
  // Changing the type keeps one upload target per channel.
  w.document.querySelector('.publishAccountSearch').dispatchEvent(new w.FocusEvent('focus'));
  w.document.querySelectorAll('.publishAccountOption')[1].dispatchEvent(new w.MouseEvent('mousedown',{bubbles:true,cancelable:true}));
  assert.equal(w.document.querySelectorAll('.publishAccountTag').length,1);
  w.document.getElementById('publishMode').value='now';
  w.document.getElementById('youtubeTitle').value='My video';
  w.document.getElementById('youtubeDescription').value='Description';
  w.document.getElementById('youtubeTags').value='tag one, tag two';
  w.document.getElementById('youtubeKids').value='no';
  w.savePostEdit=async()=>true;
  await w.confirmPublishModal();await new Promise(r=>setTimeout(r,0));
  assert(sent,'The existing publish endpoint receives YouTube');assert.equal(sent.media_id,'media');
  assert.equal(sent.targets.length,1);assert.equal(sent.targets[0].publish_content_type,'short');
  assert.deepEqual(sent.targets[0].youtube.tags,['tag one','tag two']);assert.equal(sent.targets[0].youtube.privacy,'private');
  const progress=w.document.querySelector('[data-youtube-progress] progress');assert(progress);assert.equal(progress.value/progress.max,.5);
 }
 w.close();
}
(async()=>{for(const mediaType of [null,'image','video'])await run(mediaType);console.log('PASS: YouTube channel, Video/Short choice, required media, metadata, existing publication endpoint and confirmed-byte progress (mocked network only)');})().catch(e=>{console.error(e.stack?.slice(0,1800));process.exit(1);});
