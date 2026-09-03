/* Port VERBATIM du composant pgTextareaLimitScript partagé :
   compteur de caractères et troncature automatique, avec les limites
   exactes par id/nom de champ du workflow original. */
(function(){
if(window.__pgTextareaLimitsInstalled)return;window.__pgTextareaLimitsInstalled=true;
var DEFAULT_LIMIT=2000;
var LIMITS={
  themeInput:3500,
  modalVideoScenarioText:3500,
  videoFirstFrameInstructions:1000,
  mediaInstructions:1200,
  modalInstructions:1200,
  publishPostPreview:3000
};
var NAME_LIMITS={
  theme:3500,
  prompt:3500,
  constraints:900,
  subject:300,
  facebook_scopes:1800,
  instagram_scopes:1800
};
function closestLimit(textarea){
  if(!textarea||textarea.readOnly||textarea.disabled)return null;
  var explicit=Number(textarea.getAttribute('data-char-limit')||textarea.getAttribute('data-maxlength')||textarea.getAttribute('maxlength')||0);
  if(Number.isFinite(explicit)&&explicit>0)return Math.floor(explicit);
  var id=String(textarea.id||'');
  var name=String(textarea.name||'');
  var cls=String(textarea.className||'');
  if(id&&LIMITS[id])return LIMITS[id];
  if(name&&NAME_LIMITS[name])return NAME_LIMITS[name];
  if(cls.indexOf('copyBox')!==-1)return 3000;
  if(/scenario|video/i.test(id+' '+name+' '+cls))return 3500;
  if(/instruction|comment|note|reason/i.test(id+' '+name+' '+cls))return 1200;
  return DEFAULT_LIMIT;
}
function counterId(textarea){
  if(!textarea.__pgCharCounterId){textarea.__pgCharCounterId='pg-char-counter-'+Math.random().toString(36).slice(2);}return textarea.__pgCharCounterId;
}
function countChars(value){return String(value||'').length;}
function ensureCounter(textarea,limit){
  var next=textarea.nextElementSibling;
  if(next&&next.classList&&next.classList.contains('pgCharCounter'))return next;
  var c=document.createElement('div');
  c.className='pgCharCounter';
  c.id=counterId(textarea);
  c.setAttribute('aria-live','polite');
  textarea.insertAdjacentElement('afterend',c);
  try{textarea.setAttribute('aria-describedby',((textarea.getAttribute('aria-describedby')||'')+' '+c.id).trim());}catch(e){}
  return c;
}
function updateCounter(textarea){
  var limit=closestLimit(textarea);
  if(!limit)return;
  if(!textarea.hasAttribute('maxlength'))textarea.setAttribute('maxlength',String(limit));
  var counter=ensureCounter(textarea,limit);
  var used=countChars(textarea.value);
  var remaining=limit-used;
  var over=remaining<0;
  counter.className='pgCharCounter'+(over?' error':(remaining<=Math.max(20,Math.round(limit*.1))?' warn':''));
  textarea.classList.toggle('pgTextareaLimitExceeded',over);
  counter.textContent=used+' / '+limit;
}
function enforceLimit(textarea){
  var limit=closestLimit(textarea);
  if(!limit)return;
  if(countChars(textarea.value)>limit){
    var start=textarea.selectionStart||limit;
    textarea.value=String(textarea.value||'').slice(0,limit);
    try{textarea.setSelectionRange(Math.min(start,limit),Math.min(start,limit));}catch(e){}
  }
  updateCounter(textarea);
}
function bind(textarea){
  if(!textarea||textarea.__pgTextareaLimitBound)return;
  var limit=closestLimit(textarea);
  if(!limit)return;
  textarea.__pgTextareaLimitBound=true;
  if(!textarea.hasAttribute('maxlength'))textarea.setAttribute('maxlength',String(limit));
  updateCounter(textarea);
  textarea.addEventListener('input',function(){enforceLimit(textarea);});
  textarea.addEventListener('paste',function(){setTimeout(function(){enforceLimit(textarea);},0);});
  textarea.addEventListener('change',function(){enforceLimit(textarea);});
}
function bindAll(root){
  root=root||document;
  var nodes=[];
  if(root.matches&&root.matches('textarea'))nodes=[root];
  else nodes=Array.prototype.slice.call(root.querySelectorAll?root.querySelectorAll('textarea'):[]);
  nodes.forEach(bind);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',function(){bindAll(document);});else bindAll(document);
try{
  new MutationObserver(function(mutations){
    mutations.forEach(function(m){Array.prototype.forEach.call(m.addedNodes||[],function(node){if(node&&node.nodeType===1)bindAll(node);});});
  }).observe(document.documentElement,{childList:true,subtree:true});
}catch(e){}
})();