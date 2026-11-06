(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const root = $('sms-auto-panel');
  if (!root) return;
  const csrf = document.querySelector('#bulk-audience-form input[name=csrfmiddlewaretoken]').value;
  const statusNames = {draft:'پیش‌نویس',active:'فعال',paused:'متوقف',ended:'پایان‌یافته',running:'در حال اجرا',completed:'تکمیل‌شده',skipped:'بدون مخاطب واجد شرایط',cancelled:'پایان داده‌شده',queued:'در صف ارسال'};
  let items = [], page = 0, editing = null, scenario = 'custom', pendingAction = null, previewSerial = 0;
  const wizard = $('sa-wizard');
  const num = n => Number(n || 0).toLocaleString('en-US');
  const dateLabel = s => s ? new Intl.DateTimeFormat('fa-IR-u-nu-latn', {timeZone:'Asia/Tehran',dateStyle:'medium',timeStyle:'short'}).format(new Date(s)) : '—';
  const localInput = s => {
    const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Tehran',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(s));
    const v = Object.fromEntries(parts.map(x => [x.type,x.value]));
    return `${v.year}-${v.month}-${v.day}T${v.hour}:${v.minute}`;
  };
  const tomorrow = () => localInput(Date.now()+86400000).slice(0,11)+'11:00';
  const node = (tag, text, cls) => {const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  const button = (text, action, cls) => {const b=node('button',text,cls);b.type='button';b.addEventListener('click',action);return b;};
  const selected = name => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(x=>x.value);
  const groups = Object.fromEntries([...document.querySelectorAll('input[name=auto_segments]')].map(x=>[x.value,x.parentElement.textContent.trim()]));
  function selectGroups(name, values) {document.querySelectorAll(`input[name="${name}"]`).forEach(x=>x.checked=values.includes(x.value));selectionCount();}
  function selectionCount() {$('sa-selection-count').textContent=num(selected('auto_segments').length)+' گروه انتخاب شده';}
  async function api(payload) {
    const r=await fetch(root.dataset.api, payload ? {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf,Accept:'application/json'},body:JSON.stringify(payload)} : {credentials:'same-origin',headers:{Accept:'application/json'}});
    const data=await r.json();if(!r.ok||!data.ok)throw Error(data.error||'خواندن اطلاعات انجام نشد؛ دوباره تلاش کنید.');return data;
  }
  function showTab(name, write=true) {
    ['manual','auto','history'].forEach(key=>{
      const active=key===name;$('sms-'+key+'-panel').hidden=!active;
      const b=$('sms-tab-'+key);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;
    });
    if(write)history.replaceState(null,'','#'+name);
    if(name==='auto')load().catch(showError);
    if(name==='history'&&window.smsRefreshCampaigns)window.smsRefreshCampaigns().catch(e=>$('sms-history-notice').textContent=e.message);
  }
  function showError(e) {$('sa-notice').textContent=e.message;}
  $('sa-history-host').append($('sms-history'));
  const tabs=[...document.querySelectorAll('[data-sms-tab]')];
  tabs.forEach((b,index)=>{
    b.addEventListener('click',()=>showTab(b.dataset.smsTab));
    b.addEventListener('keydown',e=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
      e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowLeft'?1:-1)+tabs.length)%tabs.length;
      tabs[next].focus();showTab(tabs[next].dataset.smsTab);
    });
  });
  showTab(location.hash==='#auto'?'auto':location.hash==='#history'||location.hash==='#sms-history'?'history':'manual',false);
  function summary(config, target) {
    target.append(node('p','گروه‌ها: '+config.segments.map(x=>groups[x]||x).join('، ')));
    target.append(node('p',`شروع: ${dateLabel(config.start_at)} · ${config.interval_days?'تکرار هر '+config.interval_days+' روز':'یک‌بار'} · سقف هر اجرا: ${num(config.limit)} · سقف 24 ساعته: ${num(config.daily_limit)}`));
    if(config.end_at)target.append(node('p','پایان زمان‌بندی: '+dateLabel(config.end_at)));
    if(config.exclude_segments.length)target.append(node('p','خروج در صورت عضویت در: '+config.exclude_segments.map(x=>groups[x]||x).join('، ')));
    if(config.inactive_days)target.append(node('p','دارای سابقه مراجعه؛ بدون مراجعه در '+config.inactive_days+' روز اخیر'));
    config.steps.forEach((step,index)=>{
      const box=node('div',undefined,'sa-review-step');
      const condition={all:'همه واجدین شرایط',unengaged:'فقط بدون مشارکت',engaged:'فقط مشارکت‌کنندگان'}[step.condition];
      box.append(node('b',`مرحله ${index+1} · ${index?step.delay_days+' روز پس از مرحله قبلی':'زمان شروع'} · ${condition}`),node('pre',step.body+(step.body.includes('لغو 11')?'':'\nلغو 11')));target.append(box);
    });
    if(config.reward.enabled)target.append(node('p',`امتیاز هر مشارکت: ${num(config.reward.points)}${config.reward.title?' · '+config.reward.title:''}`));
  }
  async function load() {
    const data=await api();items=data.automations;$('sa-notice').textContent='';$('sa-cards').replaceChildren();$('sa-empty').hidden=items.length>0;
    const active=items.filter(x=>x.status==='active');const upcoming=active.flatMap(x=>[x.next_run_at,x.next_step_at]).filter(Boolean).sort((a,b)=>new Date(a)-new Date(b));
    $('sa-summary').textContent=`${num(active.length)} کمپین فعال · ${upcoming.length?'نزدیک‌ترین زمان‌بندی: '+dateLabel(upcoming[0]):'ارسالی زمان‌بندی نشده است'}`;
    const old=$('sms-history-automation').value;$('sms-history-automation').replaceChildren(new Option('همه کمپین‌ها',''));
    for(const item of items) {
      $('sms-history-automation').append(new Option(item.name,String(item.id)));
      const card=node('article',undefined,'sa-card');card.append(node('span',statusNames[item.status]||item.status,'sa-badge '+item.status),node('h3',item.name));
      card.append(node('p',item.config.segments.map(x=>groups[x]||x).join('، ')),node('p',`${num(item.config.steps.length)} مرحله · ${item.config.interval_days?'هر '+item.config.interval_days+' روز':'یک‌بار'}`));
      card.append(node('p',item.status==='active'?('نوبت بعدی: '+dateLabel(item.next_step_at||item.next_run_at)):'شروع تعریف‌شده: '+dateLabel(item.config.start_at)),node('p','حداکثر '+num(item.config.limit)+' مخاطب در هر اجرا؛ محاسبه هنگام اجرا'));
      if(item.last_error)card.append(node('p',item.last_error,'sa-error'));
      const actions=node('div',undefined,'sa-actions');actions.append(button('مراحل و گزارش',()=>report(item)));
      if(item.status!=='active'&&!item.running)actions.append(button('ویرایش',()=>openWizard(item)));
      if(['draft','paused'].includes(item.status))actions.append(button(item.status==='paused'?'ادامه':'فعال‌سازی',()=>confirmAction(item,'activate')));
      if(item.status==='active')actions.append(button('توقف',()=>confirmAction(item,'pause')));
      if(['active','paused'].includes(item.status))actions.append(button('پایان کمپین',()=>confirmAction(item,'end')));
      card.append(actions);$('sa-cards').append(card);
    }
    if([...$('sms-history-automation').options].some(x=>x.value===old))$('sms-history-automation').value=old;
  }
  async function report(item) {
    $('sa-detail-title').textContent=item.name;$('sa-detail-body').replaceChildren(node('p','در حال دریافت گزارش…'));$('sa-detail').showModal();
    try {
      const r=await fetch(root.dataset.report.replace('/0/',`/${item.id}/`),{credentials:'same-origin',headers:{Accept:'application/json'}});const data=await r.json();if(!r.ok||!data.ok)throw Error('گزارش در دسترس نیست.');
      const area=$('sa-detail-body');area.replaceChildren();const metrics=node('div',undefined,'sa-report-metrics');
      for(const [label,value] of [['پذیرفته‌شده درگاه',data.totals.accepted],['در صف',data.totals.pending],['ناموفق',data.totals.failed],['حذف از ارسال',data.totals.skipped],['مشارکت',data.rewards.engaged],['امتیاز ثبت‌شده',data.rewards.points]]){const box=node('div',label);box.append(node('b',num(value)));metrics.append(box);}area.append(metrics);
      area.append(node('h3','مسیر تعریف‌شده'));summary(item.config,area);
      area.append(node('h3','اجراهای اخیر'));
      if(!data.runs.length)area.append(node('p','هنوز اجرای خودکاری ثبت نشده است.'));
      data.runs.forEach(run=>{const box=node('div',undefined,'sa-review-step');box.append(node('b',dateLabel(run.scheduled_for)+' · '+(statusNames[run.status]||run.status)));run.steps.forEach(s=>box.append(node('p',`مرحله ${s.index} · ${num(s.count)} مخاطب · ${statusNames[s.status]||s.status}${s.note?' · '+s.note:''}`)));if(run.note)box.append(node('p',run.note));area.append(box);});
      area.append(button('دیدن ارسال‌های این کمپین',()=>{$('sa-detail').close();$('sms-history-mode').value='auto';$('sms-history-automation').value=String(item.id);showTab('history');}));
    } catch(e) {$('sa-detail-body').replaceChildren(node('p',e.message,'sa-error'));}
  }
  function confirmAction(item, action) {
    pendingAction={item,action};$('sa-confirm-error').textContent='';$('sa-resume-consent').checked=false;$('sa-resume-typed').value='';
    const label={activate:item.status==='paused'?'ادامه کمپین':'فعال‌سازی کمپین',pause:'توقف کمپین',end:'پایان کمپین'}[action];$('sa-confirm-title').textContent=label+' «'+item.name+'»';$('sa-confirm-action').textContent=label;
    $('sa-confirm-controls').hidden=action!=='activate';const body=$('sa-confirm-body');body.replaceChildren();
    if(action==='activate'){summary(item.config,body);body.append(node('p','پس از تأیید، ارسال‌ها طبق همین زمان‌بندی و از صف انجام می‌شوند. در ادامهٔ کمپین، مراحل عقب‌افتاده ممکن است اکنون اجرا شوند.'));}
    else body.append(node('p',action==='pause'?'زمان‌بندی و پیام‌های باقی‌مانده متوقف می‌شوند و امکان ادامه وجود دارد. پیام در حال ارسال ممکن است تکمیل شود.':'اجراهای آینده و پیام‌های ارسال‌نشده پایان می‌یابند. ارسال‌های انجام‌شده و گزارش‌ها حفظ می‌شوند.'));
    $('sa-confirm').showModal();
  }
  $('sa-confirm-action').addEventListener('click',async e=>{
    const {item,action}=pendingAction;e.currentTarget.disabled=true;
    try{await api({action,id:item.id,revision:item.revision,consent:$('sa-resume-consent').checked,typed:$('sa-resume-typed').value.trim()});$('sa-confirm').close();await load();if(window.smsRefreshCampaigns)await window.smsRefreshCampaigns();}
    catch(error){$('sa-confirm-error').textContent=error.message;}finally{$('sa-confirm-action').disabled=false;}
  });
  function renumber() {
    [...$('sa-steps').children].forEach((el,i)=>{el.querySelector('h4').textContent='مرحله '+(i+1);el.querySelector('.sa-followup').hidden=i===0;el.querySelector('.sa-remove').hidden=i===0;});
    $('sa-add-step').disabled=$('sa-steps').children.length>=3;
  }
  function addStep(value={body:'',delay_days:7,condition:'all'}) {
    const el=$('sa-step-template').content.firstElementChild.cloneNode(true);const text=el.querySelector('textarea');text.value=value.body;
    el.querySelector('.sa-delay').value=value.delay_days||7;el.querySelector('.sa-condition').value=value.condition;
    const count=()=>el.querySelector('.sa-char-count').textContent=num(text.value.length)+' / 430 نویسه';text.addEventListener('input',count);count();
    el.querySelector('.sa-remove').addEventListener('click',()=>{el.remove();renumber();});
    el.querySelector('.sa-insert-link').addEventListener('click',()=>{const start=text.selectionStart,end=text.selectionEnd;text.setRangeText('{لینک}',start,end,'end');text.focus();count();});
    $('sa-steps').append(el);renumber();
  }
  function config() {
    return {scenario,segments:selected('auto_segments'),exclude_segments:selected('auto_exits'),combine:$('sa-combine').value,inactive_days:Number($('sa-inactive').value),
      steps:[...$('sa-steps').children].map((el,i)=>({body:el.querySelector('textarea').value.trim(),delay_days:i?Number(el.querySelector('.sa-delay').value):0,condition:i?el.querySelector('.sa-condition').value:'all'})),
      start_at:$('sa-start').value?$('sa-start').value+':00+03:30':'',end_at:$('sa-end').value?$('sa-end').value+':00+03:30':null,
      interval_days:Number($('sa-interval').value),limit:Number($('sa-limit').value),daily_limit:Number($('sa-daily').value),
      reward:{enabled:$('sa-reward-enabled').checked,points:Number($('sa-points').value),title:$('sa-reward-title').value.trim()}};
  }
  function applyConfig(c) {
    scenario=c.scenario;selectGroups('auto_segments',c.segments);selectGroups('auto_exits',c.exclude_segments);
    $('sa-combine').value=c.combine;$('sa-inactive').value=String(c.inactive_days);$('sa-start').value=localInput(c.start_at);$('sa-end').value=c.end_at?localInput(c.end_at):'';
    $('sa-interval').value=String(c.interval_days);$('sa-limit').value=c.limit;$('sa-daily').value=c.daily_limit;
    $('sa-reward-enabled').checked=c.reward.enabled;$('sa-points').value=c.reward.points;$('sa-reward-title').value=c.reward.title;$('sa-reward-fields').hidden=!c.reward.enabled;
    $('sa-steps').replaceChildren();c.steps.forEach(addStep);document.querySelectorAll('[data-preset]').forEach(x=>x.classList.toggle('selected',x.dataset.preset===scenario));
  }
  function openWizard(item=null) {
    editing=item;$('sa-form').reset();$('sa-title').textContent=item?'ویرایش کمپین':'کمپین جدید';$('sa-name').value=item?item.name:'';
    $('sa-form-error').textContent='';$('sa-preview').textContent='';$('sa-consent').checked=false;$('sa-typed').value='';$('sa-group-search').value='';filterGroups();
    const empty={scenario:'custom',segments:[],exclude_segments:[],combine:'any',inactive_days:0,start_at:tomorrow()+':00+03:30',end_at:null,interval_days:0,limit:100,daily_limit:100,reward:{enabled:false,points:20,title:''},steps:[{body:'',delay_days:0,condition:'all'}]};
    applyConfig(item?item.config:empty);goPage(0);wizard.showModal();
  }
  const presets={
    leads:{name:'فعال‌سازی لیدها',keys:['lead_site','lead_instagram'],exits:['visit_booked','lead_appointment','lead_won'],body:'گرین‌لایف؛ برای دریافت اطلاعات و درخواست تماس، مشارکت خود را در این لینک ثبت کنید: {لینک}'},
    return:{name:'بازگشت مخاطبان',keys:['patient_all'],exits:['visit_booked'],inactive:90,body:'همراه گرامی گرین‌لایف، خوشحال می‌شویم دوباره با شما در ارتباط باشیم. برای اعلام تمایل به تماس: {لینک}'},
    club:{name:'مشارکت امتیازی باشگاه',keys:['network_active'],exits:[],reward:true,body:'دعوت باشگاه گرین‌لایف؛ با ثبت مشارکت در این کمپین {امتیاز} امتیاز دریافت کنید: {لینک}'},
    occasion:{name:'کمپین مناسبتی',keys:[],exits:[],body:'گرین‌لایف؛ پیام مناسبتی خود را اینجا بنویسید.'},
    custom:{name:'',keys:[],exits:[],body:''}
  };
  document.querySelectorAll('[data-preset]').forEach(b=>b.addEventListener('click',()=>{
    scenario=b.dataset.preset;const p=presets[scenario];$('sa-name').value=p.name;selectGroups('auto_segments',p.keys);selectGroups('auto_exits',p.exits);
    $('sa-inactive').value=String(p.inactive||0);$('sa-reward-enabled').checked=!!p.reward;$('sa-reward-fields').hidden=!p.reward;
    $('sa-steps').replaceChildren();addStep({body:p.body,delay_days:0,condition:'all'});document.querySelectorAll('[data-preset]').forEach(x=>x.classList.toggle('selected',x===b));
  }));
  function validatePage() {
    if(page===0&&$('sa-name').value.trim().length<2)throw Error('نام کمپین را وارد کنید.');
    if(page===1&&!selected('auto_segments').length)throw Error('حداقل یک گروه انتخاب کنید.');
    if(page===2&&config().steps.some(s=>s.body.length<3||s.body.length>430))throw Error('متن هر مرحله باید بین 3 تا 430 نویسه باشد.');
    if(page===3&&!$('sa-start').value)throw Error('تاریخ شروع را مشخص کنید.');
  }
  async function goPage(next) {
    page=next;$('sa-form-error').textContent='';document.querySelectorAll('.sa-page').forEach(x=>x.hidden=Number(x.dataset.page)!==page);
    [...$('sa-progress').children].forEach((x,i)=>{x.classList.toggle('current',i===page);x.classList.toggle('done',i<page);});
    $('sa-back').hidden=page===0;$('sa-next').hidden=page===4;$('sa-save').hidden=page!==4;$('sa-activate').hidden=page!==4;
    wizard.scrollTop=0;
    if(page===4) {
      const serial=++previewSerial;const c=config();$('sa-review').replaceChildren(node('b',$('sa-name').value));summary(c,$('sa-review'));$('sa-preview').textContent='در حال محاسبه مخاطبان فعلی…';$('sa-save').disabled=true;$('sa-activate').disabled=true;
      try{const data=await api({action:'preview',config:c});if(serial!==previewSerial)return;const p=data.preview;$('sa-preview').textContent=`اکنون: ${num(p.eligible)} واجد شرایط · ${num(p.count)} نفر در سقف اجرا · ${num(p.excluded)} حذف از شرایط${p.limited?' · '+num(p.limited)+' نفر بیش از سقف':''}. شمارش هنگام اجرا دوباره انجام می‌شود.`;$('sa-save').disabled=false;$('sa-activate').disabled=false;}
      catch(e){if(serial===previewSerial){$('sa-preview').textContent='محاسبه انجام نشد.';$('sa-form-error').textContent=e.message;}}
    }
  }
  async function save(activate) {
    $('sa-save').disabled=true;$('sa-activate').disabled=true;$('sa-form-error').textContent='';
    try {
      if(activate&&(!$('sa-consent').checked||$('sa-typed').value.trim()!=='تایید'))throw Error('برای فعال‌سازی، رضایت مخاطبان و عبارت «تایید» لازم است.');
      const data=await api({action:'save',name:$('sa-name').value.trim(),config:config(),id:editing?.id,revision:editing?.revision});editing=data.automation;
      if(activate)await api({action:'activate',id:editing.id,revision:editing.revision,consent:$('sa-consent').checked,typed:$('sa-typed').value.trim()});
      wizard.close();await load();$('sa-notice').textContent=activate?'کمپین فعال شد؛ طبق زمان‌بندی اجرا می‌شود.':'پیش‌نویس ذخیره شد؛ ارسال خودکار هنوز فعال نیست.';
    } catch(e){$('sa-form-error').textContent=e.message;}finally{$('sa-save').disabled=false;$('sa-activate').disabled=false;}
  }
  function filterGroups() {const q=$('sa-group-search').value.trim().toLocaleLowerCase('fa');document.querySelectorAll('[data-sa-search]').forEach(x=>x.hidden=!x.dataset.saSearch.toLocaleLowerCase('fa').includes(q));document.querySelectorAll('.sa-groups details').forEach(x=>x.hidden=![...x.querySelectorAll('label')].some(l=>!l.hidden));}
  $('sa-form').addEventListener('submit',e=>e.preventDefault());$('sa-next').addEventListener('click',()=>{try{validatePage();goPage(page+1);}catch(e){$('sa-form-error').textContent=e.message;}});
  $('sa-back').addEventListener('click',()=>{previewSerial++;goPage(page-1);});$('sa-save').addEventListener('click',()=>save(false));$('sa-activate').addEventListener('click',()=>save(true));
  $('sa-add-step').addEventListener('click',()=>{if($('sa-steps').children.length<3)addStep();});$('sa-reward-enabled').addEventListener('change',()=>$('sa-reward-fields').hidden=!$('sa-reward-enabled').checked);
  $('sa-create').addEventListener('click',()=>openWizard());$('sa-empty-create').addEventListener('click',()=>openWizard());$('sa-refresh').addEventListener('click',()=>load().catch(showError));
  $('sa-group-search').addEventListener('input',filterGroups);document.querySelectorAll('input[name=auto_segments]').forEach(x=>x.addEventListener('change',selectionCount));
  document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>$(b.dataset.close).close()));
  if(location.hash!=='#auto')load().catch(showError);
})();
