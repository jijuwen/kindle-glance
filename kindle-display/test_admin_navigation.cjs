// Execute the real app controller against a small DOM/network harness.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function element(){return {children:[],dataset:{},textContent:'',hidden:false,disabled:false,
  classList:{toggle(){},add(){},remove(){}},append(...nodes){this.children.push(...nodes)},appendChild(node){this.append(node)},
  replaceChildren(...nodes){this.children=nodes},after(){},setAttribute(){},removeAttribute(){},focus(){},remove(){},
  querySelector(){return element()},querySelectorAll(){return []},addEventListener(){}};}
const nodes = new Map();
const node = id => {if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
node('bootstrap').textContent=JSON.stringify({settings:{timezone:'UTC'}});
const docEvents={},winEvents={},location={origin:'http://test.local',href:'http://test.local/admin/settings',reload(){throw Error('Unexpected full reload')}};
const document={body:{dataset:{view:'settings'}},hidden:false,getElementById:node,
  createElement:element,querySelector(){return {content:'test-csrf'}},querySelectorAll(){return []},addEventListener(type,fn){docEvents[type]=fn}};
let dirty=false,allowLeave=false,mounts=0,goCalls=[];
const history={state:null,replaceState(state,_,url){this.state=state;location.href=new URL(url,location.href).href;},
  pushState(state,_,url){this.replaceState(state,_,url)},go(delta){goCalls.push(delta)}};
const window={KindleSettings:{dispose(){},hasUnsavedChanges(){return dirty},async mount(){mounts++}},scrollTo(){},addEventListener(type,fn){winEvents[type]=fn}};
const payload={settings:{timezone:'UTC'},previews:{pages:[],total:0,ready:0,failed:0,active:false},
  playlist:{smart_skip:true},items:[],timeline:[],up_next:[],events:[],current:{},metrics:{},greeting:'准备中',playlist_count:0};
const context=vm.createContext({document,window,history,location,URL,Intl,Date,JSON,Map,Set,Promise,console,
  CSS:{escape:v=>v},confirm:()=>allowLeave,setTimeout(){return 1},clearTimeout(){},
  fetch:async()=>({ok:true,json:async()=>structuredClone(payload)})});
vm.runInContext(fs.readFileSync(__dirname+'/app/static/admin.js','utf8'),context);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function click(path){let prevented=false;docEvents.click({button:0,target:{closest(){return {href:'http://test.local'+path,hasAttribute(){return false}}}},preventDefault(){prevented=true}});assert.ok(prevented);}
(async()=>{
  await settle();assert.equal(mounts,1);
  dirty=true;click('/admin/playlist');await settle();assert.equal(document.body.dataset.view,'settings');
  assert.equal(history.state.kindleIndex,0);
  allowLeave=true;dirty=false;click('/admin/playlist');await settle();assert.equal(document.body.dataset.view,'playlist');
  assert.equal(history.state.kindleIndex,1);
  click('/admin/settings');await settle();assert.equal(document.body.dataset.view,'settings');
  dirty=true;allowLeave=false;winEvents.popstate({state:{view:'playlist',kindleIndex:1}});await settle();
  assert.deepEqual(goCalls,[1]);assert.equal(document.body.dataset.view,'settings');
  // The restoration event must not navigate or ask again.
  winEvents.popstate({state:{view:'settings',kindleIndex:2}});
  dirty=false;winEvents.popstate({state:{view:'playlist',kindleIndex:1}});await settle();
  assert.equal(document.body.dataset.view,'playlist');
  winEvents.popstate({state:{view:'settings',kindleIndex:2}});await settle();
  assert.equal(document.body.dataset.view,'settings');
  dirty=true;let prevented=false;winEvents.beforeunload({preventDefault(){prevented=true}});assert.ok(prevented);
  console.log('PASS: Dock navigation, unsaved cancellation, browser back/forward and reload protection.');
})().catch(error=>{console.error(error);process.exitCode=1});
