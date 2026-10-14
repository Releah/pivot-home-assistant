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
    let account;
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
      const {items}=await this._hass.callWS({type:'pivot/tasks'});if(generation!==this.generation)return;
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
      if(account.pending)this.button(body,'Retry acknowledgement of delivered link',async()=>{await this._hass.callWS({type:'pivot/link',action:'acknowledge'});await this.refresh();});
    }catch{if(generation===this.generation)body.append(this.element('p','Pivot unavailable or pairing required.'));}
    finally {
      if(generation===this.generation && account?.linked) {
      this.button(body,'Review removing my account link',async()=>{
        body.append(this.element('p','This revokes your grant and removes only your HA account link.'));
        this.button(body,'Confirm unlink my account',async()=>{await this._hass.callWS({type:'pivot/link',action:'unlink'});await this.refresh();});
      });
      }
    }
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
customElements.define('pivot-task-card',PivotTaskCard);
