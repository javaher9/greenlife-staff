(()=>{'use strict';
 const config=document.getElementById('config'),demo=config.dataset.demo==='1';
 let state=JSON.parse(document.getElementById('initial-progress').textContent),active=1,timer=null,busy=false;
 const forms=[...document.querySelectorAll('.log-form')],panels=[...document.querySelectorAll('.day-panel')],tabs=[...document.querySelectorAll('.day-tab')];
 const picker=document.getElementById('day-select'),next=document.getElementById('next-day'),prev=document.getElementById('prev-day');
 const fa=n=>new Intl.NumberFormat('fa-IR').format(n);
 function notice(message,error=false,celebrate=false){const node=document.getElementById('notice');clearTimeout(timer);node.textContent=message;node.className='toast'+(error?' error':'')+(celebrate?' celebrate':'');node.hidden=false;timer=setTimeout(()=>node.hidden=true,4000);}
 function update(){
  const dayForms=forms.filter(f=>Number(f.dataset.day)===active),rows=state.records.filter(r=>r.day===active),percent=dayForms.length?Math.round(rows.length/dayForms.length*100):0;
  document.getElementById('day-ring').style.setProperty('--progress',percent+'%');document.getElementById('ring-label').textContent=fa(percent)+'٪';
  document.getElementById('day-heading').textContent=picker.selectedOptions[0].textContent;
  document.getElementById('day-count').textContent=fa(rows.length)+' از '+fa(dayForms.length)+' وعده ثبت شد';
  document.getElementById('course-count').textContent=fa(state.completed_days.length)+' از '+fa(panels.length)+' روز ثبت کامل دارد';
  for(const form of forms){const row=state.records.find(r=>r.day===Number(form.dataset.day)&&r.key===form.dataset.key);form.elements.status.value=row?.status||'';form.elements.note.value=row?.note||'';form.querySelector('.save-state').textContent=row?'✓ ثبت‌شده · گزارش خود شما':'';}
  for(const tab of tabs){const chosen=Number(tab.dataset.day)===active;tab.setAttribute('aria-selected',chosen?'true':'false');tab.tabIndex=chosen?0:-1;tab.classList.toggle('done',state.completed_days.includes(Number(tab.dataset.day)));}
  const badges=document.getElementById('badges');badges.replaceChildren();for(const text of state.badges){const span=document.createElement('span');span.className='badge';span.textContent=text;badges.append(span);}
  const changes=document.getElementById('changes');changes.replaceChildren();for(const row of state.changes){const p=document.createElement('p');p.className='change-item';p.textContent='روز '+fa(row.day)+' · '+row.food+(row.amount?' · '+row.amount:'')+(row.reason?' · '+row.reason:'');changes.append(p);}
 }
 function show(n){if(!Number.isInteger(n)||n<1||n>panels.length)return;active=n;picker.value=String(n);panels.forEach(p=>p.hidden=Number(p.dataset.day)!==n);next.disabled=n===panels.length;prev.disabled=n===1;
  const audio=document.getElementById('plan-voice'),url=panels[n-1].dataset.audio||'';
  if(audio.getAttribute('src')!==url){audio.pause();audio.removeAttribute('src');if(url)audio.setAttribute('src',url);audio.load();}audio.hidden=!url;document.getElementById('audio-empty').hidden=Boolean(url);update();
 }
 function demoSave(data){
  if(data.action==='meal'){state.records=state.records.filter(r=>!(r.day===data.day&&r.key===data.key));if(data.status)state.records.push(data);}
  else state.changes.unshift(data);
  state.completed_days=panels.filter(p=>{const fs=forms.filter(f=>f.dataset.day===p.dataset.day);return fs.length&&fs.every(f=>state.records.some(r=>r.day===Number(f.dataset.day)&&r.key===f.dataset.key));}).map(p=>Number(p.dataset.day));
  if(state.records.length&&!state.badges.includes('🌱 اولین ثبت'))state.badges.push('🌱 اولین ثبت');
  if(state.completed_days.length>=3&&!state.badges.includes('🌿 سه روز پیگیری'))state.badges.push('🌿 سه روز پیگیری');
  if(state.completed_days.length===panels.length&&!state.badges.includes('🌳 ثبت کامل برنامه'))state.badges.push('🌳 ثبت کامل برنامه');return state;
 }
 async function save(data){
  if(demo)return demoSave(data);
  const response=await fetch(config.dataset.endpoint,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('#csrf-form input[name="csrfmiddlewaretoken"]').value},body:JSON.stringify(data)});
  if(response.redirected)throw new Error('ورود شما نیاز به تأیید مجدد دارد؛ برنامه‌های من را باز کنید.');
  let result;try{result=await response.json();}catch(e){throw new Error('ثبت انجام نشد؛ دوباره تلاش کنید.');}
  if(!response.ok)throw new Error(result.error||'ثبت انجام نشد؛ دوباره تلاش کنید.');return result;
 }
 for(const form of forms)form.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;const button=form.querySelector('button');button.disabled=true;
  const data={action:'meal',day:Number(form.dataset.day),key:form.dataset.key,status:form.elements.status.value,note:form.elements.note.value},first=!state.records.some(r=>r.day===data.day&&r.key===data.key);
  try{state=await save(data);update();notice(data.status?(first?'🌱 یک قدم برای پیگیری خودت برداشتی!':'اطلاعات وعده به‌روز شد.'):'ثبت این وعده لغو شد.',false,first&&Boolean(data.status));}catch(error){notice(error.message,true);}finally{busy=false;button.disabled=false;}
 });
 const changeForm=document.getElementById('change-form');let changeId=null;
 changeForm.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;const button=changeForm.querySelector('button');button.disabled=true;
  changeId=changeId||crypto.randomUUID();const data={action:'change',day:active,food:changeForm.elements.food.value,amount:changeForm.elements.amount.value,reason:changeForm.elements.reason.value,request_id:changeId};
  try{state=await save(data);changeForm.reset();changeId=null;update();notice('ممنون که ثبت کردی؛ این اطلاعات به شناخت روند برنامه‌ات کمک می‌کند.');}catch(error){notice(error.message,true);}finally{busy=false;button.disabled=false;}
 });
 picker.addEventListener('change',()=>show(Number(picker.value)));next.addEventListener('click',()=>show(active+1));prev.addEventListener('click',()=>show(active-1));
 for(const tab of tabs){tab.addEventListener('click',()=>show(Number(tab.dataset.day)));tab.addEventListener('keydown',e=>{const delta=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0;if(delta){e.preventDefault();show(Math.max(1,Math.min(panels.length,active+delta)));tabs[active-1].focus();}});}
 show(1);
})();
