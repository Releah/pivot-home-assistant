class PivotTaskCard extends HTMLElement {
  setConfig(config) { this.config = config; }
  set hass(value) { const changed=this._hass?.user?.id!==value.user?.id;if(changed)this.returnData=null;this._hass=value;if(!this.started||changed){this.started=true;this.refresh();} }
  connectedCallback() { if(this._hass)this.refresh(); }
  disconnectedCallback() { this.returnData=null;clearTimeout(this.pollTimer); this.generation=(this.generation||0)+1;this.replaceChildren();this.started=false; }
  element(tag,text) {const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
  button(body,text,action) {const b=this.element('button',text);b.onclick=async()=>{if(b.disabled)return;b.disabled=true;try{await action();}catch{body.replaceChildren(...[...body.children].filter(node=>node.textContent!=='Waiting for you to allow Home Assistant in Pivot…'));body.append(this.element('p','We couldn’t connect to Pivot. Please try again.'));if(text!=='Cancel')b.textContent='Retry';}finally{b.disabled=!!b.uncertain;}};body.append(b);return b;}
  async connect(account,manual=false,resume=null) {
    const hass=this._hass,generation=this.generation;
    if(manual) {await hass.callWS({type:'pivot/link',action:'start'});await this.refresh();return;}
    const approval=new URL(account.website_url);
    if(approval.protocol!=='https:' || approval.username || approval.password)throw new Error('secure_website_required');
    if(window.location?.protocol!=='https:') {
      throw new Error('secure_return_required');
    }
    // Open during the click, before awaiting WS, so HA can keep showing Cancel.
    const popup=window.open?.('about:blank','_blank');
    if(popup)popup.opener=null;
    try {
      const returnUrl=new URL('/pivot-tasks/tasks',window.location.origin).href;
      const pending=resume || await hass.callWS({type:'pivot/link',action:'start_return',browser_return:{returnUrl}});
      if(generation!==this.generation || this._hass.user?.id!==hass.user?.id){popup?.close();return;}
      if(!/^hl1\.[A-Za-z0-9_-]{43}$/.test(pending.locator) || !/^[A-Za-z0-9_-]{43}$/.test(pending.state) || !/^[A-Za-z0-9_-]{1,3072}$/.test(pending.returnContext))throw new Error('invalid_response');
      approval.hash='settings/ha/'+pending.locator+'/'+pending.state+'/'+pending.returnContext;
      if(popup){popup.location.href=approval.href;await this.refresh();}
      else window.location.assign(approval.href);
    }catch(error){popup?.close();throw error;}
  }
  takeReturn() {
    const hash=window.location?.hash||'';
    if(!hash.startsWith('#pivot-return/'))return;
    // Clear handoff material before any API calls or rendering.
    window.history?.replaceState(null,'',window.location.pathname+window.location.search);
    const match=/^#pivot-return\/([0-9a-f-]{36})\/([A-Za-z0-9_-]{43})\/([A-Za-z0-9_-]{1,3072})$/.exec(hash);
    if(!match)throw new Error('invalid_return');
    this.returnData={pairingId:match[1],state:match[2],result:match[3]};
  }
  async refresh() {
    if(typeof clearTimeout==='function')clearTimeout(this.pollTimer);
    const generation=this.generation=(this.generation||0)+1;this.replaceChildren();
    const card=this.element('ha-card');card.header='My Pivot tasks';
    const body=this.element('div');body.style.padding='16px';card.append(body);this.append(card);
    let account;
    try {
      this.takeReturn();
      if(this.returnData) {
        const data=this.returnData;this.returnData=null;
        body.append(this.element('p','Finishing your Pivot connection…'));
        await this._hass.callWS({type:'pivot/link',action:'finish_return',browser_return:data});
        if(generation!==this.generation)return;
        body.replaceChildren();
      }
      account=await this._hass.callWS({type:'pivot/link_status'});
      if(generation!==this.generation)return;
      if(!account.installation_ready){body.append(this.element('p','Ask your household administrator to set up the Pivot connection.'));return;}
      if(account.pending){
        await this.review(body,generation,account);
        return;
      }
      if(!account.linked){
        this.button(body,'Connect to Pivot',()=>this.connect(account));
        const advanced=this.element('details');advanced.append(this.element('summary','Advanced: manual connection'));
        advanced.append(this.element('p','Use this only if your browser cannot return from Pivot.'));
        this.button(advanced,'Start manual connection',()=>this.connect(account,true));body.append(advanced);return;
      }
      const {items,accountName}=await this._hass.callWS({type:'pivot/tasks'});if(generation!==this.generation)return;
      body.append(this.element('p',(accountName||account.pivot_user_name) ? `Connected as ${accountName||account.pivot_user_name}` : 'Connected to your Pivot account'));
      this.renderTasks(body,items,generation);
      this.button(body,'Refresh',()=>this.refresh());
      const advanced=this.element('details');advanced.append(this.element('summary','Connection settings'));
      this.button(advanced,'Disconnect',async()=>{await this._hass.callWS({type:'pivot/link',action:'unlink'});await this.refresh();});body.append(advanced);
    }catch{if(generation===this.generation){
      body.replaceChildren();
      if(account?.pending)this.button(body,'Connect to Pivot',()=>this.connect(account));
      body.append(this.element('p','We couldn’t finish connecting or load your tasks. Please try again.'));
      this.button(body,'Retry',()=>this.refresh());
    }}
  }
  renderTasks(body,items,generation) {
      for(const item of items){
        const row=this.element('p');row.append(this.element('span',`${item.title} (${item.ownership.mode}) `));
        if(item.status==='completed')row.append(document.createTextNode('Completed'));
        else {const button=this.button(row,'Complete',async()=>{try{
          await this._hass.callWS({type:'pivot/complete',task_id:item.id,etag:`"task-${item.id}-v${item.version}"`});
          if(generation===this.generation)await this.refresh();
        }catch{button.uncertain=true;button.textContent='Refresh to check result';}});}
        body.append(row);
      }
      if(!items.length)body.append(document.createTextNode(' No permitted tasks.'));
  }
  async review(body,generation,account){
    const result=await this._hass.callWS({type:'pivot/link',action:'inspect'});if(generation!==this.generation)return;
    const terminal=['expired','cancelled','unavailable'].includes(result.pairing.status) || result.link && ['revoked','expired','ineligible','invalid'].includes(result.link.effectiveStatus);
    if(terminal || result.delivery_uncertain){
      body.append(this.element('p',terminal?'This connection attempt has ended. Please try again.':'The connection was interrupted. Please try again.'));
      this.button(body,'Connect to Pivot',()=>this.connect(account));return;
    }
    if(result.awaiting_delivery){await this._hass.callWS({type:'pivot/link',action:'acknowledge'});if(generation===this.generation)await this.refresh();return;}
    body.append(this.element('p','Waiting for you to allow Home Assistant in Pivot…'));
    this.button(body,'Cancel',async()=>{clearTimeout(this.pollTimer);await this._hass.callWS({type:'pivot/link',action:'cancel'});await this.refresh();});
    if(result.automatic_delivery){
      this.button(body,result.approval?'Open approval page':'Connect to Pivot',()=>this.connect(account,false,result.approval));
    }else{
      const advanced=this.element('details');advanced.open=!!this.manualOpen;advanced.ontoggle=()=>{this.manualOpen=advanced.open;};advanced.append(this.element('summary','Advanced: manual connection'));body.append(advanced);
      const code=this.element('input');code.readOnly=true;code.value=account.locator||'';
      const label=this.element('label','Manual connection code');label.append(code);advanced.append(label);
      advanced.append(this.element('p','Open Pivot > Home Assistant > Advanced: manual connection, and paste this code.'));
      const p=result.pairing;
      if(p.status==='approved'){
        advanced.append(this.element('p',`Connect as ${result.approved_user_name||'your Pivot account'}?`));
        const policy=p.policy||{};
        advanced.append(this.element('p',`${policy.read?'Read tasks. ':''}${policy.complete?'Complete tasks. ':''}Only tasks in the programmes you selected in Pivot are permitted.`));
        this.button(advanced,'Confirm connection',async()=>{await this._hass.callWS({type:'pivot/link',action:'finish',confirmation:{userId:p.approvedUserId,consentId:p.consentId}});await this.refresh();});
      }
    }
    if(result.pairing.status==='pending' && typeof setTimeout==='function')this.pollTimer=setTimeout(()=>{if(generation===this.generation)this.refresh();},5000);
  }
  getCardSize(){return 4;}
}
window.customCards=window.customCards||[];
window.customCards.push({type:'pivot-task-card',name:'Pivot household tasks',description:'Private tasks with per-person account linking.'});
if(!customElements.get('pivot-task-card'))customElements.define('pivot-task-card',PivotTaskCard);


class PivotDashboardCard extends PivotTaskCard {
  renderTasks(body,items,generation) {
    const style=this.element('style',`
      pivot-dashboard-card ha-card{display:block;max-width:1400px;margin:16px auto;background:var(--card-background-color);border-radius:20px}
      pivot-dashboard-card .pivot-grid{display:grid;grid-template-columns:minmax(260px,1fr) minmax(340px,1.6fr);gap:20px;margin-top:16px}
      pivot-dashboard-card .pivot-box{padding:20px;border:1px solid var(--divider-color);border-radius:16px;background:var(--secondary-background-color)}
      pivot-dashboard-card h2{font-size:20px;margin:0 0 12px}pivot-dashboard-card .pivot-summary{font-size:16px;color:var(--secondary-text-color);margin:12px 0}
      pivot-dashboard-card .pivot-days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px}
      pivot-dashboard-card .pivot-day{min-height:66px;padding:5px;border-radius:7px;border:1px solid var(--divider-color);font-size:12px;overflow-wrap:anywhere}
      pivot-dashboard-card .pivot-target{display:block;margin-top:4px;color:var(--primary-color)}
      pivot-dashboard-card button{padding:8px 12px;border-radius:10px;margin:6px 6px 6px 0;cursor:pointer;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
      @media(max-width:720px){pivot-dashboard-card .pivot-grid{grid-template-columns:1fr}pivot-dashboard-card .pivot-day{min-height:48px;font-size:10px}}
    `);body.append(style);
    const active=items.filter(t=>t.status!=='completed');
    const completed=items.filter(t=>t.status==='completed');
    const summary=this.element('p',`${active.length} open tasks \u00b7 ${completed.length} completed`);summary.className='pivot-summary';body.append(summary);
    const grid=this.element('div');grid.className='pivot-grid';body.append(grid);
    const box=(title)=>{const e=this.element('section');e.className='pivot-box';e.append(this.element('h2',title));grid.append(e);return e;};
    const priority=box('Focus next');
    priority.append(this.element('p','Your highest-priority open tasks. Targets are planning dates, not automatic deadlines.'));
    const ranked=[...active].sort((a,b)=>(a.priority??3)-(b.priority??3)||(a.targetFinishDate||'9999').localeCompare(b.targetFinishDate||'9999'));
    for(const task of ranked.slice(0,4))this.taskTile(priority,task,generation);
    if(!ranked.length)priority.append(this.element('p','Nothing waiting here. Enjoy the breathing room.'));
    const calendar=box('Task calendar');
    const now=new Date();const month=this.month??now.getMonth(),year=this.year??now.getFullYear();
    this.button(calendar,'Previous month',()=>{const d=new Date(year,month-1,1);this.month=d.getMonth();this.year=d.getFullYear();this.refresh();});
    calendar.append(this.element('strong',new Date(year,month,1).toLocaleDateString(undefined,{month:'long',year:'numeric'})));
    this.button(calendar,'Next month',()=>{const d=new Date(year,month+1,1);this.month=d.getMonth();this.year=d.getFullYear();this.refresh();});
    const days=this.element('div');days.className='pivot-days';calendar.append(days);
    for(const name of ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])days.append(this.element('strong',name));
    const offset=(new Date(year,month,1).getDay()+6)%7,total=new Date(year,month+1,0).getDate();
    for(let n=0;n<offset;n++)days.append(this.element('div'));
    for(let day=1;day<=total;day++){
      const cell=this.element('div');cell.className='pivot-day';cell.append(this.element('strong',String(day)));
      const key=`${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
      for(const task of active.filter(t=>t.targetFinishDate===key)){const label=this.element('span',task.title);label.className='pivot-target';cell.append(label);}
      days.append(cell);
    }
    if(!active.some(t=>t.targetFinishDate))calendar.append(this.element('p','No target dates available. Add target dates in Pivot; older API versions do not provide them yet.'));
    const all=box('My open tasks');
    for(const task of ranked)this.taskTile(all,task,generation);
    if(!ranked.length)all.append(this.element('p','No open tasks in your permitted scope.'));
    const history=box('Recently completed');
    for(const task of [...completed].sort((a,b)=>String(b.completedAt||'').localeCompare(String(a.completedAt||''))).slice(0,8)){
      history.append(this.element('p',task.title));
    }
    if(!completed.length)history.append(this.element('p','Completed tasks will appear here.'));
  }
  taskTile(parent,task,generation){
    const tile=this.element('div');tile.append(this.element('strong',task.title));
    const details=[task.ownership?.mode||''];
    if(Number.isInteger(task.priority))details.push(`Priority ${task.priority}`);
    if(task.targetFinishDate)details.push(`Target ${task.targetFinishDate}${task.targetFinishConfidence?' ('+task.targetFinishConfidence+')':''}`);
    tile.append(this.element('p',details.filter(Boolean).join(' \u00b7 ')));
    const button=this.button(tile,'Complete',async()=>{try{
      await this._hass.callWS({type:'pivot/complete',task_id:task.id,etag:`"task-${task.id}-v${task.version}"`});
      if(generation===this.generation)await this.refresh();
    }catch{button.uncertain=true;button.textContent='Refresh to check result';}});
    parent.append(tile);
  }
  getCardSize(){return 12;}
}
window.customCards.push({type:'pivot-dashboard-card',name:'Pivot task dashboard',description:'Personal priorities, target calendar and task progress.'});
if(!customElements.get('pivot-dashboard-card'))customElements.define('pivot-dashboard-card',PivotDashboardCard);
