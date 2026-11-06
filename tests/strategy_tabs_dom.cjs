const fs=require('fs'),assert=require('node:assert/strict');
const {JSDOM}=require('../.cache/grid-tests/node_modules/jsdom');
const names=['summary','actions','posts','calendar'];
for(const dir of ['ltr','rtl']){
  const dom=new JSDOM(`<html dir="${dir}"><body><section class="strategyWorkspace" data-strategy-id="test"><div class="strategyDetailTabs">${names.map(n=>`<button data-strategy-tab="${n}">${n}</button>`).join('')}</div>${names.map(n=>`<section data-strategy-panel="${n}"></section>`).join('')}</section></body></html>`,{url:'http://localhost/app/strategies?strategy_id=test#posts',runScripts:'outside-only'});
  const w=dom.window;w.t=k=>k;w.pgToast=()=>{};
  w.eval(fs.readFileSync('static/js/strategies.js','utf8'));
  const tab=n=>w.document.querySelector(`[data-strategy-tab=${n}]`),panel=n=>w.document.querySelector(`[data-strategy-panel=${n}]`);
  assert.equal(tab('posts').getAttribute('aria-selected'),'true','Post deep link restored');
  assert(!panel('posts').hidden);assert(panel('actions').hidden);
  assert.equal(panel('posts').getAttribute('aria-labelledby'),tab('posts').id);
  assert.equal(tab('posts').getAttribute('aria-controls'),panel('posts').id);
  tab('posts').dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
  const target=dir==='rtl'?'actions':'calendar';
  assert.equal(w.document.activeElement,tab(target));assert(!panel(target).hidden);
  assert.equal(w.document.querySelectorAll('[data-strategy-tab][tabindex="0"]').length,1);
  tab(target).dispatchEvent(new w.KeyboardEvent('keydown',{key:'Home',bubbles:true}));
  assert.equal(w.location.hash,'#summary');assert(!panel('summary').hidden);
  w.close();
}
console.log('PASS: strategy post deep link, accessible tabs, keyboard navigation and RTL');
