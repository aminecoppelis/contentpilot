(function(){
  'use strict';
  var labels=['write','media','review'];
  function t(name){return window.t('js.post_flow.'+name);}
  function init(card){
    if(card.dataset.flowReady)return;
    var index=Number(card.dataset.ideaIndex),current=Number(card.dataset.flowStep||0),busy=false,syncing=false,stepper;
    var previous=card.querySelector('[data-flow-previous]'),next=card.querySelector('[data-flow-next]');
    function render(){
      card.dataset.flowStep=String(current);
      previous.hidden=current===0;next.hidden=current===2;
      previous.textContent=current>0?t(labels[current-1]):window.t('common.previous');
      next.textContent=current<2?t(labels[current+1]):window.t('common.next');
      card.querySelector('[data-flow-hint]').textContent=t(labels[current]+'_hint');
      card.querySelectorAll('[data-flow-go]').forEach(function(button){if(Number(button.dataset.flowGo)===current)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');});
      if(stepper&&stepper.activeStep!==current){syncing=true;try{stepper.activeStep=current;stepper.dataBind();}finally{syncing=false;}}
      if(current===2&&window.updatePostPhonePreview)window.updatePostPhonePreview(index);
    }
    async function go(target,focus){
      if(busy||target===current||target<0||target>2)return;
      var editor=document.getElementById('copy-'+index);
      if(target>current&&(!editor||!editor.value.trim())){if(window.pgToast)window.pgToast(t('empty'),'error');if(editor)editor.focus();return;}
      busy=true;card.querySelectorAll('[data-flow-go],[data-flow-next],[data-flow-previous]').forEach(function(b){b.disabled=true;});
      try{
        if(current===0&&target>0&&window.savePostEdit&&await window.savePostEdit(index)===false){if(window.pgToast)window.pgToast(window.t('js.cons.save_failed'),'error');return;}
        current=target;render();
        if(focus){var element=current===0?editor:(current===1?card.querySelector('.mediaSection button'):card.querySelector('[id^="publish-btn-"]'));if(element)element.focus({preventScroll:true});card.scrollIntoView({behavior:'smooth',block:'start'});}
      }finally{busy=false;card.querySelectorAll('[data-flow-go],[data-flow-next],[data-flow-previous]').forEach(function(b){b.disabled=false;});}
    }
    card.querySelectorAll('[data-flow-go]').forEach(function(button){button.onclick=function(){go(Number(button.dataset.flowGo),true);};});
    previous.onclick=function(){go(current-1,true);};next.onclick=function(){go(current+1,true);};
    var host=card.querySelector('[data-flow-stepper]');
    if(window.ej&&ej.navigations&&ej.navigations.Stepper){
      try{
        host.hidden=false;
        stepper=new ej.navigations.Stepper({activeStep:current,linear:false,enableRtl:window.__DIR==='rtl',
          steps:labels.map(function(label,i){return {text:String(i+1),label:t(label)};}),
          stepChanging:function(args){if(!syncing){args.cancel=true;go(args.activeStep,true);}}
        });
        stepper.appendTo(host);card.__postFlowStepper=stepper;card.querySelector('[data-flow-fallback]').hidden=true;
      }catch(error){host.hidden=true;stepper=null;}
    }
    render();
    card.dataset.flowReady='true';
  }
  try{
    document.querySelectorAll('[data-post-flow]').forEach(init);clearTimeout(window.__PG_POST_FLOW_TIMER);
    var grid=document.getElementById('posts-view-grid');
    if(grid)new MutationObserver(function(changes){
      changes.forEach(function(change){change.removedNodes.forEach(function(node){if(node.__postFlowStepper)try{node.__postFlowStepper.destroy();}catch(ignore){}});});
      grid.querySelectorAll('[data-post-flow]:not([data-flow-ready])').forEach(init);
    }).observe(grid,{childList:true});
  }
  catch(error){document.documentElement.classList.remove('pg-post-flow');}
})();
