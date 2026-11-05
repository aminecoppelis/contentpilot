(function(){
  'use strict';
  function finishLoading(){
    clearTimeout(window.__PG_GRID_BOOT_TIMER);
    document.documentElement.classList.remove('pg-grid-loading');
  }
  if(!window.ej||!ej.grids||!window.__PG_SYNCFUSION||window.__PG_SYNCFUSION_FAILED){finishLoading();return;}
  ej.grids.Grid.Inject(ej.grids.Filter,ej.grids.Sort,ej.grids.Page,ej.grids.Resize,
    ej.grids.Reorder,ej.grids.Toolbar,ej.grids.Search,ej.grids.ColumnChooser,ej.grids.ColumnMenu);
  var instances=[];
  function label(key){return window.t?window.t(key):key;}
  function text(cell){
    var clone=cell.cloneNode(true);
    clone.querySelectorAll('.mini,script,style,[aria-hidden="true"]').forEach(function(node){node.remove();});
    return String(clone.textContent||'').trim().replace(/\s+/g,' ');
  }
  function record(row,index,headers){
    var data={__key:String(index),__row:row,__cells:[],__attributes:{}};
    Array.from(row.attributes).forEach(function(attr){if(attr.name!=='id')data.__attributes[attr.name]=attr.value;});
    data.__rowId=row.id;if(row.id)row.removeAttribute('id');
    Array.from(row.cells).forEach(function(cell,i){
      data.__cells.push(Array.from(cell.childNodes));
      var value=cell.getAttribute('data-grid-value')||text(cell);
      data['c'+i]=value!==''&&/^\d+(\.\d+)?$/.test(value)?Number(value):value;
    });
    return data;
  }
  function restore(table,rows){
    rows.forEach(function(data){
      if(data.__rowId)data.__row.id=data.__rowId;
      data.__cells.forEach(function(nodes,i){nodes.forEach(function(node){data.__row.cells[i].appendChild(node);});});
    });
    table.hidden=false;
  }
  function enhance(table,index){
    if(table.dataset.gridReady)return;
    var headers=Array.from(table.tHead?table.tHead.rows[0].cells:[]);
    if(!headers.length||!table.tBodies.length)return;
    var tracker=window.pgTablePreferences?window.pgTablePreferences.create(table.dataset.gridView,headers.length):null;
    var saved=tracker&&tracker.saved;
    var resetting=false;
    var rows=Array.from(table.tBodies[0].rows).filter(function(row){return row.cells.length===headers.length&&!row.querySelector('td[colspan]');});
    var records=rows.map(function(row,i){return record(row,i,headers);});
    var views=new Map(records.map(function(data){return [data.__key,data];}));
    var dataSource=records.map(function(data){var plain={__key:data.__key};headers.forEach(function(header,i){plain['c'+i]=data['c'+i];});return plain;});
    var wrapper=document.createElement('div');wrapper.id='pg-grid-'+index;wrapper.className='pgSyncfusionGrid';
    var parent=table.parentElement;parent.insertBefore(wrapper,table);table.hidden=true;
    var columns=headers.map(function(header,i){
      var isControl=header.querySelector('input[type="checkbox"]');
      var action=i===headers.length-1&&records.some(function(data){return data.__cells[i].some(function(node){return node.nodeType===1&&(node.matches('a,button,form')||node.querySelector('a,button,form'));});});
      var title=String(header.textContent||'').trim();
      var numeric=records.length>0&&records.every(function(data){return typeof data['c'+i]==='number';});
      var column={field:'c'+i,headerText:title,type:numeric?'number':'string',width:isControl?55:(action?240:(i===0?280:175)),minWidth:70,
        allowFiltering:!action&&!isControl,allowSorting:!action&&!isControl,allowSearching:!action&&!isControl,
        showInColumnChooser:!isControl,textAlign:numeric?'Right':'Left'};
      if(isControl){
        column.__headerIndex=i;
        var headerNodes=Array.from(header.childNodes);
        column.headerTemplate=function(){var element=document.createElement('span');headerNodes.forEach(function(node){element.appendChild(node);});return [element];};
        column.__headerNodes=headerNodes;
      }
      // The original nodes retain form listeners, checkbox state and safely escaped server markup.
      column.template=function(data){var element=document.createElement('div');element.className='pgGridCell';((views.get(String(data.__key))||{}).__cells[i]||[]).forEach(function(node){element.appendChild(node);});return [element];};
      return column;
    });
    var defaultColumns=columns.map(function(column){return Object.assign({},column);});
    if(saved){
      var byField=new Map(columns.map(function(column){return [column.field,column];})),ordered=[];
      (saved.columns||[]).forEach(function(state){var column=byField.get(state.field);if(!column)return;column.width=state.width;column.visible=column.__headerNodes?true:state.visible;ordered.push(column);byField.delete(state.field);});
      columns=ordered.concat(Array.from(byField.values()));
    }
    columns.unshift({field:'__key',isPrimaryKey:true,visible:false,showInColumnChooser:false});
    defaultColumns.unshift({field:'__key',isPrimaryKey:true,visible:false,showInColumnChooser:false});
    var filterable=new Set(columns.filter(function(column){return column.allowFiltering!==false;}).map(function(column){return column.field;}));
    var sortable=new Set(columns.filter(function(column){return column.allowSorting!==false;}).map(function(column){return column.field;}));
    try{
      var grid=new ej.grids.Grid({
        dataSource:dataSource,columns:columns,locale:window.__LOCALE||'fr',enableRtl:window.__DIR==='rtl',
        allowSorting:true,allowMultiSorting:true,allowFiltering:true,filterSettings:{type:'Excel',ignoreAccent:true,columns:saved?(saved.filters||[]).filter(function(f){return filterable.has(f.field);}):[]},
        sortSettings:{columns:saved?(saved.sort||[]).filter(function(s){return sortable.has(s.field);}):[]},
        allowPaging:true,pageSettings:{pageSize:saved?saved.pageSize:10,pageSizes:[10,20,50,100],pageCount:5},
        allowResizing:true,allowReordering:true,showColumnChooser:true,showColumnMenu:true,
        allowSelection:false,enablePersistence:false,gridLines:'Horizontal',
        toolbar:['Search','ColumnChooser',{id:wrapper.id+'-reset',text:label('js.grid.reset'),prefixIcon:'e-icons e-refresh'}],
        searchSettings:{key:saved?saved.search:'',ignoreCase:true,ignoreAccent:true,fields:columns.filter(function(c){return c.allowSearching!==false&&c.field!=='__key';}).map(function(c){return c.field;})},
        toolbarClick:async function(args){if(args.item.id===wrapper.id+'-reset'){
          resetting=true;
          grid.setProperties({columns:defaultColumns.map(function(column){return Object.assign({},column);}),filterSettings:{columns:[]},sortSettings:{columns:[]},searchSettings:{key:''},pageSettings:{pageSize:10,currentPage:1}});
          if(tracker){var savedReset=await tracker.reset(grid);if(savedReset)tracker.clearPageFilters();}
          resetting=false;
        }},
        actionComplete:function(){if(tracker&&!resetting)tracker.changed(grid);},
        resizeStop:function(){if(tracker&&!resetting)tracker.changed(grid);},
        rowDataBound:function(args){var view=views.get(String(args.data.__key));if(!view)return;if(view.__rowId)args.row.id=view.__rowId;Object.keys(view.__attributes).forEach(function(name){if(name!=='class')args.row.setAttribute(name,view.__attributes[name]);});},
        dataBound:function(){document.dispatchEvent(new CustomEvent('pg:grid-data-bound',{detail:{element:wrapper,grid:grid}}));if(tracker&&!resetting)tracker.changed(grid);},
        actionFailure:function(){if(window.pgToast)window.pgToast(label('js.grid.error'),'error');}
      });
      grid.appendTo(wrapper);
      table.dataset.gridReady='true';table.remove();
      var bodyId=table.tBodies[0].id;
      instances.push({grid:grid,element:wrapper,table:table,records:records,bodyId:bodyId});
      document.dispatchEvent(new CustomEvent('pg:grid-ready',{detail:{element:wrapper,grid:grid,bodyId:bodyId}}));
    }catch(error){
      if(grid)try{grid.destroy();}catch(ignore){}
      columns.forEach(function(column){if(column.__headerNodes)column.__headerNodes.forEach(function(node){headers[column.__headerIndex].appendChild(node);});});
      wrapper.remove();restore(table,records);table.dataset.syncfusion='failed';
      if(window.pgToast)window.pgToast(label('js.grid.error'),'error');
    }
  }
  window.pgRemoveGridRow=function(row){
    var entry=instances.find(function(item){return item.element.contains(row);});
    if(!entry)return false;
    var data=entry.grid.getRowInfo(row).rowData;
    if(!data)return false;
    entry.grid.dataSource=entry.grid.dataSource.filter(function(item){return item.__key!==data.__key;});entry.grid.refresh();return true;
  };
  async function start(){
    var navigating=false;
    try{
      var preferencesReady=window.pgTablePreferences?window.pgTablePreferences.load():Promise.resolve();
      var locale=window.__LOCALE||'fr';
      var controller=new AbortController();
      var localeTimeout=setTimeout(function(){controller.abort();},4000);
      try{
        var response=await fetch('/static/vendor/syncfusion/locales/'+locale+'.json',{signal:controller.signal});
        if(response.ok)ej.base.L10n.load(await response.json());
      }catch(ignore){}finally{clearTimeout(localeTimeout);}
      await preferencesReady;
      var tables=Array.from(document.querySelectorAll('table[data-syncfusion="true"]'));
      if(window.pgTablePreferences&&window.pgTablePreferences.restorePageFilters(tables)){navigating=true;return;}
      tables.forEach(enhance);
      if(instances.length){
        document.querySelectorAll('[data-server-pagination]').forEach(function(nav){nav.hidden=true;});
      }
    }finally{
      if(!navigating){finishLoading();if(window.pgInitPagination)window.pgInitPagination();}
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
