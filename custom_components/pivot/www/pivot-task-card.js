class PivotTaskCard extends HTMLElement {
  setConfig(config) { this.config = config; }
  set hass(value) { const changed=this._hass?.user?.id!==value.user?.id;this._hass=value;if(!this.started||changed){this.started=true;this.refresh();} }
  connectedCallback() { if(this._hass)this.refresh(); }
  disconnectedCallback() { this.generation=(this.generation||0)+1;this.replaceChildren();this.started=false; }
  element(tag,text) {const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
  button(body,text,action) {const b=this.element('button',text);b.onclick=async()=>{b.disabled=true;try{await action();}catch{b.textContent='Check status before retrying';}};body.append(b);return b;}
  async refresh() {
    const generation=this.generation=(this.generation||0)+1;this.replaceChildren();
    const card=this.element('ha-card');card.header='My Pivot tasks';
    const body=this.element('div');body.style.padding='16px';card.append(body);this.append(card);
    this.button(body,'Refresh',()=>this.refresh());
    let account;let stage='status';
    try {
      account=await this._hass.callWS({type:'pivot/link_status'});
      if(generation!==this.generation)return;
      if(!account.installation_ready){body.append(this.element('p','Set up Pivot under Settings > Devices & services before linking your account.'));return;}
      if(!account.linked || account.pending){
        body.append(this.element('p',`Link your HA account (${account.ha_name}) to your own Pivot account.`));
        if(account.pending){
          body.append(this.element('p','Sign into your own Pivot account, open Settings > Home Assistant and enter this locator:'));
          body.append(this.element('code',account.locator));
          this.button(body,'Review approved account and permissions',()=>this.review(body,generation,account));
          this.button(body,'Cancel account linking',async()=>{await this._hass.callWS({type:'pivot/link',action:'cancel'});await this.refresh();});
        }else this.button(body,'Start linking my account',async()=>{await this._hass.callWS({type:'pivot/link',action:'start'});await this.refresh();});
        return;
      }
      stage='tasks';const {items}=await this._hass.callWS({type:'pivot/tasks'});if(generation!==this.generation)return;
      this.renderTasks(body,items,generation);
      if(account.pending)this.button(body,'Retry acknowledgement of delivered link',async()=>{await this._hass.callWS({type:'pivot/link',action:'acknowledge'});await this.refresh();});
    }catch(error){if(generation===this.generation){
      // Only fixed messages: never display upstream errors, URLs or credentials.
      const message=error?.code==='unknown_command'
        ? 'Home Assistant has not loaded the Pivot integration commands. Update Pivot in HACS, restart Home Assistant, and check Settings > Devices & services > Pivot.'
        : error?.code==='access_denied'
        ? 'Your signed-in Home Assistant account cannot access Pivot. Use an active personal account and check its Pivot link.'
        : stage==='status'
        ? 'Home Assistant could not read the local Pivot setup or account-link status. Check Settings > Devices & services > Pivot and the Home Assistant system logs.'
        : 'Pivot task request failed. Check the API connection, certificate and account grant; refresh before retrying any completion.';
      body.append(this.element('p',message));
    }}
    finally {
      if(generation===this.generation && account?.linked) {
      this.button(body,'Review removing my account link',async()=>{
        body.append(this.element('p','This revokes your grant and removes only your HA account link.'));
        this.button(body,'Confirm unlink my account',async()=>{await this._hass.callWS({type:'pivot/link',action:'unlink'});await this.refresh();});
      });
      }
    }
  }
  renderTasks(body,items,generation) {
      for(const item of items){
        const row=this.element('p');row.append(this.element('span',`${item.title} (${item.ownership.mode}) `));
        if(item.status==='completed')row.append(document.createTextNode('Completed'));
        else {const button=this.button(row,'Complete',async()=>{try{
          await this._hass.callWS({type:'pivot/complete',task_id:item.id,etag:`"task-${item.id}-v${item.version}"`});
          if(generation===this.generation)await this.refresh();
        }catch{button.textContent='Refresh to check result';}});}
        body.append(row);
      }
      if(!items.length)body.append(document.createTextNode(' No permitted tasks.'));
  }
  async review(body,generation,account){
    const result=await this._hass.callWS({type:'pivot/link',action:'inspect'});if(generation!==this.generation)return;
    if(result.awaiting_delivery){this.button(body,'Retry acknowledgement of delivered link',async()=>{await this._hass.callWS({type:'pivot/link',action:'acknowledge'});await this.refresh();});return;}
    const p=result.pairing;if(p.status!=='approved'){body.append(this.element('p',`Pairing is ${p.status}. Approve in Pivot within five minutes.`));return;}
    body.append(this.element('p',`HA account: ${account.ha_name} (${account.subject})`));
    body.append(this.element('p',`Pivot account: ${result.approved_user_name||''} (${p.approvedUserId})`));
    body.append(this.element('p','Review every permission and expiry. Account IDs identify the link; names are labels.'));
    body.append(this.element('pre',JSON.stringify(p.policy,null,2)));
    this.button(body,'Confirm these accounts and permissions',async()=>{
      await this._hass.callWS({type:'pivot/link',action:'finish',confirmation:{userId:p.approvedUserId,consentId:p.consentId}});await this.refresh();
    });
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
    }catch{button.textContent='Refresh to check result';}});
    parent.append(tile);
  }
  getCardSize(){return 12;}
}
window.customCards.push({type:'pivot-dashboard-card',name:'Pivot task dashboard',description:'Personal priorities, target calendar and task progress.'});
if(!customElements.get('pivot-dashboard-card'))customElements.define('pivot-dashboard-card',PivotDashboardCard);
