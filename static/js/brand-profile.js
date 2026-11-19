(function(){
  'use strict';
  var form=document.getElementById('ideasForm'),data=document.getElementById('brandProfileData');
  if(!form||!data)return;
  var saved=JSON.parse(data.textContent),apply=document.getElementById('brandProfileApply'),save=document.getElementById('brandProfileSave'),auto=document.getElementById('brandProfileAuto'),status=document.getElementById('brandProfileStatus');
  var names=['company','website','solution','default_tags','constraints'];
  function current(){var value={};names.forEach(function(name){value[name]=form.elements[name].value;});value.use_macaron=form.elements.use_macaron.checked;return value;}
  var baseline=JSON.stringify(current());
  function message(key,error){status.textContent=window.t(key);status.classList.toggle('isError',!!error);}
  function changed(){message('js.brand.unsaved');}
  names.forEach(function(name){form.elements[name].addEventListener('input',changed);});form.elements.use_macaron.addEventListener('change',changed);auto.addEventListener('change',changed);
  apply.addEventListener('click',async function(){
    if(!saved)return;
    if(JSON.stringify(current())!==baseline){
      var ok=window.pgConfirm?await window.pgConfirm(window.t('js.brand.replace')):window.confirm(window.t('js.brand.replace'));
      if(!ok)return;
    }
    names.forEach(function(name){form.elements[name].value=saved[name];form.elements[name].dispatchEvent(new Event('input',{bubbles:true}));});
    form.elements.use_macaron.checked=saved.use_macaron;
    form.elements.use_macaron.dispatchEvent(new Event('change',{bubbles:true}));
    var preview=document.getElementById('newMacaronPreview');if(preview)preview.style.display=saved.use_macaron?'flex':'none';
    baseline=JSON.stringify(current());message('js.brand.applied');
  });
  save.addEventListener('click',async function(){
    var payload=current();payload.auto_apply=auto.checked;save.disabled=true;apply.disabled=true;message('js.brand.saving');
    try{
      var response=await fetch('/app/posts/brand-profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      var result=await response.json();if(!response.ok||!result.success)throw new Error('save failed');
      saved=result.data;data.textContent=JSON.stringify(saved);apply.hidden=false;
      var fields={};names.forEach(function(name){fields[name]=saved[name];});fields.use_macaron=saved.use_macaron;
      baseline=JSON.stringify(fields);
      message(JSON.stringify(current())===baseline&&auto.checked===saved.auto_apply?'js.brand.saved':'js.brand.unsaved');
    }catch(error){message('js.brand.error',true);}
    finally{save.disabled=false;apply.disabled=false;}
  });
})();
