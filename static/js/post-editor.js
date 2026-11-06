(function(){
  'use strict';
  var grid=document.getElementById('posts-view-grid'),navigator=document.getElementById('postVariantNavigator');if(!grid||!navigator)return;
  var host=document.getElementById('postVariantToolbar'),fallback=document.getElementById('postVariantFallback'),toolbar;
  function cards(){return Array.from(grid.querySelectorAll(':scope > [data-idea-index]'));}
  function label(index){return window.t('js.editor.variant',{n:index+1});}
  function jump(card){card.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});card.tabIndex=-1;card.focus({preventScroll:true});}
  function update(){
    var entries=cards();navigator.hidden=entries.length<2;
    var links=entries.map(function(card,index){var link=document.createElement('a');link.href='#'+card.id;link.textContent=label(index);link.onclick=function(event){event.preventDefault();jump(card);};return link;});fallback.replaceChildren.apply(fallback,links);
    if(!window.ej||!ej.navigations||!ej.navigations.Toolbar)return;
    var items=entries.map(function(card,index){return {text:label(index),type:'Button',htmlAttributes:{'aria-controls':card.id,title:(card.querySelector('[id^="post-title-"]')||{}).textContent||label(index)},click:function(){jump(card);}};});
    try{if(toolbar){toolbar.items=items;toolbar.dataBind();}else{host.hidden=false;toolbar=new ej.navigations.Toolbar({items:items,overflowMode:'Scrollable',enableRtl:window.__DIR==='rtl'});toolbar.appendTo(host);}fallback.hidden=true;}
    catch(error){host.hidden=true;fallback.hidden=false;}
  }
  update();var observer=new MutationObserver(update);observer.observe(grid,{childList:true});
  window.addEventListener('pagehide',function(){observer.disconnect();if(toolbar)toolbar.destroy();});
})();
