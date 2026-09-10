/**
 * Page de consultation/édition d'un sujet — port des interactions du nœud
 * "Construire page consultation moderne" : édition inline du post avec
 * mise en forme Unicode (gras/italique/souligné), copie, régénération IA,
 * validation, carrousel de médias, lightbox, génération de média,
 * publication multi-comptes et génération d'idées supplémentaires.
 */
(function(){
  var WEBHOOK_BASE='/app';
  var VIEW=window.__PG_VIEW||{ideas:[],requestId:''};
  var currentActionIndex=null, currentAction='', currentMediaIndex=null, currentPublishIndex=null;
  var currentMediaMode='create', currentMediaTarget=null;

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function showToast(message,type){
    var c=document.getElementById('toastContainer');
    if(!c){ if(window.pgToast)window.pgToast(message,type); return; }
    var el=document.createElement('div');
    el.className='toast '+(type||'success'); el.textContent=String(message||'');
    c.appendChild(el);
    requestAnimationFrame(function(){el.classList.add('show');});
    setTimeout(function(){el.classList.remove('show');setTimeout(function(){el.remove();},220);},3800);
  }
  window.showToast=showToast;

  function ideaAt(i){ return (VIEW.ideas||[])[i]||{}; }
  function postBox(i){ return document.getElementById('copy-'+i); }

  /* ---------- Centre d’activité IA — parité V90 ---------- */
  var aiActivityJobs=new Map();
  function aiJobKey(job){return String(job&&job.id||'').trim();}
  function aiActiveJobs(){return Array.from(aiActivityJobs.values()).filter(function(job){return String(job.status||'processing')==='processing';});}
  function aiJobIcon(type){return type==='video'?'▶':(type==='image'?'▧':'✦');}
  function renderAiActivity(){
    var root=document.getElementById('pgAiActivity'),toggle=document.getElementById('pgAiActivityToggle'),panel=document.getElementById('pgAiActivityPanel'),list=document.getElementById('pgAiActivityList');
    if(!root||!toggle||!list)return;
    var jobs=Array.from(aiActivityJobs.values()),active=aiActiveJobs();
    if(!jobs.length){root.hidden=true;return;}
    root.hidden=false;
    var title=document.getElementById('pgAiActivityTitle'),subtitle=document.getElementById('pgAiActivitySubtitle'),count=document.getElementById('pgAiActivityCount');
    if(active.length){
      if(title)title.textContent='IA en cours · '+active.length+' tâche'+(active.length>1?'s':'');
      if(subtitle)subtitle.textContent=active.map(function(j){return j.label||'Traitement IA';}).slice(0,2).join(' · ');
      if(count)count.textContent=String(active.length);
    }else{
      var failed=jobs.filter(function(j){return j.status==='failed';});
      if(title)title.textContent=failed.length?'Activité IA · erreur':'Activité IA terminée';
      if(subtitle)subtitle.textContent=failed.length?(failed[0].message||'Une tâche a échoué.'):'Toutes les tâches sont terminées.';
      if(count)count.textContent=failed.length?'!':'✓';
    }
    list.innerHTML=jobs.slice(-8).map(function(job){
      var status=String(job.status||'processing'),statusLabel=status==='completed'?'Terminée':(status==='failed'?'Erreur':'En cours');
      return '<div class="pgAiJob '+esc(status)+'"><span class="pgAiJobIcon">'+esc(aiJobIcon(job.type))+'</span><span class="pgAiJobText"><b>'+esc(job.label||'Traitement IA')+'</b><small>'+esc(job.message||'Traitement côté serveur…')+'</small></span><span class="pgAiJobStatus">'+esc(statusLabel)+'</span></div>';
    }).join('');
    if(panel&&!active.length&&toggle.getAttribute('aria-expanded')!=='true')panel.hidden=true;
  }
  function updateAiJob(id,patch){
    id=String(id||'').trim();if(!id)return;
    var current=aiActivityJobs.get(id)||{id:id,status:'processing'};
    aiActivityJobs.set(id,Object.assign({},current,patch||{}));renderAiActivity();
  }
  function completeAiJob(id,message){updateAiJob(id,{status:'completed',message:message||'Terminé.'});setTimeout(function(){var j=aiActivityJobs.get(String(id));if(j&&j.status==='completed'){aiActivityJobs.delete(String(id));renderAiActivity();}},5000);}
  function failAiJob(id,message){updateAiJob(id,{status:'failed',message:message||'Le traitement a échoué.'});}
  window.pgAiActivity={updateJob:updateAiJob,completeJob:completeAiJob,failJob:failAiJob,hasActiveJobs:function(){return aiActiveJobs().length>0;}};
  (Array.isArray(VIEW.backgroundJobs)?VIEW.backgroundJobs:[]).forEach(function(job){if(aiJobKey(job))aiActivityJobs.set(aiJobKey(job),Object.assign({status:'processing'},job));});
  document.addEventListener('DOMContentLoaded',function(){
    var toggle=document.getElementById('pgAiActivityToggle'),panel=document.getElementById('pgAiActivityPanel'),close=document.getElementById('pgAiActivityClose');
    if(toggle&&panel)toggle.addEventListener('click',function(){var open=toggle.getAttribute('aria-expanded')==='true';toggle.setAttribute('aria-expanded',open?'false':'true');panel.hidden=open;});
    if(close&&panel&&toggle)close.addEventListener('click',function(){panel.hidden=true;toggle.setAttribute('aria-expanded','false');});
    renderAiActivity();
  });

  /* ---------- Mise en forme Unicode (gras / italique / souligné) ---------- */
  var UNICODE_MAPS={
    bold:{offsetUpper:0x1D400-65,offsetLower:0x1D41A-97,offsetDigit:0x1D7CE-48},
    italic:{offsetUpper:0x1D434-65,offsetLower:0x1D44E-97,offsetDigit:0}
  };
  function toUnicodeStyle(text,style){
    if(style==='underline'){
      return String(text||'').split('').map(function(ch){return ch+'\u0332';}).join('');
    }
    var map=UNICODE_MAPS[style];
    if(!map)return text;
    return String(text||'').split('').map(function(ch){
      var code=ch.charCodeAt(0);
      if(code>=65&&code<=90)return String.fromCodePoint(code+map.offsetUpper);
      if(code>=97&&code<=122)return String.fromCodePoint(code+map.offsetLower);
      if(map.offsetDigit&&code>=48&&code<=57)return String.fromCodePoint(code+map.offsetDigit);
      return ch;
    }).join('');
  }
  window.formatPostSelection=function(i,style){
    var box=postBox(i); if(!box)return false;
    var start=box.selectionStart, end=box.selectionEnd;
    if(start===end){ showToast(window.t('js.cons.select_text'),'info'); return false; }
    var selected=box.value.slice(start,end);
    var replaced=toUnicodeStyle(selected,style);
    box.value=box.value.slice(0,start)+replaced+box.value.slice(end);
    box.setSelectionRange(start,start+replaced.length);
    box.focus();
    window.markPostEdited(i);
    return false;
  };
  window.updateFormatToolbar=function(){ /* état visuel de la barre : sans effet requis */ };

  window.copyPost=async function(elementId,btn){
    var el=document.getElementById(elementId); if(!el)return false;
    try{
      await navigator.clipboard.writeText(el.value||el.textContent||'');
      showToast(window.t('js.cons.post_copied'),'success');
      if(btn){ var prev=btn.textContent; btn.textContent='✓'; setTimeout(function(){btn.textContent=prev;},1200); }
    }catch(e){ showToast(window.t('js.copy_failed'),'error'); }
    return false;
  };
  window.copyFullPost=window.copyPost;
  window.copyBox=window.copyPost;

  /* ---------- Sauvegarde automatique de l'édition ---------- */
  var saveTimers={};
  window.markPostEdited=function(i){
    var status=document.getElementById('post-edit-status-'+i);
    if(status)status.textContent='Modification non enregistrée…';
    clearTimeout(saveTimers[i]);
    saveTimers[i]=setTimeout(function(){ window.savePostEdit(i); },1200);
  };
  window.savePostEdit=async function(i){
    var box=postBox(i); var idea=ideaAt(i);
    if(!box||!idea.idea_id)return;
    var status=document.getElementById('post-edit-status-'+i);
    if(status)status.textContent='Enregistrement…';
    try{
      var r=await fetch(WEBHOOK_BASE+'/post-ideas-autosave',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({idea_id:idea.idea_id,field:'post_text',value:box.value})});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      if(status)status.textContent='Enregistré.';
      setTimeout(function(){ if(status&&status.textContent==='Enregistré.')status.textContent=''; },2200);
      return true;
    }catch(e){ if(status)status.textContent='Enregistrement impossible.'; return false; }
  };
  window.handlePostPaste=function(event,i){ setTimeout(function(){ window.markPostEdited(i); },0); };

  window.shareIdea=async function(i,btn){
    var idea=ideaAt(i);
    var url=location.origin+WEBHOOK_BASE+'/posts/view?'+(VIEW.readOnly?'':'request_id='+encodeURIComponent(VIEW.requestId||'')+'&')+
      'idea_id='+encodeURIComponent(idea.idea_id||'');
    try{ await navigator.clipboard.writeText(url); showToast(window.t('js.cons.link_copied'),'success'); }
    catch(e){ showToast(window.t('js.copy_failed'),'error'); }
    return false;
  };

  /* ---------- Modale d'action (Valider / Refuser / Régénérer / À valider) ---------- */
  var ACTION_LABELS={
    'Valider':{title:'Valider le post',desc:'Le post sera marqué comme prêt à publier.',confirm:'Valider',
      instructions:'Note de validation (optionnelle)'},
    'Refuser':{title:'Refuser le post',desc:'Le post sera marqué comme rejeté.',confirm:'Refuser',
      instructions:'Motif du refus (optionnel)'},
    'À valider':{title:'Demander une validation',desc:'Le post repassera en attente de validation.',
      confirm:'Demander',instructions:'Note (optionnelle)'},
    'Régénérer':{title:'Régénérer le post',desc:'Une nouvelle version sera créée, le format est conservé.',
      confirm:'Régénérer',instructions:'Instructions optionnelles'}
  };
  window.openActionModal=function(i,action){
    currentActionIndex=i; currentAction=action;
    var meta=ACTION_LABELS[action]||{title:action,desc:'',confirm:'Confirmer',instructions:'Instructions optionnelles'};
    document.getElementById('modalTitle').textContent=meta.title;
    document.getElementById('modalDescription').textContent=meta.desc;
    document.getElementById('modalConfirm').textContent=meta.confirm;
    document.getElementById('modalInstructionsLabel').textContent=meta.instructions;
    document.getElementById('modalInstructions').value='';
    document.getElementById('modalStatus').textContent='';
    var idea=ideaAt(i);
    document.getElementById('modalIdea').innerHTML='<b>'+esc(idea.title||'')+'</b>';
    document.getElementById('actionModal').classList.add('isVisible');
    return false;
  };
  window.closeActionModal=function(){
    document.getElementById('actionModal').classList.remove('isVisible'); return false;
  };
  window.confirmActionModal=async function(){
    if(currentActionIndex===null)return false;
    var idea=ideaAt(currentActionIndex);
    var instructions=document.getElementById('modalInstructions').value;
    var status=document.getElementById('modalStatus');
    var confirmBtn=document.getElementById('modalConfirm');
    var apiAction=currentAction==='Régénérer'?'regenerate':
      (currentAction==='Valider'?'validate':(currentAction==='Refuser'?'reject':'request_review'));
    confirmBtn.disabled=true; status.textContent='Traitement en cours…';
    try{
      var r=await fetch(WEBHOOK_BASE+'/post-ideas-action',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({idea_id:idea.idea_id,action:apiAction,instructions:instructions})});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      showToast(window.t('js.cons.action_applied'),'success');
      window.closeActionModal();
      setTimeout(function(){location.reload();},600);
    }catch(e){ status.textContent=e.message||'Action impossible.'; confirmBtn.disabled=false; }
    return false;
  };
  window.submitAction=window.confirmActionModal;

  /* ---------- Carrousel + lightbox (fallbacks déjà globaux dans l'original) ---------- */
  window.showCarouselMedia=function(index,pos){
    var items=Array.prototype.slice.call(document.querySelectorAll('[data-carousel-item="'+Number(index)+'"]'));
    if(!items.length)return false;
    var total=items.length;
    var next=((Number(pos)||0)%total+total)%total;
    items.forEach(function(el,i){ el.classList.toggle('active',i===next); });
    items.forEach(function(el){
      var c=el.querySelector('.mediaCarouselCounter');
      if(c)c.textContent=(next+1)+' / '+total;
    });
    return false;
  };
  window.moveCarouselMedia=function(index,delta){
    var items=Array.prototype.slice.call(document.querySelectorAll('[data-carousel-item="'+Number(index)+'"]'));
    if(!items.length)return false;
    var current=items.findIndex(function(el){return el.classList.contains('active');});
    if(current<0)current=0;
    return window.showCarouselMedia(Number(index),current+(Number(delta)||0));
  };
  window.closeMediaLightbox=function(){
    var root=document.getElementById('mediaLightbox');
    if(root)root.classList.remove('show');
    return false;
  };
  window.openMediaLightbox=function(index,pos){
    var item=document.querySelector('[data-carousel-item="'+Number(index)+'"][data-media-pos="'+Number(pos)+'"]');
    if(!item)return false;
    var img=item.querySelector('img'); var vid=item.querySelector('video');
    var root=document.getElementById('mediaLightbox');
    if(!root){
      root=document.createElement('div'); root.id='mediaLightbox'; root.className='lightboxOverlay';
      root.innerHTML='<div class="lightboxCard"><div class="lightboxActions">'+
        '<a id="mediaLightboxDownload" class="lightboxBtn" target="_blank" rel="noopener" download>Télécharger</a>'+
        '<button type="button" class="lightboxBtn lightboxClose" onclick="window.closeMediaLightbox()">×</button>'+
        '</div><div class="lightboxStage" id="mediaLightboxStage"></div></div>';
      root.addEventListener('click',function(e){ if(e.target===root)window.closeMediaLightbox(); });
      document.body.appendChild(root);
    }
    var stage=root.querySelector('#mediaLightboxStage');
    var dl=root.querySelector('#mediaLightboxDownload');
    root.classList.add('show');
    var src=img?(img.currentSrc||img.getAttribute('src')||''):(vid?(vid.currentSrc||vid.src||''):'');
    if(!src)return false;
    if(dl){ dl.href=src; dl.style.display='inline-flex'; }
    if(stage)stage.innerHTML=img
      ? '<img src="'+src.replace(/"/g,'&quot;')+'" alt="Média">'
      : '<video src="'+src.replace(/"/g,'&quot;')+'" controls autoplay playsinline preload="auto"></video>';
    return false;
  };

  function readyMediaItems(items){
    return (Array.isArray(items)?items:[]).filter(function(m){
      return String(m&&m.status||'ready').toLowerCase()==='ready' && String(m&&m.url||m&&m.public_url||m&&m.external_url||'').trim();
    }).map(function(m){
      var out=Object.assign({},m); out.url=String(out.url||out.public_url||out.external_url||'').trim(); return out;
    });
  }
  function mediaObjectMetadata(media){
    var value=media&&media.metadata;
    if(value&&typeof value==='object'&&!Array.isArray(value))return value;
    if(typeof value==='string'){try{var parsed=JSON.parse(value);return parsed&&typeof parsed==='object'?parsed:{};}catch(_e){}}
    return {};
  }
  function mediaKindLabel(media){return String(media&&media.media_type||'').toLowerCase()==='video'?'Vidéo':'Image';}
  function mediaByPos(i,pos){var items=readyMediaItems(ideaAt(i).media||[]);return items[Number(pos)]||null;}
  function mediaCarouselHtml(items,i){
    items=readyMediaItems(items);
    if(!items.length)return '<div class="mediaPlaceholder"><div><b>Aucun média exploitable</b><span>Les générations en erreur ou encore en attente ne sont pas comptées comme médias disponibles.</span></div></div>';
    var selectedId=String(ideaAt(i).selected_media_id||'');
    var selectedPos=items.findIndex(function(m){return String(m.id||'')===selectedId||String(m.media_role||'')==='cover';});
    var activePos=selectedPos>=0?selectedPos:0;
    var cards=items.map(function(m,pos){
      var id=esc(m.id||''), rawUrl=String(m.url||'').trim(), url=esc(rawUrl), isVideo=String(m.media_type||'').toLowerCase()==='video';
      var selected=String(m.media_role||'')==='cover'||selectedId===String(m.id||'');
      var proxy=isVideo?(WEBHOOK_BASE+'/posts/media-video.mp4?media_id='+encodeURIComponent(m.id||'')):rawUrl;
      var preview='<div class="mediaPreviewFrame" data-open-media-preview="1" data-media-index="'+i+'" data-media-pos="'+pos+'">'+
        '<div class="mediaPreviewOverlay"><button type="button" class="mediaCornerBtn" onclick="event.preventDefault();event.stopPropagation();window.openMediaLightbox('+i+','+pos+');return false" title="Ouvrir en grand" aria-label="Ouvrir en grand">□</button></div>'+
        (isVideo
          ? '<video controls playsinline preload="metadata" src="'+url+'" data-video-proxy-url="'+esc(proxy)+'"></video>'
          : '<img src="'+url+'" alt="Aperçu image" onclick="window.openMediaLightbox('+i+','+pos+')">')+
        '</div>';
      var selectBtn=VIEW.readOnly?'':(selected
        ? '<button type="button" class="mediaUiBtn selected" data-select-media-btn disabled aria-disabled="true">Sélectionné</button>'
        : '<button type="button" class="mediaUiBtn primary" data-select-media-btn onclick="event.preventDefault();event.stopPropagation();window.selectMedia(\''+id+'\','+i+',this);return false">Choisir ce média</button>');
      var modifyBtn=VIEW.readOnly?'':'<button type="button" class="mediaUiBtn" data-edit-media="1" onclick="event.preventDefault();event.stopPropagation();window.openMediaEditModal('+i+','+pos+');return false">Modifier</button>';
      var downloadBtn='<button type="button" class="mediaUiBtn" onclick="event.preventDefault();event.stopPropagation();window.downloadGalleryMedia('+i+','+pos+');return false">Télécharger</button>';
      var deleteBtn=VIEW.readOnly?'':'<button type="button" class="mediaUiBtn danger" onclick="event.preventDefault();event.stopPropagation();window.deleteMedia(\''+id+'\','+i+');return false">Supprimer</button>';
      var badge=selected?'<span class="status published" data-media-selected-badge>Sélectionné</span>':'';
      return '<div class="mediaCarouselItem '+(pos===activePos?'active ':'')+'" data-carousel-item="'+i+'" data-media-pos="'+pos+'" data-media-id="'+id+'" data-media-kind="'+(isVideo?'video':'image')+'">'+
        preview+'<div class="mediaCarouselMeta"><span>'+mediaKindLabel(m)+'</span><span class="mediaCarouselCounter">'+(pos+1)+' / '+items.length+'</span>'+badge+'</div>'+
        '<div class="mediaActionRow">'+selectBtn+modifyBtn+downloadBtn+deleteBtn+'</div></div>';
    }).join('');
    return '<div class="mediaCarouselShell" data-carousel-shell="'+i+'">'+
      (items.length>1?'<button type="button" class="carouselNav" onclick="event.preventDefault();window.moveCarouselMedia('+i+',-1);return false" aria-label="Média précédent">‹</button>':'<span></span>')+
      '<div class="mediaCarousel" id="media-carousel-'+i+'">'+cards+'</div>'+
      (items.length>1?'<button type="button" class="carouselNav" onclick="event.preventDefault();window.moveCarouselMedia('+i+',1);return false" aria-label="Média suivant">›</button>':'<span></span>')+'</div>';
  }
  function mediaSlotHeader(i){
    if(VIEW.readOnly)return '<div class="mediaHeader"><span class="mediaLabel">Médias</span></div>';
    return '<div class="mediaHeader"><span class="mediaLabel">Médias</span><div class="mediaHeaderActions">'+
      '<button type="button" class="mediaBtn" id="media-btn-inline-'+i+'" data-media-index="'+i+'" onclick="return window.openMediaModal('+i+')">Générer un média</button>'+
      '<button type="button" class="mediaDownload" onclick="importMedia('+i+')">Importer image</button></div></div>';
  }
  function mediaCollapsedHtml(i,count){
    count=Math.max(0,Number(count)||0);
    if(!count)return '<div class="mediaPlaceholder"><div><b>Aucun média généré</b><span>Génère plusieurs images ou vidéos, compare-les, puis choisis le média à publier.</span></div></div>';
    return '<div class="mediaPlaceholder" style="border:2px solid #93c5fd;background:linear-gradient(180deg,#eff6ff,#ffffff);padding:24px"><div style="width:100%;display:flex;flex-direction:column;align-items:center;gap:14px"><b style="font-size:16px">'+count+' média(s) disponible(s)</b><button type="button" class="mediaBtn mediaLoadBtn" data-load-idea-media="'+i+'" onclick="event.preventDefault();event.stopPropagation();window.loadIdeaMedia('+i+',1,this);return false">Voir les médias ('+count+')</button></div></div>';
  }
  function renderMediaCollapsed(i,count){
    var slot=document.getElementById('media-slot-'+i);if(slot)slot.innerHTML=mediaSlotHeader(i)+mediaCollapsedHtml(i,count);
  }
  async function refreshIdeaMediaCollapsed(i){
    var idea=ideaAt(i);if(!idea.idea_id)return [];
    var r=await fetch(WEBHOOK_BASE+'/posts/idea-media-json?idea_id='+encodeURIComponent(idea.idea_id),{cache:'no-store'});
    var d=await r.json().catch(function(){return {};});if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
    var items=readyMediaItems(d.data||[]);idea.media=items;idea.media_count=items.length;var cover=items.find(function(m){return String(m.media_role||'')==='cover';});if(cover)idea.selected_media_id=cover.id;renderMediaCollapsed(i,items.length);return items;
  }
  async function pollVideoMediaUntilFinished(i,mediaId,jobKey){
    jobKey=jobKey||('media-'+mediaId);var started=Date.now(),maxMs=45*60*1000,temporaryErrors=0;
    updateAiJob(jobKey,{id:jobKey,media_id:mediaId,idea_id:ideaAt(i).idea_id,type:'video',label:'Génération vidéo',status:'processing',message:'Vidéo en cours côté serveur…'});
    while(Date.now()-started<maxMs){
      try{
        var r=await fetch(WEBHOOK_BASE+'/post-ideas-video/status?media_id='+encodeURIComponent(mediaId),{cache:'no-store'});
        var d=await r.json().catch(function(){return {};});
        if(r.ok&&d.success!==false){
          var data=d.data||{},state=String(data.status||'running').toLowerCase();temporaryErrors=0;
          if(data.url||['done','ready','completed','complete','success','succeeded'].indexOf(state)>=0){
            var items=await refreshIdeaMediaCollapsed(i);completeAiJob(jobKey,'Vidéo prête · '+items.length+' média(s) disponible(s).');showToast('Vidéo prête. Clique sur « Voir les médias » pour l’afficher.','success');return data;
          }
          updateAiJob(jobKey,{status:'processing',message:'Génération vidéo · '+(state||'en cours')+'…'});
        }else if(r.status===404||r.status===422){
          var msg=d.message||d.error||'La génération vidéo a échoué.';failAiJob(jobKey,msg);showToast(msg,'error');return null;
        }else{temporaryErrors++;updateAiJob(jobKey,{status:'processing',message:'Synchronisation vidéo en attente…'});}
      }catch(e){temporaryErrors++;updateAiJob(jobKey,{status:'processing',message:'Synchronisation vidéo en attente…'});}
      await new Promise(function(resolve){setTimeout(resolve,temporaryErrors>2?10000:5000);});
    }
    failAiJob(jobKey,'Le suivi automatique a expiré. Recharge la page pour reprendre le suivi.');return null;
  }
  function applyLoadedMedia(i,items){
    var idea=ideaAt(i);items=readyMediaItems(items);idea.media=items;idea.media_count=items.length;
    var cover=items.find(function(m){return String(m.media_role||'')==='cover';});
    if(cover)idea.selected_media_id=cover.id;
    var slot=document.getElementById('media-slot-'+i);
    if(slot)slot.innerHTML=mediaSlotHeader(i)+mediaCarouselHtml(items,i);
    return items;
  }
  window.loadIdeaMedia=async function(i,_force,btn){
    var idea=ideaAt(i); if(!idea.idea_id)return false;
    var original=btn?btn.textContent:'Voir les médias';
    if(btn){ btn.disabled=true; btn.classList.add('loading'); btn.textContent='Chargement…'; }
    try{
      var r=await fetch(WEBHOOK_BASE+'/posts/idea-media-json?idea_id='+encodeURIComponent(idea.idea_id),{cache:'no-store'});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      var items=applyLoadedMedia(i,d.data||[]);
      if(!items.length){ showToast(window.t('js.cons.no_media'),'info'); return false; }
      showToast(items.length+' média(s) chargé(s).','success');
      return true;
    }catch(e){ showToast('Impossible de charger les médias : '+(e.message||e),'error'); return false; }
    finally{ if(btn&&document.body.contains(btn)){btn.disabled=false;btn.classList.remove('loading');btn.textContent=original;} }
  };

  window.selectMedia=async function(mediaId,i,clickedBtn){
    var idea=ideaAt(i);
    if(clickedBtn&&clickedBtn.dataset.loading==='1')return false;
    var original=clickedBtn?clickedBtn.textContent:'Choisir ce média';
    if(clickedBtn){clickedBtn.dataset.loading='1';clickedBtn.disabled=true;clickedBtn.classList.add('loading');clickedBtn.textContent='Sélection en cours…';}
    try{
      var r=await fetch(WEBHOOK_BASE+'/media-select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea_id:idea.idea_id,media_id:mediaId})});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||'Sélection impossible.');
      idea.selected_media_id=mediaId;
      (idea.media||[]).forEach(function(m){m.media_role=String(m.id)===String(mediaId)?'cover':null;});
      document.querySelectorAll('[data-carousel-item="'+Number(i)+'"]').forEach(function(item){
        var selected=String(item.getAttribute('data-media-id')||'')===String(mediaId);
        var btn=item.querySelector('[data-select-media-btn]');
        if(btn){
          btn.disabled=selected;btn.setAttribute('aria-disabled',selected?'true':'false');
          btn.classList.toggle('selected',selected);btn.classList.toggle('primary',!selected);
          btn.classList.remove('loading');delete btn.dataset.loading;btn.textContent=selected?'Sélectionné':'Choisir ce média';
        }
        var badge=item.querySelector('[data-media-selected-badge]');
        if(selected&&!badge){badge=document.createElement('span');badge.className='status published';badge.setAttribute('data-media-selected-badge','');badge.textContent='Sélectionné';item.querySelector('.mediaCarouselMeta')?.appendChild(badge);}
        else if(!selected&&badge)badge.remove();
      });
      showToast(window.t('js.cons.media_selected'),'success');
    }catch(e){
      if(clickedBtn){clickedBtn.disabled=false;clickedBtn.classList.remove('loading');delete clickedBtn.dataset.loading;clickedBtn.textContent=original;}
      showToast(e.message||window.t('js.cons.select_failed'),'error');
    }
    return false;
  };
  window.downloadGalleryMedia=function(i,pos){
    var media=mediaByPos(i,pos);if(!media)return false;
    var item=document.querySelector('[data-carousel-item="'+Number(i)+'"][data-media-pos="'+Number(pos)+'"]');
    var el=item&&(item.querySelector('img')||item.querySelector('video'));
    var url=String(media.url||media.public_url||media.external_url||(el&&(el.currentSrc||el.src))||'').trim();
    if(!url){showToast(window.t('js.cons.no_download'),'error');return false;}
    var a=document.createElement('a');a.href=url;a.download=String(media.file_name||('media-'+(Number(pos)+1)));a.target='_blank';a.rel='noopener';
    document.body.appendChild(a);a.click();a.remove();return false;
  };
  window.openMediaEditModal=function(i,pos){
    var target=mediaByPos(i,pos);if(!target){showToast(window.t('js.cons.media_not_found'),'error');return false;}
    currentMediaMode='edit';currentMediaTarget=target;
    return window.openMediaModal(i,String(target.media_type||'').toLowerCase()==='video'?'video':'image',{mode:'edit',target:target});
  };
  window.deleteMedia=async function(mediaId,i){
    if(!(await window.pgConfirm(window.t('js.cons.confirm_delete_media'),{danger:true,confirmText:window.t('js.delete')})))return false;
    try{
      var r=await fetch(WEBHOOK_BASE+'/media-delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({media_id:mediaId})});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||'Suppression impossible.');
      showToast(window.t('js.cons.media_deleted'),'success');
      await window.loadIdeaMedia(i,1,null);
    }catch(e){ showToast(e.message||window.t('js.delete_failed'),'error'); }
    return false;
  };

  /* ---------- Génération de média — parité du modal n8n V90 ---------- */
  var mediaInspirationDataUrl='';
  var mediaFirstFrameDataUrl='';
  var mediaFirstFrameGeneratedUrl='';
  var mediaStyleState={image:[],video:[],firstframe:[]};
  var IMAGE_STYLES=[
    ['linkedin_pro','LinkedIn pro'],['instagram_impact','Instagram impact'],['illustration_minimaliste','Illustration minimaliste'],
    ['illustration_b2b','Illustration B2B moderne'],['mockup_saas','Mockup SaaS'],['photo_realiste','Photo réaliste professionnelle'],
    ['infographie','Infographie claire'],['isometrique','Illustration isométrique'],['flat_design','Flat design'],['3d','Visuel 3D premium'],
    ['3d_clean','3D clean'],['cover_linkedin','Cover LinkedIn professionnelle'],['visuel_reel','Visuel vertical Reel / Story'],
    ['avatar','Avatar'],['objet_anime','Objet animé']
  ];
  var VIDEO_STYLES=[
    ['demo_produit','Démo produit'],['video_explicative','Vidéo explicative'],['avant_apres','Avant / Après'],
    ['storytelling_court','Storytelling court'],['motion_design','Motion design'],['video_realiste','Vidéo réaliste'],
    ['avatar','Avatar'],['objet_anime','Objet animé']
  ];
  var ASPECT_DESCRIPTIONS={
    '4:5':'Fil LinkedIn / Instagram · recommandé pour les images','1:1':'Carré polyvalent','16:9':'Paysage / couverture','9:16':'Reel / Story · recommandé pour les vidéos verticales'
  };
  function createMiniMultiSelect(id,options,stateKey){
    var mount=document.getElementById(id);if(!mount)return;
    mount.innerHTML='<div class="miniMultiBox"><div class="miniMultiTags"></div><input type="text" class="miniMultiInput" placeholder="Rechercher ou ajouter..." autocomplete="off"></div><div class="miniMultiOptions"></div>';
    var tags=mount.querySelector('.miniMultiTags'),input=mount.querySelector('.miniMultiInput'),opts=mount.querySelector('.miniMultiOptions');
    function render(){
      tags.innerHTML='';mediaStyleState[stateKey].forEach(function(v){
        var label=(options.find(function(o){return o[0]===v;})||[v,v])[1];var tag=document.createElement('span');tag.className='miniMultiTag';
        tag.innerHTML='<span></span><button type="button" aria-label="Retirer">×</button>';tag.querySelector('span').textContent=label;
        tag.querySelector('button').onclick=function(){mediaStyleState[stateKey]=mediaStyleState[stateKey].filter(function(x){return x!==v;});render();};tags.appendChild(tag);
      });renderOptions();
    }
    function add(value){value=String(value||'').trim();if(!value)return;if(!mediaStyleState[stateKey].includes(value))mediaStyleState[stateKey].push(value);input.value='';render();}
    function renderOptions(){var q=input.value.trim().toLowerCase();opts.innerHTML='';var rows=options.filter(function(o){return !mediaStyleState[stateKey].includes(o[0])&&(!q||o[1].toLowerCase().includes(q)||o[0].includes(q));});
      rows.slice(0,15).forEach(function(o){var b=document.createElement('button');b.type='button';b.className='miniMultiOption';b.textContent=o[1];b.onmousedown=function(e){e.preventDefault();add(o[0]);};opts.appendChild(b);});
      if(q&&!rows.some(function(o){return o[1].toLowerCase()===q||o[0]===q;})){var b=document.createElement('button');b.type='button';b.className='miniMultiOption';b.textContent='Ajouter : '+input.value.trim();b.onmousedown=function(e){e.preventDefault();add(input.value.trim());};opts.prepend(b);}
    }
    input.onfocus=function(){renderOptions();opts.classList.add('isOpen');};input.oninput=function(){renderOptions();opts.classList.add('isOpen');};
    input.onblur=function(){setTimeout(function(){opts.classList.remove('isOpen');},150);};input.onkeydown=function(e){if(e.key==='Enter'){e.preventDefault();var first=opts.querySelector('.miniMultiOption');if(first)first.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}));else add(input.value);}};
    mount.querySelector('.miniMultiBox').onclick=function(){input.focus();};render();
  }
  function syncAspectPicker(selectId){
    var select=document.getElementById(selectId);var picker=document.querySelector('[data-aspect-select="'+selectId+'"]');if(!select||!picker)return;
    var value=select.value;var label=picker.querySelector('[data-aspect-current-label]');var desc=picker.querySelector('[data-aspect-current-description]');
    if(label)label.textContent=value;if(desc)desc.textContent=ASPECT_DESCRIPTIONS[value]||'Format';
    picker.querySelectorAll('[data-aspect-value]').forEach(function(b){b.classList.toggle('isSelected',b.getAttribute('data-aspect-value')===value);});
  }
  function bindAspectPickers(){
    document.querySelectorAll('[data-aspect-select]').forEach(function(picker){if(picker.__bound)return;picker.__bound=true;var id=picker.getAttribute('data-aspect-select');
      picker.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-aspect-value]');if(!b)return;e.preventDefault();var select=document.getElementById(id);if(select){select.value=b.getAttribute('data-aspect-value');syncAspectPicker(id);}picker.removeAttribute('open');});syncAspectPicker(id);});
  }
  function selectedMediaType(){return (document.querySelector('input[name="media_type"]:checked')||{}).value||'image';}
  function syncQualityLabels(){
    var type=selectedMediaType(),q=document.getElementById('mediaQuality'),help=document.getElementById('mediaQualityHelp');if(!q)return;
    var cur=q.value==='haute'?'haute':'standard';
    if(type==='video'){q.options[0].textContent='Standard (480p)';q.options[1].textContent='Haute (720p)';if(help)help.textContent='Grok Imagine Video : Standard = 480p ; Haute = 720p.';}
    else if(document.getElementById('imageModel').value==='x-ai/grok-imagine-image-quality'){q.options[0].textContent='Standard (1K)';q.options[1].textContent='Haute (2K)';if(help)help.textContent='Grok Imagine Image Quality : Standard = 1K ; Haute = 2K.';}
    else{q.options[0].textContent='Standard (1K)';q.options[1].textContent='Haute (1K HQ)';if(help)help.textContent='GPT-5 Image Mini : Standard = 1K ; Haute = 1K HQ.';}q.value=cur;
  }
  function populateFirstFrames(i){
    var idea=ideaAt(i),picker=document.getElementById('videoFirstFrameCarouselImage');if(!picker)return;
    picker.innerHTML='';
    var images=readyMediaItems(idea.media||[]).filter(function(m){return String(m.media_type||'').toLowerCase()==='image';});
    if(!images.length){var empty=document.createElement('option');empty.value='';empty.textContent='Aucune image disponible dans le carrousel';picker.appendChild(empty);picker.disabled=true;}
    else{picker.disabled=false;images.forEach(function(m,pos){var o=document.createElement('option');o.value=m.url;o.textContent='Image '+(pos+1)+(m.file_name?' · '+m.file_name:'');picker.appendChild(o);});}
    var source=document.getElementById('videoFirstFrameSource');if(source)source.value='none';
    var status=document.getElementById('videoFirstFrameStatus');if(status)status.textContent='Aucune première frame active.';
    updateVideoFirstFrameUi();
  }
  function syncFirstFrameQualityLabels(){
    var q=document.getElementById('videoFirstFrameQuality'),model=document.getElementById('videoFirstFrameModel'),help=document.getElementById('videoFirstFrameQualityHelp');if(!q||!model)return;
    var cur=q.value==='haute'?'haute':'standard';
    if(model.value==='x-ai/grok-imagine-image-quality'){q.options[0].textContent='Standard (1K)';q.options[1].textContent='Haute (2K)';if(help)help.textContent='Grok Imagine Image Quality : Standard = 1K ; Haute = 2K.';}
    else{q.options[0].textContent='Standard (1K)';q.options[1].textContent='Haute (1K HQ)';if(help)help.textContent='GPT-5 Image Mini : Standard = 1K ; Haute = 1K HQ.';}q.value=cur;
  }
  function updateVideoFirstFrameUi(){
    var source=document.getElementById('videoFirstFrameSource'),wrap=document.getElementById('videoFirstFrameCarouselPickerWrap'),upload=document.getElementById('videoFirstFrameUploadBtn'),gen=document.getElementById('videoFirstFrameGenerateOptions'),preview=document.getElementById('videoFirstFramePreview'),status=document.getElementById('videoFirstFrameStatus');
    if(!source)return;var value=source.value||'none';if(wrap)wrap.style.display=value==='selected_image'?'block':'none';if(upload)upload.style.display=value==='upload'?'inline-flex':'none';if(gen)gen.style.display=value==='generate_image'?'block':'none';
    if(value==='generate_image'){createMiniMultiSelect('videoFirstFrameStyleSelect',IMAGE_STYLES,'firstframe');syncFirstFrameQualityLabels();}
    var url='';if(value==='selected_image')url=document.getElementById('videoFirstFrameCarouselImage')?.value||'';else if(value==='upload')url=mediaFirstFrameDataUrl;else if(value==='generate_image')url=mediaFirstFrameGeneratedUrl;
    if(preview)preview.innerHTML=url?'<img src="'+esc(url)+'" alt="Première frame vidéo">':'';
    if(status)status.textContent=url?'Première frame active. Elle sera utilisée pour ancrer la vidéo.':'Aucune première frame active.';
  }
  function toggleMediaOptions(){
    var type=selectedMediaType();document.querySelectorAll('#modalMediaType .mediaTypeOption').forEach(function(l){var r=l.querySelector('input');l.classList.toggle('active',!!(r&&r.checked));});
    document.getElementById('mediaModalBox').classList.toggle('videoMode',type==='video');
    ['mediaInspirationField','imageModelField','imageStyleField','imageAspectField','mediaInstructionsField'].forEach(function(id){var e=document.getElementById(id);if(e)e.style.display=type==='image'?'block':'none';});
    var v=document.getElementById('videoOptions');if(v)v.style.display=type==='video'?'block':'none';syncQualityLabels();if(type==='video')updateVideoFirstFrameUi();
    var btn=document.getElementById('mediaModalConfirm');if(btn){btn.textContent=type==='video'?'Générer la vidéo':'Générer l’image';btn.classList.toggle('ok',type==='video');}
  }
  window.openMediaModal=function(i,forcedType,options){
    options=options&&typeof options==='object'?options:{};
    currentMediaIndex=Number(i);
    if(options.mode==='edit'){currentMediaMode='edit';currentMediaTarget=options.target||currentMediaTarget||null;}else if(currentMediaMode!=='edit'){currentMediaMode='create';currentMediaTarget=null;}
    var target=currentMediaMode==='edit'?currentMediaTarget:null;
    var metadata=mediaObjectMetadata(target||{});
    mediaInspirationDataUrl='';mediaFirstFrameDataUrl='';mediaFirstFrameGeneratedUrl='';mediaStyleState.image=[];mediaStyleState.video=[];mediaStyleState.firstframe=[];
    document.getElementById('mediaModalStatus').textContent='';document.getElementById('mediaModalStatus').className='modalStatus';
    document.getElementById('mediaInstructions').value='';document.getElementById('modalVideoScenarioText').value='';
    document.getElementById('mediaInspirationStatus').textContent='Aucune inspiration importée. Clique sur « Importer inspiration » pour ajouter une image de référence à envoyer à l’IA.';
    document.getElementById('imageModel').value='openai/gpt-5-image-mini';document.getElementById('mediaQuality').value='standard';document.getElementById('videoDuration').value='6';document.getElementById('videoFirstFrameModel').value='openai/gpt-5-image-mini';document.getElementById('videoFirstFrameQuality').value='standard';document.getElementById('videoFirstFrameInstructions').value='';
    document.getElementById('imageAspect').value='4:5';document.getElementById('videoAspect').value='9:16';
    var targetType=target&&String(target.media_type||'').toLowerCase()==='video'?'video':'image';
    var requested=(forcedType==='video'||forcedType==='image')?forcedType:(target?targetType:'image');
    if(target){
      var savedModel=String(metadata.image_model||'openai/gpt-5-image-mini');if(['openai/gpt-5-image-mini','x-ai/grok-imagine-image-quality'].includes(savedModel))document.getElementById('imageModel').value=savedModel;
      document.getElementById('mediaQuality').value=String(metadata.quality||'standard').toLowerCase()==='haute'?'haute':'standard';
      var aspect=String(metadata.aspect_ratio||'');if(requested==='video'&&['9:16','16:9'].includes(aspect))document.getElementById('videoAspect').value=aspect;if(requested==='image'&&['4:5','1:1','16:9'].includes(aspect))document.getElementById('imageAspect').value=aspect;
      var styles=String(metadata.visual_style||'').split(',').map(function(v){return v.trim();}).filter(Boolean);mediaStyleState[requested]=styles;
      if(requested==='video'){document.getElementById('videoDuration').value=String([4,6,8,10,12,15].includes(Number(metadata.duration))?Number(metadata.duration):6);document.getElementById('modalVideoScenarioText').value=String(metadata.user_instructions||target.scenario_text||target.prompt||'');}
      else{document.getElementById('mediaInstructions').value=String(metadata.user_instructions||'');mediaInspirationDataUrl=String(target.url||'');document.getElementById('mediaInspirationStatus').textContent='Image actuelle utilisée comme référence pour la modification. Tu peux importer une autre inspiration pour la remplacer.';}
    }
    document.querySelectorAll('input[name="media_type"]').forEach(function(r){r.checked=r.value===requested;r.disabled=!!target&&r.value!==requested;var label=r.closest('.mediaTypeOption');if(label)label.style.opacity=r.disabled?'0.45':'1';});
    var idea=ideaAt(i);document.getElementById('mediaModalIdea').innerHTML='<b>#'+(Number(i)+1)+' · '+esc(idea.post_title||idea.title||'Post')+'</b><br><span>'+esc(idea.recommended_format||'post')+'</span>';
    var title=document.getElementById('mediaModalTitle'),desc=document.getElementById('mediaModalDescription');
    if(title)title.textContent=target?'Modifier un média':'Générer un média';
    if(desc)desc.textContent=target?'Les paramètres du média sont préremplis. Modifie uniquement ce qui est nécessaire puis génère une nouvelle version.':'Création d’un nouveau média : pour une vidéo, écris une instruction simple, un scénario complet, utilise l’aide facultative, ou laisse le champ vide pour partir du post.';
    createMiniMultiSelect('imageStyleSelect',IMAGE_STYLES,'image');createMiniMultiSelect('videoStyleSelect',VIDEO_STYLES,'video');bindAspectPickers();populateFirstFrames(i);toggleMediaOptions();
    var confirm=document.getElementById('mediaModalConfirm');if(confirm&&target)confirm.textContent=requested==='video'?'Modifier la vidéo':'Modifier l’image';
    document.getElementById('mediaModal').classList.add('isVisible');return false;
  };
  window.closeMediaModal=function(){document.getElementById('mediaModal').classList.remove('isVisible');currentMediaIndex=null;currentMediaMode='create';currentMediaTarget=null;document.querySelectorAll('input[name="media_type"]').forEach(function(r){r.disabled=false;var label=r.closest('.mediaTypeOption');if(label)label.style.opacity='1';});return false;};
  document.addEventListener('change',function(e){if(e.target&&e.target.name==='media_type')toggleMediaOptions();if(e.target&&e.target.id==='imageModel')syncQualityLabels();if(e.target&&e.target.id==='videoFirstFrameModel')syncFirstFrameQualityLabels();if(e.target&&['videoFirstFrameSource','videoFirstFrameCarouselImage'].includes(e.target.id))updateVideoFirstFrameUi();});
  window.chooseMediaInspiration=function(){var f=document.getElementById('mediaInspirationFile');if(f)f.click();return false;};
  document.addEventListener('change',function(e){if(!e.target||e.target.id!=='mediaInspirationFile')return;var file=e.target.files&&e.target.files[0];if(!file)return;if(!String(file.type||'').startsWith('image/')){showToast('Choisis une image.','error');return;}if(file.size>12*1024*1024){showToast('Image trop volumineuse (12 Mo maximum).','error');return;}var reader=new FileReader();reader.onload=function(){mediaInspirationDataUrl=String(reader.result||'');document.getElementById('mediaInspirationStatus').textContent='Inspiration importée : '+file.name+'. Elle sera envoyée uniquement comme référence à l’IA.';};reader.onerror=function(){showToast('Lecture de l’image impossible.','error');};reader.readAsDataURL(file);});
  window.importVideoFirstFrame=function(){
    if(currentMediaIndex===null)return false;var input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.style.display='none';document.body.appendChild(input);
    input.onchange=function(){var file=input.files&&input.files[0];input.remove();if(!file)return;if(!String(file.type||'').startsWith('image/')){showToast('Import impossible. Utilise une image PNG/JPG/WEBP.','error');return;}if(file.size>25*1024*1024){showToast('Image trop lourde. Limite : 25 Mo.','error');return;}var reader=new FileReader();reader.onload=function(){mediaFirstFrameDataUrl=String(reader.result||'');mediaFirstFrameGeneratedUrl='';updateVideoFirstFrameUi();showToast('Première frame importée.','success');};reader.onerror=function(){showToast('Impossible de lire cette image.','error');};reader.readAsDataURL(file);};input.click();return false;
  };
  window.generateVideoFirstFrameImage=async function(){
    if(currentMediaIndex===null)return false;var styles=mediaStyleState.firstframe||[],status=document.getElementById('mediaModalStatus'),btn=document.getElementById('videoFirstFrameGenerateBtn');if(!styles.length){status.textContent='Choisis au moins un style d’image de première frame.';status.className='modalStatus error';return false;}
    var i=currentMediaIndex,idea=ideaAt(i),aspect=document.getElementById('videoAspect').value||'9:16',instructions=document.getElementById('videoFirstFrameInstructions').value||'';
    var prompt=['Créer une image de première frame professionnelle pour la vidéo suivante.',ideaContext(i),'Style demandé : '+styles.join(', ')+'.','Format final obligatoire : '+aspect+'.',instructions?('Instructions utilisateur : '+instructions):'','La composition doit être stable, sans étirement, et préparer visuellement la première seconde de la vidéo.'].filter(Boolean).join('\n\n');
    if(btn)btn.disabled=true;status.textContent='Génération de la première frame…';status.className='modalStatus show';
    try{var r=await fetch(WEBHOOK_BASE+'/post-ideas-image',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea_id:idea.idea_id,prompt:prompt,aspect_ratio:aspect,quality:document.getElementById('videoFirstFrameQuality').value,image_model:document.getElementById('videoFirstFrameModel').value,visual_style:styles.join(', ')})});var d=await r.json().catch(function(){return {};});if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));var url=String((d.data||{}).url||'').trim();if(!url)throw new Error('La première frame générée n’a pas d’URL exploitable.');mediaFirstFrameGeneratedUrl=url;mediaFirstFrameDataUrl='';document.getElementById('videoFirstFrameSource').value='generate_image';updateVideoFirstFrameUi();status.textContent='Première frame générée. Elle sera utilisée automatiquement pour la vidéo.';status.className='modalStatus show';await window.loadIdeaMedia(i,1,null);}
    catch(e){status.textContent=e.message||'Génération de la première frame impossible.';status.className='modalStatus error';}finally{if(btn)btn.disabled=false;}return false;
  };
  function ideaContext(i){var idea=ideaAt(i);return [idea.post_title||idea.title,idea.full_text,idea.summary,idea.business_problem_solved,idea.ai_or_software_solution,idea.concrete_application_example].filter(Boolean).join('\n\n');}
  function buildMediaPrompt(i,type){
    var idea=ideaAt(i),styles=mediaStyleState[type]||[],instructions=type==='video'?document.getElementById('modalVideoScenarioText').value:document.getElementById('mediaInstructions').value;
    var aspect=type==='video'?document.getElementById('videoAspect').value:document.getElementById('imageAspect').value;
    var base=type==='video'?'Créer une vidéo B2B professionnelle fidèle au post suivant :':'Créer une image B2B professionnelle fidèle au post suivant :';
    return [base,ideaContext(i),'Style demandé : '+styles.join(', ')+'.','Format final obligatoire : '+aspect+'.',instructions?('Instructions utilisateur : '+instructions):'',type==='image'?'Éviter le texte visible dans l’image sauf nécessité explicite. Garder le sujet entièrement visible avec des marges de sécurité.':'Les 0 à 2 premières secondes doivent contenir un hook visuel clair. Garder une scène cohérente, stable et professionnelle.'].filter(Boolean).join('\n\n');
  }
  window.generateMediaInstructionsWithAI=async function(){
    if(currentMediaIndex===null)return false;var type=selectedMediaType();var btn=document.getElementById(type==='video'?'modalRegenerateScenarioBtn':'mediaGeneratePromptBtn');var status=document.getElementById('mediaModalStatus');if(btn)btn.disabled=true;status.textContent='Génération des instructions avec l’IA…';status.className='modalStatus show';
    try{var r=await fetch(WEBHOOK_BASE+'/post-ideas-media-assist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea_id:ideaAt(currentMediaIndex).idea_id,media_type:type,aspect_ratio:type==='video'?document.getElementById('videoAspect').value:document.getElementById('imageAspect').value,styles:mediaStyleState[type],current_instructions:type==='video'?document.getElementById('modalVideoScenarioText').value:document.getElementById('mediaInstructions').value,duration:Number(document.getElementById('videoDuration').value||6)})});var d=await r.json().catch(function(){return {};});if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));var text=String((d.data||{}).instructions||'').trim();if(!text)throw new Error('Aucune instruction générée.');var field=document.getElementById(type==='video'?'modalVideoScenarioText':'mediaInstructions');field.value=text;field.dispatchEvent(new Event('input',{bubbles:true}));status.textContent='Instructions générées. Tu peux les modifier avant de lancer le média.';status.className='modalStatus show';}
    catch(e){status.textContent=e.message||'Génération des instructions impossible.';status.className='modalStatus error';}finally{if(btn)btn.disabled=false;}return false;
  };
  window.confirmMediaModal=async function(){
    if(currentMediaIndex===null)return false;var i=currentMediaIndex,idea=ideaAt(i),type=selectedMediaType(),status=document.getElementById('mediaModalStatus'),loader=document.getElementById('mediaLoader'),confirm=document.getElementById('mediaModalConfirm');var styles=mediaStyleState[type]||[];
    if(!styles.length){status.textContent='Choisis au moins un style '+(type==='video'?'de vidéo':'d’image')+'.';status.className='modalStatus error';return false;}
    var aspect=type==='video'?document.getElementById('videoAspect').value:document.getElementById('imageAspect').value;
    var rawInstructions=type==='video'?(document.getElementById('modalVideoScenarioText').value||''):(document.getElementById('mediaInstructions').value||'');
    var payload={idea_id:idea.idea_id,prompt:buildMediaPrompt(i,type),aspect_ratio:aspect,quality:document.getElementById('mediaQuality').value,visual_style:styles.join(', '),user_instructions:rawInstructions};
    if(currentMediaMode==='edit'&&currentMediaTarget)payload.edit_source_media_id=String(currentMediaTarget.id||'');
    if(type==='image'){payload.image_model=document.getElementById('imageModel').value;if(mediaInspirationDataUrl)payload.image_refs=[mediaInspirationDataUrl];}
    else{payload.video_model='x-ai/grok-imagine-video';payload.duration=Number(document.getElementById('videoDuration').value||6);payload.scenario=rawInstructions;var ffSource=document.getElementById('videoFirstFrameSource').value,ff='';if(ffSource==='selected_image')ff=document.getElementById('videoFirstFrameCarouselImage').value||'';else if(ffSource==='upload')ff=mediaFirstFrameDataUrl;else if(ffSource==='generate_image')ff=mediaFirstFrameGeneratedUrl;if(ff)payload.first_frame_url=ff;}
    status.textContent='Génération en cours…';status.className='modalStatus show';if(loader)loader.classList.add('show');if(confirm)confirm.disabled=true;
    try{var endpoint=type==='video'?'/post-ideas-video':'/post-ideas-image';var r=await fetch(WEBHOOK_BASE+endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});var d=await r.json().catch(function(){return {};});if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));var created=d.data||{};showToast(type==='video'?'Génération vidéo lancée en arrière-plan.':'Image générée.','success');window.closeMediaModal();if(type==='image')await window.loadIdeaMedia(i,1,null);else if(created.media_id){var jobKey='media-'+String(created.media_id);pollVideoMediaUntilFinished(i,String(created.media_id),jobKey);}}
    catch(e){status.textContent=e.message||'Génération impossible.';status.className='modalStatus error';}
    finally{if(loader)loader.classList.remove('show');if(confirm)confirm.disabled=false;}return false;
  };
  window.importMedia=async function(i){
    var url=prompt('URL HTTPS publique de l’image à importer :');if(!url)return false;var idea=ideaAt(i);
    try{var r=await fetch(WEBHOOK_BASE+'/post-ideas-media-import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea_id:idea.idea_id,image_url:url})});var d=await r.json().catch(function(){return {};});if(!r.ok||d.success===false)throw new Error(d.message||'Import impossible.');showToast('Image importée.','success');await window.loadIdeaMedia(i,1,null);}catch(e){showToast(e.message||'Import impossible.','error');}return false;
  };

  /* ---------- Publication — parité du modal n8n V90 ---------- */
  var publishAccountsCache={loaded:false,loading:null,items:[]};
  var publishTargetSelectionState=new Set();

  function toDatetimeLocalValue(date){
    var d=new Date(date);d.setSeconds(0,0);
    function pad(n){return String(n).padStart(2,'0');}
    return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes());
  }
  function minScheduledDate(){
    var d=new Date(Date.now()+2*60*1000);d.setMinutes(Math.ceil(d.getMinutes()/5)*5,0,0);return d;
  }
  function updatePublishDateMin(){
    var dt=document.getElementById('publishDateTime');if(dt)dt.min=toDatetimeLocalValue(minScheduledDate());
  }
  function clearPublishFieldError(wrapId,errorId){
    var wrap=document.getElementById(wrapId);if(wrap)wrap.classList.remove('hasPublishError');
    var error=document.getElementById(errorId);if(error)error.style.display='';
  }
  function clearAllPublishFieldErrors(){
    clearPublishFieldError('publishAccountSelectorsWrap','publishAccountsError');
    clearPublishFieldError('publishContentTypeWrap','publishContentTypesError');
    clearPublishFieldError('publishModeWrap','publishModeError');
    clearPublishFieldError('publishDateWrap','publishDateError');
    clearPublishFieldError('publishMediaWrap','publishMediaError');
  }
  function markPublishFieldError(wrapId,errorId,message){
    var wrap=document.getElementById(wrapId);if(wrap)wrap.classList.add('hasPublishError');
    var error=document.getElementById(errorId);if(error){if(message)error.textContent=message;error.style.display='block';}
  }
  function focusFirstPublishError(){
    var first=document.querySelector('#publishModal .hasPublishError');if(!first)return;
    first.scrollIntoView({behavior:'smooth',block:'center'});
    var focusable=first.querySelector('input:not([type="hidden"]),select,button');if(focusable)setTimeout(function(){focusable.focus();},220);
  }
  function setPublishModalStatus(message,isError){
    var el=document.getElementById('publishModalStatus');if(!el)return;
    el.textContent=String(message||'');el.className='modalStatus '+(isError?'error':'show');
  }

  function selectedPublishMedia(idea){
    var id=String(idea&&idea.selected_media_id||'').trim();if(!id)return null;
    var list=readyMediaItems(idea&&idea.media||[]);
    return list.find(function(m){return String(m.id||m.media_id||'')===id;})||null;
  }
  function ideaHasImageMedia(idea){var m=selectedPublishMedia(idea);return !!m&&String(m.media_type||'').toLowerCase()==='image';}
  function ideaHasVideoMedia(idea){var m=selectedPublishMedia(idea);return !!m&&String(m.media_type||'').toLowerCase()==='video';}
  function mediaGallery(idea){return readyMediaItems(idea&&idea.media||[]);}
  function publishMediaPreviewHtml(idea,index){
    var media=selectedPublishMedia(idea),available=mediaGallery(idea).length;
    if(!media){
      return '<div class="mediaSection" style="margin:0"><div class="mediaPlaceholder"><div><b>'+
        (available?'Aucun média sélectionné':'Aucun média disponible')+'</b><span>'+
        (available?available+' média(s) sont disponibles. Ferme cette fenêtre puis clique sur « Choisir ce média » dans le carrousel.':'Génère ou importe une image ou une vidéo avant de publier, ou confirme explicitement une publication texte lorsque le réseau le permet.')+
        '</span></div></div></div>';
    }
    var url=String(media.url||media.public_url||media.external_url||'').trim();
    var type=String(media.media_type||'').toLowerCase();
    if(type==='video'){
      return '<div class="mediaSection" style="margin:0"><div class="mediaHeader"><span class="mediaLabel">Vidéo jointe à la publication</span></div><video src="'+esc(url)+'" controls playsinline preload="metadata" class="mediaImg"></video><div class="mediaMeta">Cette vidéo sera jointe à la publication.</div></div>';
    }
    return '<div class="mediaSection" style="margin:0"><div class="mediaHeader"><span class="mediaLabel">Image jointe à la publication</span></div><img src="'+esc(url)+'" alt="Média qui sera publié avec le post '+(Number(index)+1)+'" class="mediaImg" style="max-height:420px;object-fit:contain;object-position:center center"><div class="mediaMeta">Cette image sera jointe à la publication.</div></div>';
  }

  function publishPlatformLabel(platform){return {linkedin:'LinkedIn',facebook:'Facebook',instagram:'Instagram'}[platform]||platform;}
  function publishContentTypeLabel(type){return type==='reel'?'Reel':(type==='story'?'Story':'Post');}
  function publishAccountService(account){return String(account&&account.service||'').trim().toLowerCase();}
  function publishAccountConnectionProvider(account){return String(account&&account.connection_provider||'').trim().toLowerCase();}
  function publishAccountTitle(account){return String(account&&account.display_name||account&&account.platform_account_name||account&&account.external_username||account&&account.external_account_id||account&&account.label||'Compte sans nom');}
  function publishAccountRouteLabel(account){
    var provider=String(account&&account.provider||'').toLowerCase(),connection=publishAccountConnectionProvider(account),service=publishAccountService(account);
    if(provider==='buffer'||connection==='buffer')return 'Buffer API'+(service?' · '+service:'');
    if(connection==='meta_direct')return 'Meta · Instagram Login';
    if(connection==='meta_facebook'&&provider==='facebook')return 'Meta · Page Facebook';
    return provider==='instagram'?'Instagram Login':(provider==='facebook'?'Meta · Facebook':'Fournisseur');
  }
  function publishAccountDetail(account,platform){
    return [publishAccountRouteLabel(account),account&&account.external_username?'@'+String(account.external_username).replace(/^@+/, ''):'',account&&account.external_account_id||''].filter(Boolean).join(' · ');
  }
  function accountLooksLinkedinBuffer(account){return publishAccountService(account).includes('linkedin')||String(account&&account.platform||'').toLowerCase()==='linkedin';}
  function accountLooksInstagramBuffer(account){return publishAccountService(account).includes('instagram')||String(account&&account.platform||'').toLowerCase()==='instagram';}
  function activePublishAccounts(platform){
    return publishAccountsCache.items.filter(function(account){
      if(!account||account.is_active===false)return false;
      var provider=String(account.provider||'').toLowerCase(),connection=publishAccountConnectionProvider(account),service=publishAccountService(account),declared=String(account.platform||'').toLowerCase();
      if(platform==='linkedin')return provider==='buffer'&&(accountLooksLinkedinBuffer(account)||declared==='linkedin');
      if(platform==='instagram')return (provider==='buffer'&&(accountLooksInstagramBuffer(account)||declared==='instagram'))||(provider==='instagram'&&(connection==='meta_direct'||!connection));
      if(platform==='facebook')return (provider==='buffer'&&(service.includes('facebook')||declared==='facebook'))||(provider==='facebook'&&(connection==='meta_facebook'||!connection));
      return false;
    });
  }
  function inferPublishContentTypeFromAccount(platform,account){
    var label=[account&&account.label,account&&account.display_name,account&&account.platform_account_name,account&&account.service].join(' ').toLowerCase();
    if(platform==='instagram'){
      if(/story|stories/.test(label))return 'story';if(/reel|réel/.test(label))return 'reel';
    }
    if(platform==='facebook'&&/reel|réel/.test(label))return 'reel';
    return 'standard';
  }
  function publishTargetsForAccount(platform,account){
    var hasImage=ideaHasImageMedia(ideaAt(currentPublishIndex)),hasVideo=ideaHasVideoMedia(ideaAt(currentPublishIndex));
    var provider=String(account&&account.provider||'').toLowerCase(),connection=publishAccountConnectionProvider(account),isBuffer=provider==='buffer'||connection==='buffer';
    var directInstagram=platform==='instagram'&&provider==='instagram'&&(connection==='meta_direct'||!connection),targets=[];
    function add(type){targets.push({platform:platform,account:account,contentType:type,disabled:false,disabledReason:''});}
    if(platform==='linkedin'){
      if(isBuffer)add('standard');
      return targets;
    }
    if(platform==='instagram'){
      // Les types proposés dépendent du média réellement sélectionné.
      // Meta direct : image = Post/Story ; vidéo = Reel/Story.
      if(directInstagram){
        if(hasImage){add('standard');add('story');}
        else if(hasVideo){add('reel');add('story');}
        return targets;
      }
      // Buffer : image = Post/Story ; vidéo = Post/Reel/Story.
      if(isBuffer){
        if(hasImage){add('standard');add('story');}
        else if(hasVideo){
          var base=inferPublishContentTypeFromAccount(platform,account);
          var order=base==='reel'?['reel','standard','story']:(base==='story'?['story','standard','reel']:['standard','reel','story']);
          order.forEach(add);
        }
        return targets;
      }
      return targets;
    }
    if(platform==='facebook'){
      add('standard');
      if(hasVideo)add('reel');
      return targets;
    }
    return targets;
  }
  function publishTargetKey(platform,type,id){return [platform,type,id].map(function(v){return String(v||'').trim();}).join('|');}
  function parsePublishTargetKey(key){var parts=String(key||'').split('|');return {platform:parts[0]||'',contentType:parts[1]||'standard',socialAccountId:parts[2]||''};}
  function publishAccountById(platform,id){return activePublishAccounts(platform).find(function(a){return String(a.id||'')===String(id||'');})||null;}
  function getSelectedPublishTargets(){
    return Array.from(publishTargetSelectionState).map(parsePublishTargetKey).map(function(target){
      var account=publishAccountById(target.platform,target.socialAccountId);if(!account)return null;
      return {platform:target.platform,contentType:target.contentType||'standard',socialAccountId:target.socialAccountId,accountName:publishAccountTitle(account),account:account};
    }).filter(Boolean);
  }
  function getSelectedPublishPlatforms(){return Array.from(new Set(getSelectedPublishTargets().map(function(t){return t.platform;}))).filter(Boolean);}
  function getSelectedPublishContentTypes(){return Array.from(new Set(getSelectedPublishTargets().map(function(t){return t.contentType||'standard';}))).filter(Boolean);}
  function prunePublishSelections(){
    Array.from(publishTargetSelectionState).forEach(function(key){
      var target=parsePublishTargetKey(key),account=publishAccountById(target.platform,target.socialAccountId);
      if(!account||!publishTargetsForAccount(target.platform,account).some(function(item){return item.contentType===target.contentType&&!item.disabled;}))publishTargetSelectionState.delete(key);
    });
  }
  async function ensurePublishAccountsLoaded(force){
    if(publishAccountsCache.loaded&&!force){renderPublishAccountSelectors();return publishAccountsCache.items;}
    if(publishAccountsCache.loading)return publishAccountsCache.loading;
    var box=document.getElementById('publishAccountSelectors');if(box)box.innerHTML='<div class="publishAccountEmpty">Chargement des comptes…</div>';
    publishAccountsCache.loading=(async function(){
      var r=await fetch(WEBHOOK_BASE+'/networks/publishable',{cache:'no-store'}),d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      publishAccountsCache.items=(d.data&&Array.isArray(d.data.accounts))?d.data.accounts:(Array.isArray(d.accounts)?d.accounts:[]);
      publishAccountsCache.loaded=true;renderPublishAccountSelectors();updatePublishTypeVisibility();return publishAccountsCache.items;
    })().catch(function(error){if(box)box.innerHTML='<div class="publishAccountError">Comptes indisponibles : '+esc(error.message)+'<br><a href="'+WEBHOOK_BASE+'/networks" target="_blank" rel="noopener">Gérer mes réseaux</a></div>';throw error;}).finally(function(){publishAccountsCache.loading=null;});
    return publishAccountsCache.loading;
  }
  function renderPublishAccountSelectors(){
    var mount=document.getElementById('publishAccountSelectors');if(!mount)return;
    prunePublishSelections();
    var platforms=['linkedin','facebook','instagram'];
    var availablePlatforms=platforms.filter(function(p){return activePublishAccounts(p).length>0;});
    var allTargets=[];availablePlatforms.forEach(function(p){activePublishAccounts(p).forEach(function(a){publishTargetsForAccount(p,a).filter(function(t){return !t.disabled;}).forEach(function(t){allTargets.push(t);});});});
    if(!allTargets.length){var selected=selectedPublishMedia(ideaAt(currentPublishIndex));var msg=selected?'Aucun compte/type compatible avec le média sélectionné.':'Aucun compte/type compatible. Pour Instagram, sélectionne d’abord une image ou une vidéo.';mount.innerHTML='<div class="publishAccountError">'+esc(msg)+' <a href="'+WEBHOOK_BASE+'/networks" target="_blank" rel="noopener">Gérer mes réseaux</a></div>';updatePublishTypeVisibility();return;}
    mount.innerHTML='<div class="publishAccountMultiBox"><div class="publishAccountTags"></div><input class="publishAccountSearch" type="text" autocomplete="off" placeholder="Rechercher et sélectionner un compte / type..."></div><div class="publishAccountDropdown"></div><div class="publishAccountHidden"></div><div class="publishAccountSummary"></div>';
    var box=mount.querySelector('.publishAccountMultiBox'),tags=mount.querySelector('.publishAccountTags'),search=mount.querySelector('.publishAccountSearch'),dropdown=mount.querySelector('.publishAccountDropdown'),hidden=mount.querySelector('.publishAccountHidden'),summary=mount.querySelector('.publishAccountSummary');
    function selectedTargets(){return getSelectedPublishTargets();}
    function selectionChanged(){draw();if(getSelectedPublishPlatforms().length)clearPublishFieldError('publishAccountSelectorsWrap','publishAccountsError');updatePublishTypeVisibility();window.updatePublishMediaRequirement();search.focus();}
    function toggle(platform,type,id){var key=publishTargetKey(platform,type,id);if(publishTargetSelectionState.has(key))publishTargetSelectionState.delete(key);else publishTargetSelectionState.add(key);selectionChanged();}
    function draw(){
      tags.innerHTML='';hidden.innerHTML='';var targets=selectedTargets();
      targets.forEach(function(target){
        var tag=document.createElement('span');tag.className='publishAccountTag';var text=document.createElement('span');text.textContent=publishPlatformLabel(target.platform)+' '+publishContentTypeLabel(target.contentType)+' · '+publishAccountRouteLabel(target.account)+' · '+target.accountName;
        var remove=document.createElement('button');remove.type='button';remove.setAttribute('aria-label','Retirer '+target.accountName);remove.textContent='×';remove.addEventListener('click',function(e){e.stopPropagation();publishTargetSelectionState.delete(publishTargetKey(target.platform,target.contentType,target.socialAccountId));selectionChanged();});tag.appendChild(text);tag.appendChild(remove);tags.appendChild(tag);
        var input=document.createElement('input');input.type='checkbox';input.hidden=true;input.checked=true;input.name='publishTarget';input.value=JSON.stringify({platform:target.platform,contentType:target.contentType,socialAccountId:target.socialAccountId});hidden.appendChild(input);
      });
      summary.textContent=targets.length?targets.length+' publication(s) sélectionnée(s) · '+targets.map(function(t){return publishPlatformLabel(t.platform)+' '+publishContentTypeLabel(t.contentType);}).join(', '):'Aucune publication sélectionnée.';
      drawOptions();
    }
    function drawOptions(){
      var q=String(search.value||'').trim().toLowerCase();dropdown.innerHTML='';var count=0;
      availablePlatforms.forEach(function(platform){
        var list=[];activePublishAccounts(platform).forEach(function(account){publishTargetsForAccount(platform,account).forEach(function(item){var hay=[publishPlatformLabel(item.platform),publishContentTypeLabel(item.contentType),publishAccountTitle(item.account),publishAccountDetail(item.account,item.platform),item.disabledReason].join(' ').toLowerCase();if(!q||hay.includes(q))list.push(item);});});
        if(!list.length)return;var group=document.createElement('div');group.className='publishAccountGroupTitle';group.textContent=publishPlatformLabel(platform);dropdown.appendChild(group);
        list.forEach(function(item){
          var id=String(item.account.id||'').trim();if(!id)return;count++;var key=publishTargetKey(item.platform,item.contentType,id),selected=publishTargetSelectionState.has(key);
          var button=document.createElement('button');button.type='button';button.className='publishAccountOption'+(selected?' selected':'')+(item.disabled?' disabled':'');button.disabled=!!item.disabled;
          var tx=document.createElement('span');tx.className='publishAccountOptionText';var title=document.createElement('b');title.textContent=publishPlatformLabel(item.platform)+' '+publishContentTypeLabel(item.contentType)+' · '+publishAccountRouteLabel(item.account)+' · '+publishAccountTitle(item.account);var detail=document.createElement('small');detail.textContent=(publishAccountDetail(item.account,item.platform)||publishPlatformLabel(item.platform))+(item.disabledReason?' · '+item.disabledReason:'');var mark=document.createElement('span');mark.className='publishAccountOptionMark';mark.textContent=item.disabled?'':'✓';tx.appendChild(title);tx.appendChild(detail);button.appendChild(tx);button.appendChild(mark);
          if(!item.disabled)button.addEventListener('mousedown',function(e){e.preventDefault();toggle(item.platform,item.contentType,id);});dropdown.appendChild(button);
        });
      });
      if(!count){var empty=document.createElement('div');empty.className='publishAccountEmpty';empty.textContent=q?'Aucun compte/type ne correspond à cette recherche.':'Aucun compte/type compatible avec le média sélectionné.';dropdown.appendChild(empty);}
    }
    box.addEventListener('click',function(){search.focus();});search.addEventListener('focus',function(){drawOptions();dropdown.classList.add('isOpen');});search.addEventListener('input',function(){drawOptions();dropdown.classList.add('isOpen');});search.addEventListener('keydown',function(e){if(e.key==='Escape'){dropdown.classList.remove('isOpen');search.blur();}});search.addEventListener('blur',function(){setTimeout(function(){dropdown.classList.remove('isOpen');},140);});draw();
  }
  function updatePublishTypeVisibility(){
    var wrap=document.getElementById('publishContentTypeWrap'),hint=document.getElementById('publishContentTypeHint'),box=document.getElementById('publishContentTypes'),targets=getSelectedPublishTargets();
    if(wrap)wrap.style.display='none';if(box)box.innerHTML='';if(hint)hint.textContent=targets.length?'Le type de publication est déterminé par le compte sélectionné : '+targets.map(function(t){return publishPlatformLabel(t.platform)+' '+publishContentTypeLabel(t.contentType);}).join(', ')+'.':'Choisis un compte/type à utiliser.';
    clearPublishFieldError('publishContentTypeWrap','publishContentTypesError');window.updatePublishMediaRequirement();
  }
  function publishWithoutMediaConfirmed(){var cb=document.getElementById('publishWithoutMedia');return !!(cb&&cb.checked);}
  function canExplicitlyPublishWithoutMedia(platforms,types){return platforms.length>0&&types.length>0&&platforms.every(function(p){return p==='linkedin'||p==='facebook';})&&types.every(function(t){return t==='standard';});}
  function updatePublishMediaRequirementCore(){
    if(currentPublishIndex===null)return {requiresMedia:false,selectedMediaId:'',omitMedia:false,effectiveMediaId:null};
    var idea=ideaAt(currentPublishIndex),selected=selectedPublishMedia(idea),platforms=getSelectedPublishPlatforms(),types=getSelectedPublishContentTypes(),hasTarget=platforms.length>0&&types.length>0,canText=canExplicitlyPublishWithoutMedia(platforms,types),without=publishWithoutMediaConfirmed();
    var requirement=document.getElementById('publishMediaRequirement'),choose=document.getElementById('publishChooseMediaBtn'),withoutWrap=document.getElementById('publishWithoutMediaWrap'),mark=document.getElementById('publishMediaRequiredMark'),available=mediaGallery(idea).length;
    var selectedMediaId=selected?String(selected.id||selected.media_id||'').trim():'';
    var requiresMedia=Boolean(hasTarget&&!canText);
    if(mark)mark.style.display=requiresMedia?'inline':'none';
    if(selected){
      if(requirement){requirement.style.background='#ecfdf5';requirement.style.border='1px solid #bbf7d0';requirement.style.color='#047857';requirement.textContent='Média sélectionné : il sera joint à la publication.';}
      if(choose)choose.style.display='none';if(withoutWrap)withoutWrap.style.display='none';var cb=document.getElementById('publishWithoutMedia');if(cb)cb.checked=false;clearPublishFieldError('publishMediaWrap','publishMediaError');
      return {requiresMedia:requiresMedia,selectedMediaId:selectedMediaId,omitMedia:false,effectiveMediaId:selectedMediaId||null};
    }
    if(requirement){requirement.style.background='#fef2f2';requirement.style.border='1px solid #fecaca';requirement.style.color='#991b1b';requirement.textContent=available?'Des médias existent, mais aucun n’est sélectionné pour cette publication.':'Aucun média n’est sélectionné pour cette publication.';}
    if(choose)choose.style.display='inline-flex';if(withoutWrap)withoutWrap.style.display=canText?'inline-flex':'none';if(!canText){var cb2=document.getElementById('publishWithoutMedia');if(cb2)cb2.checked=false;}if(canText&&without)clearPublishFieldError('publishMediaWrap','publishMediaError');
    var omitMedia=Boolean(canText&&without);
    return {requiresMedia:requiresMedia,selectedMediaId:'',omitMedia:omitMedia,effectiveMediaId:omitMedia?null:(selectedMediaId||null)};
  }
  window.updatePublishMediaRequirement=function(){return updatePublishMediaRequirementCore();};
  window.focusMediaSelectionFromPublish=function(){
    var index=currentPublishIndex;if(index===null)return false;window.closePublishModal();var slot=document.getElementById('media-slot-'+index);if(slot)slot.scrollIntoView({behavior:'smooth',block:'center'});showToast('Choisis explicitement un média avec le bouton « Choisir ce média » avant de publier.','error');return false;
  };
  function updatePublishScheduleVisibility(){
    var mode=(document.getElementById('publishMode')||{}).value||'',wrap=document.getElementById('publishDateWrap'),dt=document.getElementById('publishDateTime'),confirm=document.getElementById('publishModalConfirm');
    if(wrap)wrap.style.display=mode==='scheduled'?'block':'none';if(dt)dt.required=mode==='scheduled';if(mode)clearPublishFieldError('publishModeWrap','publishModeError');if(mode!=='scheduled')clearPublishFieldError('publishDateWrap','publishDateError');updatePublishTypeVisibility();if(confirm){confirm.disabled=false;confirm.textContent=mode==='scheduled'?'Programmer':'Publier';}
  }
  window.openPublishModal=async function(i){
    currentPublishIndex=i;var idea=ideaAt(i),modal=document.getElementById('publishModal');
    document.getElementById('publishModalIdea').innerHTML='<b>#'+(Number(i)+1)+' · '+esc(idea.ready_post&&idea.ready_post.title||idea.title||'Post')+'</b><br><span>'+esc(idea.recommended_format||'Format non défini')+'</span>';
    document.getElementById('publishPostPreview').value=(postBox(i)||{}).value||'';var preview=document.getElementById('publishMediaPreview');if(preview)preview.innerHTML=publishMediaPreviewHtml(idea,i);
    var noMedia=document.getElementById('publishWithoutMedia');if(noMedia)noMedia.checked=false;var status=document.getElementById('publishModalStatus');if(status){status.textContent='';status.className='modalStatus';}
    clearAllPublishFieldErrors();var mode=document.getElementById('publishMode');if(mode)mode.value='';var dt=document.getElementById('publishDateTime');if(dt)dt.value='';updatePublishDateMin();updatePublishScheduleVisibility();renderPublishAccountSelectors();modal.classList.add('isVisible');
    try{await ensurePublishAccountsLoaded(false);}catch(_e){}return false;
  };
  window.closePublishModal=function(){var modal=document.getElementById('publishModal');if(modal)modal.classList.remove('isVisible');currentPublishIndex=null;return false;};
  document.addEventListener('change',function(e){
    if(e.target&&e.target.id==='publishMode')updatePublishScheduleVisibility();
    else if(e.target&&e.target.id==='publishWithoutMedia'){clearPublishFieldError('publishMediaWrap','publishMediaError');window.updatePublishMediaRequirement();}
    else if(e.target&&e.target.id==='publishDateTime'&&e.target.value)clearPublishFieldError('publishDateWrap','publishDateError');
  });
  window.confirmPublishModal=async function(){
    var index=currentPublishIndex;if(index===null)return false;var idea=ideaAt(index),platforms=getSelectedPublishPlatforms(),types=getSelectedPublishContentTypes(),mode=(document.getElementById('publishMode')||{}).value||'',scheduledLocal=(document.getElementById('publishDateTime')||{}).value||'';
    clearAllPublishFieldErrors();var missing=false;if(!platforms.length){markPublishFieldError('publishAccountSelectorsWrap','publishAccountsError','Choisis au moins un compte à utiliser.');missing=true;}if(!mode){markPublishFieldError('publishModeWrap','publishModeError','Choisis le moment de publication.');missing=true;}if(mode==='scheduled'&&!scheduledLocal){markPublishFieldError('publishDateWrap','publishDateError','Choisis une date et une heure de publication.');missing=true;}if(missing){setPublishModalStatus('Complète les champs obligatoires indiqués en rouge.',true);focusFirstPublishError();return false;}
    var selected=selectedPublishMedia(idea);if(!selected){var candidates=mediaGallery(idea);if(candidates.length===1){setPublishModalStatus('Préparation du média unique...');await window.selectMedia(String(candidates[0].id||candidates[0].media_id||''),index,null);selected=selectedPublishMedia(idea);}}
    var canText=canExplicitlyPublishWithoutMedia(platforms,types),without=publishWithoutMediaConfirmed();var mediaState=window.updatePublishMediaRequirement();if(mediaState&&mediaState.requiresMedia&&!mediaState.selectedMediaId){markPublishFieldError('publishMediaWrap','publishMediaError','Sélectionne un média avant de publier.');setPublishModalStatus('Sélectionne un média avant de publier.',true);focusFirstPublishError();return false;}if(!selected&&!(canText&&without)){markPublishFieldError('publishMediaWrap','publishMediaError','Sélectionne un média avant de publier ou confirme explicitement une publication sans média lorsque cette option est autorisée.');setPublishModalStatus('Sélectionne un média avant de publier. Pour un Post LinkedIn/Facebook sans média, coche explicitement « Publier volontairement sans média ».',true);window.updatePublishMediaRequirement();focusFirstPublishError();return false;}
    if(platforms.includes('instagram')&&!selected){markPublishFieldError('publishMediaWrap','publishMediaError','Instagram nécessite une image ou une vidéo sélectionnée.');setPublishModalStatus('Instagram nécessite une image ou une vidéo.',true);focusFirstPublishError();return false;}
    if(types.includes('reel')&&!ideaHasVideoMedia(idea)){markPublishFieldError('publishMediaWrap','publishMediaError','Un Reel nécessite une vidéo sélectionnée.');setPublishModalStatus('Un Reel nécessite une vidéo.',true);focusFirstPublishError();return false;}
    if(types.includes('story')&&!selected){markPublishFieldError('publishMediaWrap','publishMediaError','Une Story nécessite une image ou une vidéo sélectionnée.');setPublishModalStatus('Une Story nécessite une image ou une vidéo.',true);focusFirstPublishError();return false;}
    if(mode==='scheduled'){updatePublishDateMin();var ts=new Date(scheduledLocal).getTime();if(!Number.isFinite(ts)||ts<minScheduledDate().getTime()-1000){markPublishFieldError('publishDateWrap','publishDateError','Choisis une date et une heure futures.');setPublishModalStatus('Choisis une date et une heure futures.',true);focusFirstPublishError();return false;}}
    var btn=document.getElementById('publishModalConfirm');if(btn)btn.disabled=true;setPublishModalStatus('Enregistrement du texte...');
    try{
      if(saveTimers[index]){clearTimeout(saveTimers[index]);saveTimers[index]=null;}var saved=await window.savePostEdit(currentPublishIndex);if(saved===false)throw new Error('Le texte du post n’a pas pu être enregistré. Publication annulée.');
      setPublishModalStatus(mode==='scheduled'?'Planification en cours…':'Publication en cours…');var scheduledAt=mode==='scheduled'?new Date(scheduledLocal).toISOString():null;
      var targets=getSelectedPublishTargets().map(function(t){return {provider:String(t.account.provider||'').toLowerCase(),platform:t.platform,account_id:t.socialAccountId,publish_content_type:t.contentType||'standard',publish_mode:mode==='scheduled'?'scheduled':'immediate',scheduled_at:scheduledAt};});
      var r=await fetch(WEBHOOK_BASE+'/post-ideas-publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea_id:idea.idea_id,version_id:idea.version_id,media_id:(mediaState&&mediaState.effectiveMediaId)||null,timezone:(window.pgUserTimezone?window.pgUserTimezone():window.__PG_TIMEZONE||'UTC'),targets:targets})});var d=await r.json().catch(function(){return {};});if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      showToast(d.message||'Publication traitée.','success');window.closePublishModal();setTimeout(function(){location.reload();},800);
    }catch(e){setPublishModalStatus(e.message||'Publication impossible.',true);if(btn)btn.disabled=false;}return false;
  };
  window.publishSelectedPost=window.confirmPublishModal;


  function ideaIndexById(ideaId){var id=String(ideaId||'').trim();return (VIEW.ideas||[]).findIndex(function(idea){return String(idea.idea_id||'')===id;});}
  function startRestoredAiMediaJobs(){
    (Array.isArray(VIEW.backgroundJobs)?VIEW.backgroundJobs:[]).forEach(function(job){
      if(String(job.type||'').toLowerCase()!=='video'||!job.media_id)return;
      var i=ideaIndexById(job.idea_id);if(i<0)return;
      pollVideoMediaUntilFinished(i,String(job.media_id),String(job.id||('media-'+job.media_id)));
    });
  }
  setTimeout(startRestoredAiMediaJobs,700);

  /* ---------- Génération d'idées en arrière-plan — parité V90 ---------- */
  var generationPollTimer=null;
  function setGenerateMoreLaunchBusy(busy){
    var launchButton=document.querySelector('.moreIdeasFooter .moreIdeasBtn');
    if(!launchButton)return;
    launchButton.disabled=Boolean(busy);
    launchButton.textContent=busy?'Génération en cours…':'Générer plus d\'idées';
    launchButton.title=busy?'Une génération est déjà en cours':'';
  }
  async function fetchGenerationStatus(){
    if(!VIEW.requestId)return null;
    var r=await fetch(WEBHOOK_BASE+'/posts/generation-status?request_id='+encodeURIComponent(VIEW.requestId),{credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'}});
    var d=await r.json().catch(function(){return {};});
    if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
    return d.data||d;
  }
  function stopGenerationPoll(){if(generationPollTimer){clearTimeout(generationPollTimer);generationPollTimer=null;}}
  function scheduleGenerationPoll(statusEl){
    stopGenerationPoll();
    async function tick(){
      try{
        var d=await fetchGenerationStatus();
        if(!d)return;
        var js=String(d.job_status||'').toLowerCase();
        var rs=String(d.status||'').toLowerCase();
        var active=['queued','running','retry'].indexOf(js)>=0||['generating','generating_more'].indexOf(rs)>=0;
        if(active){
          updateAiJob('ideas-'+VIEW.requestId,{type:'ideas',label:'Génération des sujets',status:'processing',message:(d.ideas_count||0)+' idée(s) disponible(s) · génération en arrière-plan…'});
        }
        if(statusEl&&active){
          statusEl.textContent=(d.ideas_count||0)+' idée(s) disponible(s) · génération en arrière-plan…';
          statusEl.className='generateMoreStatus show loading';
        }
        if(active){generationPollTimer=setTimeout(tick,2500);return;}
        if(js==='failed'||rs==='failed'){
          var err=d.job_error||d.last_error||'La génération a échoué.';
          failAiJob('ideas-'+VIEW.requestId,err);
          if(statusEl){statusEl.textContent=err;statusEl.className='generateMoreStatus error';}
          setGenerateMoreLaunchBusy(false);
          if(typeof showToast==='function')showToast(err,'error');
          return;
        }
        completeAiJob('ideas-'+VIEW.requestId,'Génération terminée.');
        window.location.reload();
      }catch(error){
        if(statusEl){statusEl.textContent='Vérification de la génération impossible : '+error.message;statusEl.className='generateMoreStatus error';}
        generationPollTimer=setTimeout(tick,5000);
      }
    }
    generationPollTimer=setTimeout(tick,1200);
  }
  window.submitGenerateMoreIdeas=async function(event,form){
    if(event&&event.preventDefault)event.preventDefault();
    var status=document.getElementById('generateMoreStatus');
    var submit=form&&form.querySelector('button[type="submit"]');
    var count=Math.max(1,Math.min(8,Math.round(Number(form&&form.post_count&&form.post_count.value||3))));
    if(!Number.isFinite(count)){if(status){status.textContent='Indique un nombre entre 1 et 8.';status.className='generateMoreStatus error';}return false;}
    if(status){status.textContent='Lancement de la génération…';status.className='generateMoreStatus show loading';}
    if(submit){submit.disabled=true;submit.classList.add('loading');}
    try{
      var r=await fetch(WEBHOOK_BASE+'/posts/generate-more',{
        method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json','X-PG-Api-Context':'generate_more'},
        credentials:'same-origin',
        body:JSON.stringify({request_id:VIEW.requestId,post_count:count,additional_count:count,api_response_format:'json',api_context:'generate_more'})});
      var raw=await r.text();var d={};try{d=raw?JSON.parse(raw):{};}catch(_e){}
      if(!r.ok||d.success===false)throw new Error(d.message||d.error||raw||('HTTP '+r.status));
      if(d.async===true||['queued','pending','processing','generating','accepted'].indexOf(String(d.status||'queued').toLowerCase())>=0){
        var backgroundMessage=d.message||'Génération additionnelle lancée en arrière-plan.';
        updateAiJob('ideas-'+VIEW.requestId,{type:'ideas',label:'Génération des sujets',status:'processing',message:backgroundMessage});
        if(status){status.textContent=backgroundMessage;status.className='generateMoreStatus show loading';}
        var modal=document.getElementById('generateMoreModal');
        if(modal)modal.classList.remove('isVisible');
        setGenerateMoreLaunchBusy(true);
        if(typeof showToast==='function')showToast('Génération lancée en arrière-plan.','success');
        scheduleGenerationPoll(null);
        return false;
      }
      window.location.reload();
    }catch(e){
      if(status){status.textContent=e.message||'Génération impossible.';status.className='generateMoreStatus error';}
      if(typeof showToast==='function')showToast('Impossible de générer plus d’idées.','error');
      if(submit){submit.disabled=false;submit.classList.remove('loading');}
    }
    return false;
  };
  if(VIEW.generationInProgress)scheduleGenerationPoll(null);
})();
