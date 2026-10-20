const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
class Element {
  constructor(){this.children=[];this.style={};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
}
function fixture(callWS,type='pivot-task-card',browser={}){
  const cards=new Map();
  vm.runInNewContext(fs.readFileSync('custom_components/pivot/www/pivot-task-card.js','utf8'),{
    window:browser,URL,clearTimeout,HTMLElement:Element,document:{createElement:()=>new Element(),createTextNode:text=>({textContent:text})},
    customElements:{get:name=>cards.get(name),define:(name,value)=>cards.set(name,value)}
  });
  const card=new (cards.get(type))();card._hass={callWS:async message=>message.type==='pivot/link_status'?{installation_ready:true,linked:true,ha_name:'Synthetic',subject:'synthetic-a'}:callWS(message),user:{id:'synthetic-a'}};return card;
}
test('HA card uses opaque UUID and version, safe title text, refresh after confirmed completion',async()=>{
  const calls=[];const item={id:'synthetic-task',title:'<img src=x onerror=secret()>',version:7,status:'active',ownership:{mode:'together'}};
  const card=fixture(async message=>{calls.push(message);return {items:[item]};});
  await card.refresh();const row=card.children[0].children[0].children.find(e=>e.children[0]?.textContent===item.title+' (together) ');
  assert.equal(row.children[0].textContent,item.title+' (together) ');
  await row.children[1].onclick();
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1])),{type:'pivot/complete',task_id:item.id,etag:'"task-synthetic-task-v7"'});
  assert.equal(calls[2].type,'pivot/tasks');
});
test('HA card does not retry uncertain completion or report success; disconnect clears tasks',async()=>{
  let writes=0;
  const card=fixture(async message=>{if(message.type==='pivot/complete'){writes++;throw Error('synthetic timeout');}return {items:[{id:'synthetic',title:'Synthetic task',version:1,status:'active',ownership:{mode:'individual'}}]};});
  await card.refresh();const button=card.children[0].children[0].children.find(e=>e.children[1]?.textContent==='Complete').children[1];
  await button.onclick();assert.equal(writes,1);assert.equal(button.textContent,'Refresh to check result');assert.equal(button.disabled,true);
  card.disconnectedCallback();assert.equal(card.children.length,0);
});


test('HACS bundled card matches the manually installed card',()=>{
  assert.equal(fs.readFileSync('custom_components/pivot/www/pivot-task-card.js','utf8'),fs.readFileSync('custom_components/pivot/www/pivot-task-card.js','utf8'));
});

test('linking shows identity and scope before explicit confirmation; no task data before linking',async()=>{
  const calls=[];
  const card=fixture(async()=>({}));
  card._hass.callWS=async message=>{
    calls.push(message);
    if(message.type==='pivot/link_status')return {installation_ready:true,linked:false,pending:true,locator:'synthetic-locator',ha_name:'Synthetic person',subject:'synthetic-a'};
    if(message.action==='inspect')return {pairing:{status:'approved',approvedUserId:'synthetic-pivot',consentId:'synthetic-consent',policy:{read:true,complete:false,expiresAt:1}},approved_user_name:'Synthetic Pivot person'};
    return {linked:true};
  };
  await card.refresh();
  assert.equal(calls.some(c=>c.type==='pivot/tasks'),false);
  const body=card.children[0].children[0];
  assert.ok(calls.some(c=>c.action==='inspect'));
  assert.equal(calls.some(c=>c.action==='finish'),false);
  assert.ok(body.children.some(c=>c.textContent?.includes('synthetic-pivot')));
  const confirm=body.children.find(c=>c.textContent==='Confirm these accounts and permissions');
  await confirm.onclick();
  const finish=calls.find(c=>c.action==='finish');
  assert.deepEqual(JSON.parse(JSON.stringify(finish.confirmation)),{userId:'synthetic-pivot',consentId:'synthetic-consent'});
  assert.equal(JSON.stringify(calls).includes('credential'),false);
});


test('dashboard ranks priorities and maps planning dates to calendar without HTML injection',async()=>{
 const items=[{id:'low',title:'Low',priority:5,targetFinishDate:'2031-04-15',status:'active',ownership:{mode:'individual'}},{id:'high',title:'<script>synthetic</script>',priority:1,targetFinishDate:'2031-04-03',status:'active',ownership:{mode:'individual'}},{id:'done',title:'Done',status:'completed',ownership:{mode:'individual'}}];
 const card=fixture(async()=>({items}),'pivot-dashboard-card');card.month=3;card.year=2031;await card.refresh();
 const body=card.children[0].children[0],grid=body.children.find(e=>e.className==='pivot-grid');
 assert.equal(grid.children[0].children[2].children[0].textContent,items[1].title);
 const days=grid.children[1].children.find(e=>e.className==='pivot-days');
 const dated=days.children.filter(e=>e.className==='pivot-day');
 assert.equal(dated[2].children[1].textContent,items[1].title);assert.equal(dated[14].children[1].textContent,'Low');
 assert.equal(grid.children[2].children.length,3);assert.equal(grid.children[3].children[1].textContent,'Done');
 card.disconnectedCallback();assert.equal(card.children.length,0);
});
test('an earlier account response cannot repopulate the dashboard after switching account',async()=>{
 let release;const card=fixture(()=>new Promise(resolve=>{release=resolve;}),'pivot-dashboard-card');
 const pending=card.refresh();await new Promise(resolve=>setImmediate(resolve));
 card._hass={user:{id:'synthetic-b'},callWS:async()=>({installation_ready:true,linked:false,ha_name:'Other',subject:'synthetic-b'})};await card.refresh();
 release({items:[{title:'Previous account private task'}]});await pending;
 const all=e=>[e.textContent||'',...(e.children||[]).flatMap(all)];assert.equal(all(card).join(' ').includes('Previous account private task'),false);
});
test('missing integration commands show setup instructions without exposing raw errors',async()=>{
 const card=fixture(async()=>({}));card._hass.callWS=async()=>{throw {code:'unknown_command',message:'synthetic-sensitive-value'};};await card.refresh();
 const body=card.children[0].children[0];const messages=body.children.map(e=>e.textContent||'').join(' ');
 assert.ok(messages.includes('restart Home Assistant'));assert.equal(messages.includes('synthetic-sensitive-value'),false);
});


test('Connect navigates to approval and a fresh dashboard automatically finishes before displaying Connected',async()=>{
  let assigned,cleared,connected=false;const calls=[];
  const locator='hl1.'+'L'.repeat(43),state='S'.repeat(43),context='C'.repeat(80),result='R'.repeat(100),pairingId='11111111-1111-4111-8111-111111111111';
  const browser={location:{protocol:'https:',origin:'https://ha.example.invalid',hash:'',assign:url=>{assigned=url;}}};
  const card=fixture(async()=>({}),'pivot-dashboard-card',browser);
  const account={installation_ready:true,linked:false,pending:false,website_url:'https://pivot.example.invalid',subject:'synthetic-a'};
  card._hass.callWS=async message=>{calls.push(message);if(message.type==='pivot/link_status')return account;if(message.action==='start_return')return {locator,state,returnContext:context};return {};};
  await card.refresh();
  await card.children[0].children[0].children.find(e=>e.textContent==='Connect Pivot account').onclick();
  assert.equal(assigned,'https://pivot.example.invalid/#settings/ha/'+locator+'/'+state+'/'+context);
  assert.deepEqual(JSON.parse(JSON.stringify(calls.find(c=>c.action==='start_return').browser_return)),{returnUrl:'https://ha.example.invalid/pivot-tasks/tasks'});
  const returning={location:{hash:'#pivot-return/'+pairingId+'/'+state+'/'+result,pathname:'/pivot-tasks/tasks',search:''},history:{replaceState(){cleared=true;returning.location.hash='';}}};
  const next=fixture(async()=>({}),'pivot-dashboard-card',returning);
  next._hass.callWS=async message=>{
    calls.push(message);
    if(message.action==='finish_return'){assert.equal(cleared,true);assert.equal(message.browser_return.state,state);connected=true;return {linked:true};}
    if(message.type==='pivot/link_status')return {...account,linked:connected};
    if(message.type==='pivot/tasks')return {items:[]};return {};
  };
  await next.refresh();
  assert.ok(next.children[0].children[0].children.some(e=>e.textContent==='Connected'));
  assert.equal(calls.filter(c=>c.action==='finish_return').length,1);
  assert.equal(calls.some(c=>c.action==='finish'),false);
  await next.refresh();assert.equal(calls.filter(c=>c.action==='finish_return').length,1);
});

test('a rejected automatic return never displays Connected or requests private tasks',async()=>{
  const calls=[];const browser={location:{hash:'#pivot-return/11111111-1111-4111-8111-111111111111/'+'S'.repeat(43)+'/'+'R'.repeat(80),pathname:'/pivot-tasks/tasks',search:''},history:{replaceState(){}}};
  const card=fixture(async()=>({}),'pivot-dashboard-card',browser);
  card._hass.callWS=async message=>{calls.push(message);throw {code:'link_failed'};};
  await card.refresh();assert.equal(calls.length,1);assert.equal(calls[0].action,'finish_return');
  assert.equal(card.children[0].children[0].children.some(e=>e.textContent==='Connected'),false);
  assert.equal(calls.some(c=>c.type==='pivot/tasks'),false);
});
