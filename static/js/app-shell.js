(function(){
  'use strict';
  var sidebar=document.getElementById('pgSidebar');if(!sidebar)return;
  var root=document.documentElement,body=document.body,main=document.querySelector('.main-content');
  var desktop=document.getElementById('pgSidebarToggle'),mobile=document.querySelector('.pgMobileNavToggle'),overlay=document.getElementById('pgSidebarOverlay');
  var drawer=false,returnFocus=null;
  function isMobile(){return window.matchMedia('(max-width: 1024px)').matches;}
  function focusables(){return Array.from(sidebar.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),[tabindex="0"]')).filter(function(element){return !element.hidden&&window.getComputedStyle(element).display!=='none';});}
  function setDrawer(open,restore){
    drawer=!!open&&isMobile();body.classList.toggle('pg-sidebar-open',drawer);
    sidebar.inert=isMobile()&&!drawer;if(main)main.inert=drawer;
    if(mobile)mobile.setAttribute('aria-expanded',String(drawer));
    if(drawer){returnFocus=document.activeElement;var first=focusables()[0];if(first)first.focus();}
    else if(restore&&returnFocus&&returnFocus.isConnected)returnFocus.focus();
  }
  function collapsed(value){root.classList.toggle('pg-nav-collapsed',value);if(desktop)desktop.setAttribute('aria-expanded',String(!value));try{localStorage.setItem('pg_nav_collapsed',value?'1':'0');}catch(ignore){}}
  if(desktop){desktop.setAttribute('aria-expanded',String(!root.classList.contains('pg-nav-collapsed')));desktop.addEventListener('click',function(){if(isMobile())setDrawer(!drawer,true);else collapsed(!root.classList.contains('pg-nav-collapsed'));});}
  if(mobile)mobile.addEventListener('click',function(event){event.preventDefault();setDrawer(!drawer,true);});
  if(overlay)overlay.addEventListener('click',function(){setDrawer(false,true);});
  sidebar.querySelectorAll('a[href]').forEach(function(link){
    if(!link.title)link.title=link.textContent.trim();
    if(link.classList.contains('active'))link.setAttribute('aria-current','page');
    link.addEventListener('click',function(){if(drawer)setDrawer(false,false);});
  });
  document.addEventListener('keydown',function(event){
    if(!drawer)return;
    if(event.key==='Escape'){event.preventDefault();setDrawer(false,true);return;}
    if(event.key==='Tab'){
      var elements=focusables(),first=elements[0],last=elements[elements.length-1];if(!first)return;
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    }
  });
  window.addEventListener('resize',function(){if(!isMobile())setDrawer(false,false);else if(!drawer)sidebar.inert=true;});
  setDrawer(false,false);

  var host=document.getElementById('pgBreadcrumb'),fallback=document.getElementById('pgBreadcrumbFallback'),source=document.getElementById('pgBreadcrumbItems'),breadcrumb;
  if(host&&source&&window.ej&&ej.navigations&&ej.navigations.Breadcrumb){
    try{
      breadcrumb=new ej.navigations.Breadcrumb({items:JSON.parse(source.textContent),maxItems:3,overflowMode:'Menu',enableNavigation:true,enableActiveItemNavigation:false,enableRtl:window.__DIR==='rtl'});
      host.hidden=false;breadcrumb.appendTo(host);if(fallback)fallback.hidden=true;
    }catch(error){host.hidden=true;if(fallback)fallback.hidden=false;}
  }
  window.addEventListener('pagehide',function(){if(breadcrumb)breadcrumb.destroy();});
})();
