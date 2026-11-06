(function(){
  'use strict';
  var form=document.getElementById('ideasForm'),host=document.getElementById('creationOptions'),accordion;
  if(!form||!host)return;
  if(window.ej&&ej.navigations&&ej.navigations.Accordion){
    try{
      // Materialize both panels before legacy form controllers bind their fields.
      accordion=new ej.navigations.Accordion({expandMode:'Multiple',expandedIndices:[0,1],enableRtl:window.__DIR==='rtl',animation:{expand:{effect:'None'},collapse:{effect:'None'}}});
      accordion.appendTo(host);
      requestAnimationFrame(function(){accordion.expandItem(false,0);accordion.expandItem(false,1);});
    }catch(error){if(accordion)try{accordion.destroy();}catch(ignore){}accordion=null;}
  }
  form.querySelectorAll('.field').forEach(function(field,index){
    var label=field.querySelector('label'),control=field.querySelector('input:not([type=hidden]),select,textarea');
    if(!label||!control)return;
    if(!control.id)control.id='creation-field-'+index;
    if(!label.htmlFor)label.htmlFor=control.id;
    var hint=field.querySelector('.hint'),error=field.querySelector('.error'),described=[];
    if(hint){if(!hint.id)hint.id=control.id+'-hint';described.push(hint.id);}
    if(error){if(!error.id)error.id=control.id+'-error';described.push(error.id);error.setAttribute('aria-live','polite');}
    if(described.length)control.setAttribute('aria-describedby',described.join(' '));
  });
  function reveal(field,focus){
    if(!field)return;
    var item=field.closest('.e-acrdn-item');
    if(item&&accordion){var index=Array.from(host.querySelectorAll(':scope > .e-acrdn-item')).indexOf(item);if(index>=0)accordion.expandItem(true,index);}
    if(focus){var control=field.querySelector('input:not([type=hidden]),select,textarea');if(control)control.focus();field.scrollIntoView({behavior:'auto',block:'center'});}
  }
  form.addEventListener('invalid',function(event){reveal(event.target.closest('.field'),false);},true);
  form.addEventListener('pg:creation-errors',function(){reveal(form.querySelector('.isInvalid'),true);});
  window.addEventListener('pagehide',function(){if(accordion)accordion.destroy();});
})();
