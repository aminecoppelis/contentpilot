/**
 * Formulaire de création de sujet — port des interactions du workflow :
 * multi-select personnalisés (recherche + ajout libre via Entrée), suggestions
 * de sujet via Serper, bouton de reformulation IA (mode generate/improve),
 * validation par champ et overlay de génération.
 */
(function(){
  var WEBHOOK_BASE='/app';
  var form=document.getElementById('ideasForm');
  if(!form)return;
  var themeInput=document.getElementById('themeInput');
  var reformulateBtn=document.getElementById('reformulateBtn');
  var promptAssistStatus=document.getElementById('promptAssistStatus');
  var submitBtn=document.getElementById('submitBtn');
  var overlay=document.getElementById('loaderOverlay');
  var subjectInput=document.getElementById('subjectInput');
  var suggestionsEl=document.getElementById('subjectSuggestions');

  /* --- Multi-select : structure identique au V90 n8n --- */
  function uniqValues(values){
    return Array.from(new Set((values||[]).map(function(v){return String(v||'').trim();}).filter(Boolean)));
  }
  function createMultiSelect(config){
    var mount=document.getElementById(config.mountId);
    if(!mount)return {getValues:function(){return [];}};
    var state={options:uniqValues(config.options),selected:uniqValues(config.selected)};
    mount.innerHTML='<div class="msBox"><div class="msTags"></div><input class="msSearch" type="text" autocomplete="off"></div><div class="msOptions"></div><div class="msHidden"></div>';
    var tagsEl=mount.querySelector('.msTags');
    var input=mount.querySelector('.msSearch');
    var optionsEl=mount.querySelector('.msOptions');
    var hiddenEl=mount.querySelector('.msHidden');
    input.placeholder=config.placeholder||'Rechercher ou ajouter...';
    function closeOptionsSoon(){setTimeout(function(){optionsEl.classList.remove('isOpen');},140);}
    function addValue(value){
      var clean=String(value||'').trim();if(!clean)return;
      if(state.options.indexOf(clean)<0)state.options.push(clean);
      if(state.selected.indexOf(clean)<0)state.selected.push(clean);
      input.value='';render();
      var field=mount.closest('.field');if(field){field.classList.remove('isInvalid','hasError');var err=field.querySelector('.error');if(err)err.classList.remove('isVisible');}
    }
    function removeValue(value){state.selected=state.selected.filter(function(v){return v!==value;});render();}
    function render(){
      tagsEl.innerHTML='';hiddenEl.innerHTML='';
      state.selected.forEach(function(value){
        var tag=document.createElement('span');tag.className='msTag';
        var text=document.createElement('span');text.textContent=value;
        var btn=document.createElement('button');btn.type='button';btn.setAttribute('aria-label','Retirer '+value);btn.textContent='×';
        btn.addEventListener('click',function(event){event.stopPropagation();removeValue(value);});
        tag.appendChild(text);tag.appendChild(btn);tagsEl.appendChild(tag);
        var hidden=document.createElement('input');hidden.type='hidden';hidden.name=config.name;hidden.value=value;hiddenEl.appendChild(hidden);
      });
      renderOptions();
    }
    function renderOptions(){
      var q=input.value.trim().toLowerCase();
      var available=state.options.filter(function(opt){return state.selected.indexOf(opt)<0&&(!q||opt.toLowerCase().indexOf(q)>=0);});
      optionsEl.innerHTML='';
      available.slice(0,12).forEach(function(opt){
        var btn=document.createElement('button');btn.type='button';btn.className='msOption';btn.innerHTML='<span></span><strong>+</strong>';
        btn.querySelector('span').textContent=opt;
        btn.addEventListener('mousedown',function(event){event.preventDefault();addValue(opt);input.focus();});optionsEl.appendChild(btn);
      });
      var lowers=state.options.map(function(v){return v.toLowerCase();});
      var selectedLowers=state.selected.map(function(v){return v.toLowerCase();});
      if(q&&selectedLowers.indexOf(q)<0&&lowers.indexOf(q)<0){
        var addBtn=document.createElement('button');addBtn.type='button';addBtn.className='msOption msOptionAdd';addBtn.innerHTML='<span></span><strong>Ajouter</strong>';
        addBtn.querySelector('span').textContent=input.value.trim();
        addBtn.addEventListener('mousedown',function(event){event.preventDefault();addValue(input.value);input.focus();});optionsEl.prepend(addBtn);
      }
      if(!optionsEl.children.length){var empty=document.createElement('div');empty.className='msEmpty';empty.textContent='Aucune option disponible. Écris une valeur et appuie sur Entrée.';optionsEl.appendChild(empty);}
    }
    input.addEventListener('focus',function(){renderOptions();optionsEl.classList.add('isOpen');});
    input.addEventListener('blur',closeOptionsSoon);
    input.addEventListener('input',function(){renderOptions();optionsEl.classList.add('isOpen');});
    input.addEventListener('keydown',function(event){
      if(event.key==='Enter'){event.preventDefault();var first=optionsEl.querySelector('.msOption');if(first)first.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}));else addValue(input.value);}
      if(event.key==='Backspace'&&!input.value&&state.selected.length)removeValue(state.selected[state.selected.length-1]);
    });
    mount.querySelector('.msBox').addEventListener('click',function(){input.focus();});render();
    return {getValues:function(){return state.selected.slice();},addValue:addValue,removeValue:removeValue};
  }

  var multiSelects={
    content_domains:createMultiSelect({
      mountId:'contentDomainsSelect',name:'content_domains',
      placeholder:'Rechercher ou ajouter un domaine...',
      options:['Intelligence artificielle','Agents IA','Automatisation','Logiciels professionnels','SaaS',
        'Analyse d\u2019images et vidéos par IA','Productivité','Data Analytics','Business Intelligence',
        'Transformation numérique des entreprises'],
      selected:['Intelligence artificielle','Agents IA','Automatisation','Logiciels professionnels','SaaS',
        'Analyse d\u2019images et vidéos par IA','Productivité','Data Analytics','Business Intelligence',
        'Transformation numérique des entreprises']
    }),
    target_audience:createMultiSelect({
      mountId:'targetAudienceSelect',name:'target_audience',
      placeholder:'Rechercher ou ajouter un public...',
      options:['PME','Indépendants','Grandes entreprises','Directions métiers','Dirigeants','DSI / IT'],
      selected:[]
    }),
    preferred_formats:createMultiSelect({
      mountId:'preferredFormatsSelect',name:'preferred_formats',
      placeholder:'Rechercher ou ajouter un format...',
      options:['LinkedIn · Post','Facebook · Post','Facebook · Reel','Instagram · Post','Instagram · Story',
        'Instagram · Reel','Démo produit','Cas d\u2019usage','Conseil pratique','Avant / Après','Mini-guide','Article expert'],
      selected:['LinkedIn · Post','Facebook · Post','Instagram · Post']
    })
  };
  function getMultiValues(name){ return multiSelects[name]?multiSelects[name].getValues():[]; }
  function getFieldValue(name){
    var f=form.querySelector('[name="'+name+'"]'); return f?f.value:'';
  }

  /* --- Suggestions de sujet (Serper) --- */
  var suggestTimer=null;
  if(subjectInput&&suggestionsEl){
    subjectInput.addEventListener('input',function(){
      clearTimeout(suggestTimer);
      var q=subjectInput.value.trim();
      if(q.length<3){ suggestionsEl.classList.remove('isOpen'); return; }
      suggestTimer=setTimeout(async function(){
        try{
          var r=await fetch(WEBHOOK_BASE+'/subject-suggestions',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({subject_partial:q})});
          var d=await r.json().catch(function(){return {};});
          var items=(d.data&&d.data.suggestions)||d.suggestions||[];
          suggestionsEl.innerHTML='';
          items.slice(0,8).forEach(function(s){
            var el=document.createElement('div'); el.className='subjectSuggestion'; el.textContent=s;
            el.addEventListener('mousedown',function(e){
              e.preventDefault(); subjectInput.value=s; suggestionsEl.classList.remove('isOpen');
            });
            suggestionsEl.appendChild(el);
          });
          suggestionsEl.classList.toggle('isOpen',items.length>0);
          subjectInput.setAttribute('aria-expanded',items.length?'true':'false');
        }catch(e){ suggestionsEl.classList.remove('isOpen'); }
      },320);
    });
    subjectInput.addEventListener('blur',function(){
      setTimeout(function(){suggestionsEl.classList.remove('isOpen');},150);
    });
  }

  /* --- Reformulation IA du prompt --- */
  function setPromptAssistStatus(message,type){
    if(!promptAssistStatus)return;
    promptAssistStatus.textContent=message||'';
    promptAssistStatus.className='assistStatus';
    if(message)promptAssistStatus.classList.add('isVisible',type||'info');
  }
  function getPromptMode(){ return themeInput&&themeInput.value.trim()?'improve':'generate'; }
  function syncReformulateButtonLabel(){
    if(reformulateBtn)reformulateBtn.textContent=getPromptMode()==='improve'?'Améliorer avec l\u2019IA':'Générer avec l\u2019IA';
  }
  if(themeInput)themeInput.addEventListener('input',syncReformulateButtonLabel);
  syncReformulateButtonLabel();

  if(reformulateBtn)reformulateBtn.addEventListener('click',async function(){
    var subject=getFieldValue('subject').trim();
    if(!subject){ setPromptAssistStatus('Renseigne d\u2019abord un sujet.','error'); return; }
    reformulateBtn.disabled=true;
    setPromptAssistStatus('Génération du prompt en cours…','info');
    try{
      var payload={
        subject:subject, prompt:themeInput?themeInput.value:'', prompt_mode:getPromptMode(),
        commercial_objective:getFieldValue('commercial_objective'),
        target_sector:getFieldValue('target_sector'),
        language:getFieldValue('language'),
        constraints:getFieldValue('constraints'),
        content_domains:getMultiValues('content_domains'),
        target_audience:getMultiValues('target_audience'),
        preferred_formats:getMultiValues('preferred_formats')
      };
      var r=await fetch(WEBHOOK_BASE+'/reformulate-prompt',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      var prompt=(d.data&&d.data.prompt)||d.prompt||'';
      if(prompt&&themeInput){ themeInput.value=prompt; themeInput.dispatchEvent(new Event('input',{bubbles:true})); }
      setPromptAssistStatus('Prompt généré.','success');
    }catch(e){ setPromptAssistStatus('Génération impossible : '+e.message,'error'); }
    finally{ reformulateBtn.disabled=false; syncReformulateButtonLabel(); }
  });

  /* --- Validation + soumission --- */
  function markInvalid(fieldName,invalid){
    var f=form.querySelector('[data-field="'+fieldName+'"]');
    if(f){f.classList.toggle('isInvalid',Boolean(invalid));f.classList.toggle('hasError',Boolean(invalid));var err=f.querySelector('.error');if(err)err.classList.toggle('isVisible',Boolean(invalid));}
  }
  form.addEventListener('submit',async function(event){
    event.preventDefault();
    var subject=getFieldValue('subject').trim();
    var domains=getMultiValues('content_domains');
    var formats=getMultiValues('preferred_formats');
    var ok=true;
    markInvalid('subject',!subject); if(!subject)ok=false;
    markInvalid('content_domains',!domains.length); if(!domains.length)ok=false;
    markInvalid('preferred_formats',!formats.length); if(!formats.length)ok=false;
    if(!ok)return;

    if(submitBtn)submitBtn.disabled=true;
    if(overlay)overlay.classList.add('isOpen','isVisible');
    try{
      var payload={
        subject:subject,
        prompt:themeInput?themeInput.value:'',
        commercial_objective:getFieldValue('commercial_objective'),
        target_sector:getFieldValue('target_sector'),
        language:getFieldValue('language'),
        constraints:getFieldValue('constraints'),
        post_count:Number(getFieldValue('post_count')||5),
        company:getFieldValue('company'),
        website:getFieldValue('website'),
        solution:getFieldValue('solution'),
        default_tags:getFieldValue('default_tags'),
        content_domains:domains,
        target_audience:getMultiValues('target_audience'),
        preferred_formats:formats
      };
      var r=await fetch(WEBHOOK_BASE+'/post-ideas-generate',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      var d=await r.json().catch(function(){return {};});
      if(!r.ok||d.success===false)throw new Error(d.message||('HTTP '+r.status));
      var requestId=(d.data&&d.data.request_id)||d.request_id||'';
      var redirectUrl=d.redirect_url||(d.data&&d.data.redirect_url)||(WEBHOOK_BASE+'/posts/view?request_id='+encodeURIComponent(requestId)+'&queued=1');
      window.location.href=redirectUrl;
    }catch(e){
      if(overlay)overlay.classList.remove('isOpen','isVisible');
      if(submitBtn)submitBtn.disabled=false;
      window.pgToast(e.message||window.t('js.form.gen_failed'),'error');
    }
  });
})();
