(function(){
  'use strict';
  function openRow(event){
    if(event.defaultPrevented)return;
    var target=event.target&&event.target.closest?event.target:null;
    if(!target||target.closest('a,button,input,select,textarea,label,summary,form,[role="button"],[contenteditable="true"],[data-no-row-navigation]'))return;
    var row=target.closest('tr[data-row-url]');if(!row)return;
    if(event.type==='keydown'&&(event.key!=='Enter'||target!==row))return;
    if(event.type==='click'&&(event.button!==0||String(window.getSelection()||'').trim()))return;
    var url=new URL(row.dataset.rowUrl,location.href);
    if(url.origin!==location.origin)return;
    event.preventDefault();
    if(event.ctrlKey||event.metaKey)window.open(url.href,'_blank','noopener');
    else location.assign(url.href);
  }
  document.addEventListener('click',openRow);
  document.addEventListener('keydown',openRow);
})();
