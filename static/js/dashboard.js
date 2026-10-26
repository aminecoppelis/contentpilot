(function(){
  var guide=document.getElementById('quickStart');
  if(!guide)return;
  var userId=String(guide.getAttribute('data-user-id')||'anonymous');
  var completed=Number(guide.getAttribute('data-completed')||0);
  var storageKey='pg_quick_start_hidden_'+userId;
  var hidden=false;
  try{hidden=localStorage.getItem(storageKey)==='1';}catch(_error){}
  if(completed>=4||hidden)guide.classList.add('isCollapsed');

  var hideButton=document.getElementById('quickStartHide');
  var openButton=document.getElementById('quickStartOpen');
  if(hideButton)hideButton.addEventListener('click',function(){
    guide.classList.add('isCollapsed');
    try{localStorage.setItem(storageKey,'1');}catch(_error){}
  });
  if(openButton)openButton.addEventListener('click',function(){
    guide.classList.remove('isCollapsed');
    try{localStorage.removeItem(storageKey);}catch(_error){}
    var title=document.getElementById('quickStartTitle');
    if(title)title.focus({preventScroll:true});
  });
})();
