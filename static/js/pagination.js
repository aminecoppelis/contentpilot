(function(){
  'use strict';
  var DEFAULT_SIZE=10;

  function label(key,fallback,params){
    var value=window.t?window.t(key,params):key;
    return value&&value!==key?value:fallback;
  }

  function createButton(text,page,disabled,current){
    var button=document.createElement('button');
    button.type='button';
    button.className='pgPaginationButton'+(current?' isCurrent':'');
    button.textContent=text;
    button.disabled=Boolean(disabled);
    button.dataset.page=String(page);
    if(current)button.setAttribute('aria-current','page');
    return button;
  }

  function enhance(container,selector){
    if(!container||container.dataset.paginationReady==='true')return;
    container.dataset.paginationReady='true';
    var page=1;
    var size=Math.max(1,Number(container.dataset.pageSize||DEFAULT_SIZE));
    var navigation=document.createElement('nav');
    navigation.className='pgPagination';
    navigation.setAttribute('aria-label',label('js.pagination.label','Pagination'));
    var info=document.createElement('span');
    info.className='pgPaginationInfo';
    var buttons=document.createElement('div');
    buttons.className='pgPaginationButtons';
    navigation.appendChild(info);navigation.appendChild(buttons);
    var anchor=container.closest('.tableWrap')||container;
    anchor.insertAdjacentElement('afterend',navigation);

    function items(){
      return Array.prototype.slice.call(container.querySelectorAll(selector)).filter(function(item){
        return !(item.tagName==='TR'&&item.children.length===1&&item.children[0].hasAttribute('colspan'));
      });
    }
    function render(){
      var rows=items();
      var pages=Math.max(1,Math.ceil(rows.length/size));
      page=Math.min(page,pages);
      rows.forEach(function(row,index){row.hidden=index<(page-1)*size||index>=page*size;});
      navigation.hidden=rows.length<=size;
      if(navigation.hidden)return;
      var first=(page-1)*size+1,last=Math.min(page*size,rows.length);
      info.textContent=label('js.pagination.range',first+'–'+last+' / '+rows.length,{first:first,last:last,total:rows.length});
      buttons.innerHTML='';
      buttons.appendChild(createButton('‹',page-1,page===1,false));
      var start=Math.max(1,Math.min(page-2,pages-4));
      var end=Math.min(pages,start+4);
      for(var number=start;number<=end;number++)buttons.appendChild(createButton(String(number),number,false,number===page));
      buttons.appendChild(createButton('›',page+1,page===pages,false));
    }
    buttons.addEventListener('click',function(event){
      var button=event.target.closest('[data-page]');
      if(!button||button.disabled)return;
      page=Math.max(1,Number(button.dataset.page||1));render();
      var top=(container.closest('.tableWrap')||container).getBoundingClientRect().top+window.scrollY-100;
      if(window.scrollY>top)window.scrollTo({top:top,behavior:'smooth'});
    });
    var timer;
    new MutationObserver(function(){clearTimeout(timer);timer=setTimeout(render,30);}).observe(container,{childList:true});
    render();
  }

  function init(){
    document.querySelectorAll('.tableWrap table tbody').forEach(function(body){enhance(body,':scope > tr');});
    document.querySelectorAll('[data-paginate-items]').forEach(function(container){
      enhance(container,container.dataset.paginateItems||':scope > *');
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
