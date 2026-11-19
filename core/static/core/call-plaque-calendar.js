// Display Persian calendar dates; option values identify exact Tehran civil days.
window.createPlaqueCalendar = function (dialog) {
  const field = name => dialog.querySelector('[data-cp-' + name + ']');
  const month = field('month'), day = field('day'), hour = field('hour'), minute = field('minute');
  const value = field('followup'), interval = field('interval');
  const fmt = new Intl.DateTimeFormat('fa-IR', {calendar:'persian', year:'numeric', month:'long', day:'numeric', timeZone:'Asia/Tehran'});
  const greg = new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Tehran', year:'numeric', month:'2-digit', day:'2-digit'});
  const pad = n => String(n).padStart(2, '0');
  let dates = new Map(), baseDay, clock, started;
  function options(select, prompt, choices) {
    select.replaceChildren(new Option(prompt, ''), ...choices.map(([v,t]) => new Option(t,v)));
  }
  options(hour,'ساعت',Array.from({length:24}, (_,i)=>[pad(i),pad(i)]));
  options(minute,'دقیقه',Array.from({length:60}, (_,i)=>[pad(i),pad(i)]));
  const groups = [['minutes','دقیقه',[30]],['hours','ساعت',[1,2,3,4,6,8,10]],['days','روز',[1,2,3,4,5,6]],['weeks','هفته',[1,2,3]],['months','ماه',[1,2,3,4,6]]];
  options(interval,'انتخاب زمان دقیق',groups.flatMap(([unit,title,nums]) => nums.map(n=>[unit+':'+n,n+' '+title])));
  function build(now, saved) {
    const today = greg.format(now);
    if (baseDay === today && (!saved || [...dates.values()].some(days=>days.some(([v])=>v===saved)))) return;
    baseDay = today;
    dates = new Map();
    function add(iso) {
      const parts = fmt.formatToParts(new Date(iso+'T12:00:00Z'));
      const part = type => parts.find(p=>p.type===type).value;
      const key = part('month')+' '+part('year');
      if (!dates.has(key)) dates.set(key, []);
      dates.get(key).push([iso,part('day')]);
    }
    if (saved && saved < today) add(saved);
    const start = Date.parse(today+'T12:00:00Z');
    for (let i=0;i<=731;i++) add(new Date(start+i*86400000).toISOString().slice(0,10));
    options(month,'ماه و سال',[...dates.keys()].map(k=>[k,k]));
  }
  function setDate(iso) {
    month.value = [...dates].find(([,days])=>days.some(([v])=>v===iso))?.[0] || '';
    options(day,'روز',dates.get(month.value)||[]);
    day.value = iso;
  }
  function notify() {
    value.value = day.value && hour.value && minute.value ? day.value+'T'+hour.value+':'+minute.value : '';
    value.dispatchEvent(new Event('input'));
  }
  month.addEventListener('change',()=>{options(day,'روز',dates.get(month.value)||[]);interval.value='';notify();});
  for (const select of [day,hour,minute]) select.addEventListener('change',()=>{interval.value='';notify();});
  interval.addEventListener('change',()=>{
    if (!interval.value) return;
    const [unit,amount] = interval.value.split(':');
    const n = Number(amount), now = new Date(clock+performance.now()-started);
    // Tehran civil date represented in UTC for host-independent arithmetic.
    const civil = new Date(now.getTime()+210*60000);
    if (unit==='months') {
      const d = civil.getUTCDate();
      civil.setUTCDate(1);
      civil.setUTCMonth(civil.getUTCMonth()+n+1,0);
      civil.setUTCDate(Math.min(d,civil.getUTCDate()));
    } else civil.setUTCMinutes(civil.getUTCMinutes()+n*({minutes:1,hours:60,days:1440,weeks:10080}[unit]));
    setDate(civil.toISOString().slice(0,10));
    hour.value=pad(civil.getUTCHours());minute.value=pad(civil.getUTCMinutes());notify();
  });
  return {sync(local, serverNow) {
    if (clock!==Date.parse(serverNow)) {
      clock=Date.parse(serverNow)||Date.now();started=performance.now();value.value='';interval.value='';
      build(new Date(clock),local.slice(0,10));setDate('');hour.value='';minute.value='';
    }
    if (local===value.value) return;
    value.value=local;
    setDate(local.slice(0,10));hour.value=local.slice(11,13);minute.value=local.slice(14,16);
  }};
};
