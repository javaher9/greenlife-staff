'use strict';

(() => {
  const byId = id => document.getElementById(id);
  const e = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  })[char]);
  const fa = value => Number(value).toLocaleString('en-US');
  const screen = byId('workspace');
  const dialog = byId('detail');
  const mainPhone = screen.dataset.mainPhone;
  const inboundPhone = screen.dataset.inboundPhone;
  const key = 'greenlife-staff-phone-preview-v1:' + screen.dataset.userId;
  const destinations = ['صف کال‌سنتر','صف پیگیری','پذیرش شعبه','داخلی سرپرست'];
  const tabs = [
    ['overview','نمای کلی'],
    ['main-line','بررسی خط‌ها'],
    ['history','سابقه تماس'],
    ['lines','خطوط و صف‌ها'],
    ['routing','آزمون مسیر']
  ];
  const defaultRoute = {
    start:'08:00', end:'20:00', fallback:'صف کال‌سنتر',
    afterHours:'داخلی سرپرست', testProfile:''
  };
  const testProfiles = [['','مسیر پاسخ‌گویی انسانی'],['pilot','دستیار داخلی آزمایشی']];
  const validTime = value => /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(value);
  let route = defaultRoute;
  let activeTab = 'overview';
  let toastTimer;

  function isValidRoute(value) {
    return value && validTime(value.start) && validTime(value.end) && value.start !== value.end &&
      destinations.includes(value.fallback) && destinations.includes(value.afterHours) &&
      testProfiles.some(([id]) => id === value.testProfile);
  }

  try {
    const saved = JSON.parse(localStorage.getItem(key));
    if (isValidRoute(saved)) route = saved;
  } catch {
    // Route simulation is available even if browser storage is unavailable.
  }

  const options = (items,selected) => items.map(item => {
    const [value,label] = Array.isArray(item) ? item : [item,item];
    return '<option value="'+e(value)+'"'+(value === selected ? ' selected' : '')+'>'+e(label)+'</option>';
  }).join('');
  const chip = (label,tone='',dot=false) => '<span class="chip '+tone+'">'+
    (dot ? '<span class="dot" aria-hidden="true"></span>' : '')+e(label)+'</span>';
  const button = (label,action,kind='',extra='') => '<button type="button" class="btn '+kind+
    '" data-action="'+action+'" '+extra+'>'+label+'</button>';
  const detailRows = rows => '<dl class="details">'+rows.map(([label,value]) =>
    '<div><dt>'+label+'</dt><dd>'+value+'</dd></div>'
  ).join('')+'</dl>';
  const routeStrip = steps => '<ol class="route-strip">'+steps.map(step =>
    '<li class="route-step">'+e(step)+'</li>'
  ).join('')+'</ol>';

  function notify(message) {
    clearTimeout(toastTimer);
    const toast = byId('toast');
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; },5000);
  }

  function showDialog(title,contents) {
    if (dialog.open) return;
    dialog.innerHTML = '<div class="spread"><h2 id="dialog-title">'+title+
      '</h2>'+button('بستن','close','compact','autofocus')+'</div>'+contents;
    dialog.showModal();
  }

  const readiness = window.createPhoneCenterReadiness({
    key,mainPhone,inboundPhone,e,chip,notify,render
  });
  const activity = window.createPhoneCenterActivity({
    e,fa,chip,button,options,detailRows,routeStrip,showDialog
  });

  function overview() {
    return '<div class="stack"><section class="stack overview-readiness" aria-labelledby="readiness-heading">'+
      '<div class="section-heading"><h2 id="readiness-heading">آمادگی خط‌ها</h2></div>'+
      readiness.summaryCards()+
      '</section>'+activity.overview()+'</div>';
  }

  function lines() {
    return '<div class="stack"><section class="stack" aria-labelledby="directory-heading">'+
      '<div class="section-heading"><h2 id="directory-heading">خط‌های گرین‌لایف</h2></div>'+
      readiness.summaryCards()+'</section>'+
      '<div class="duo equal"><section class="panel">'+
      '<div class="panel-head"><h2>داخلی‌ها</h2></div>'+
      detailRows([
        ['داخلی آزمون تلفن','<bdi>125</bdi>'],
        ['داخلی دستیار آزمایشی','<bdi>890</bdi>'],
        ['مراکز','نیاوران، پونک، اصفهان و افسریه']
      ])+'</section><section class="panel">'+
      '<div class="panel-head"><h2>مقصدهای آزمون مسیر</h2></div>'+
      '<div class="row">'+destinations.map(name => chip(name)).join('')+'</div>'+
      '</section></div>'+activity.queueView()+'</div>';
  }

  function routing() {
    return '<div class="stack"><div class="section-heading">'+
      '<div><h2>آزمون مسیر خط اصلی <bdi>'+mainPhone+'</bdi></h2>'+
      '<p class="small">پیش‌نمایش مسیر در ساعت تهران. قواعد روی همین مرورگر ذخیره می‌شوند.</p></div>'+
      chip('شبیه‌سازی','violet')+'</div>'+
      '<div class="duo equal"><section class="panel"><div class="panel-head"><h3>قواعد مسیر نمونه</h3></div>'+
      '<form id="route-editor" class="form-grid">'+
      '<label>شروع ساعت کاری<input type="time" name="start" value="'+e(route.start)+'" required></label>'+
      '<label>پایان ساعت کاری<input type="time" name="end" value="'+e(route.end)+'" required></label>'+
      '<label class="wide">مقصد عادی یا جایگزین هنگام اختلال<select name="fallback">'+options(destinations,route.fallback)+'</select></label>'+
      '<label class="wide">مقصد خارج ساعت کاری<select name="afterHours">'+options(destinations,route.afterHours)+'</select></label>'+
      '<label class="wide">مسیر پیش‌فرض آزمون<select name="testProfile">'+options(testProfiles,route.testProfile)+'</select></label>'+
      '<div class="wide"><button class="btn primary" type="submit">ذخیره مسیر نمونه</button></div>'+
      '</form></section>'+
      '<section class="panel"><div class="panel-head"><h3>نتیجهٔ یک تماس آزمایشی</h3></div>'+
      '<div class="row scenario-tools" aria-label="سناریوهای آماده">'+
      button('در ساعت کاری','route-scenario','compact','data-scenario="work"')+
      button('خارج ساعت کاری','route-scenario','compact','data-scenario="closed"')+
      button('اختلال دستیار','route-scenario','compact','data-scenario="error"')+
      '</div>'+
      '<form id="route-test" class="form-grid">'+
      '<label>ساعت تماس<input type="time" name="time" value="12:00" required></label>'+
      '<label>وضعیت تماس<select name="mode"><option value="normal">تماس عادی</option><option value="error">اختلال دستیار</option></select></label>'+
      '<label class="wide">مسیر این آزمون<select name="profile">'+options([['default','طبق مسیر ذخیره‌شده'],...testProfiles],'default')+'</select></label>'+
      '<div class="wide"><button class="btn" type="submit">نمایش مسیر</button></div>'+
      '</form><div id="route-result" class="route-preview" aria-live="polite" hidden></div>'+
      '</section></div></div>';
  }

  function saveRoute(form) {
    const values = new FormData(form);
    const next = Object.fromEntries(Object.keys(defaultRoute).map(field => [field,values.get(field)]));
    if (!isValidRoute(next)) {
      notify('زمان شروع و پایان باید معتبر و متفاوت باشند.');
      return;
    }
    route = next;
    byId('route-result').hidden = true;
    try {
      localStorage.setItem(key, JSON.stringify(route));
      notify('قواعد مسیر نمونه در مرورگر ذخیره شد.');
    } catch {
      notify('قواعد برای این نشست اعمال شد. ذخیره در مرورگر در دسترس نیست.');
    }
  }

  function testRoute(form) {
    const values = new FormData(form);
    const time = values.get('time');
    if (!validTime(time)) return;
    const inHours = route.start < route.end
      ? time >= route.start && time < route.end
      : time >= route.start || time < route.end;
    const profile = values.get('profile') === 'default' ? route.testProfile : values.get('profile');
    const steps = ['تماس با خط اصلی'];
    if (!inHours) steps.push('خارج ساعت کاری',route.afterHours);
    else if (!profile) steps.push('ساعت کاری','پاسخ‌گویی انسانی',route.fallback);
    else if (values.get('mode') === 'error') steps.push('ساعت کاری','اختلال دستیار',route.fallback);
    else steps.push('ساعت کاری','داخلی آزمایشی 890','دستیار آزمایشی');
    const result = byId('route-result');
    result.innerHTML = '<div class="result"><strong>مسیر در ساعت <bdi>'+e(time)+
      '</bdi></strong>'+routeStrip(steps)+'</div>';
    result.hidden = false;
  }

  function fillScenario(scenario) {
    const form = byId('route-test');
    form.elements.time.value = scenario === 'closed' ? route.end : route.start;
    form.elements.mode.value = scenario === 'error' ? 'error' : 'normal';
    form.elements.profile.value = scenario === 'error' ? 'pilot' : 'default';
    testRoute(form);
  }

  function hasRouteChanges() {
    const form = byId('route-editor');
    if (!form) return false;
    const values = new FormData(form);
    return Object.keys(defaultRoute).some(field => values.get(field) !== route[field]);
  }

  function setMenu(open) {
    byId('sidebar').classList.toggle('open',open);
    byId('menu').setAttribute('aria-expanded',String(open));
  }

  function render() {
    const nav = '<nav aria-label="بخش‌های مرکز تلفن" class="tabs workspace-nav">'+tabs.map(([id,label]) =>
      '<button type="button" class="tab" data-tab="'+id+'" aria-current="'+(id === activeTab)+'">'+label+'</button>'
    ).join('')+'</nav>';
    const action = activeTab === 'main-line'
      ? '<button type="button" class="btn primary" data-tab="routing">آزمون مسیر</button>'
      : '<button type="button" class="btn primary" data-tab="main-line">بررسی خط‌ها</button>';
    const hero = '<header class="hero"><div class="wave" aria-hidden="true"></div>'+
      '<div class="spread"><div><h1 id="page-heading" tabindex="-1">مرکز تلفن گرین‌لایف</h1>'+
      '<p>آمادگی خط‌ها، گزارش بررسی و آزمون مسیر پاسخ‌گویی</p></div>'+action+'</div></header>';
    const view = {overview,'main-line':readiness.mainLine,history:activity.historyView,lines,routing}[activeTab];
    screen.innerHTML = hero+nav+view();
  }

  function activateTab(id, updateHash=true, focusTarget='') {
    if (!tabs.some(([tab]) => tab === id)) return;
    if (id === activeTab) {
      if (focusTarget) byId(focusTarget)?.focus();
      return;
    }
    if (hasRouteChanges() && !window.confirm('تغییرات ذخیره‌نشده کنار گذاشته شوند؟')) {
      if (!updateHash) history.replaceState(null,'','#'+activeTab);
      return;
    }
    activeTab = id;
    if (updateHash) history.pushState(null,'','#'+id);
    render();
    window.scrollTo(0,0);
    const target = focusTarget && byId(focusTarget);
    if (target) target.focus();
    else screen.querySelector('.tab[aria-current="true"]').focus({preventScroll:true});
  }

  document.addEventListener('click',event => {
    const control = event.target.closest('[data-action],[data-tab],[data-period],#menu');
    if (!control || control.disabled) return;
    if (control.id === 'menu') {
      setMenu(control.getAttribute('aria-expanded') !== 'true');
    } else if (control.dataset.tab) {
      activateTab(control.dataset.tab,true,control.dataset.focusTarget);
    } else if (control.dataset.action === 'close') {
      dialog.close();
    } else if (control.dataset.action === 'route-scenario') {
      fillScenario(control.dataset.scenario);
    } else if (!readiness.handleClick(control)) {
      activity.handleClick(control);
    }
  });

  document.addEventListener('submit',event => {
    const form = event.target;
    if (form.id === 'route-editor') {
      event.preventDefault();
      saveRoute(form);
    } else if (form.id === 'route-test') {
      event.preventDefault();
      testRoute(form);
    } else if (readiness.handleSubmit(form) || activity.handleSubmit(form)) {
      event.preventDefault();
    }
  });
  document.addEventListener('input',event => {
    if (!readiness.handleInput(event.target)) activity.handleInput(event.target);
  });
  document.addEventListener('change',event => {
    if (!readiness.handleChange(event.target)) activity.handleChange(event.target);
  });
  document.addEventListener('keydown',event => {
    if (event.key === 'Escape' && byId('sidebar').classList.contains('open') && !dialog.open) {
      setMenu(false);
      byId('menu').focus();
    }
  });

  function tabFromHash() {
    return tabs.find(([id]) => '#'+id === location.hash)?.[0] ?? 'overview';
  }
  window.addEventListener('hashchange',() => activateTab(tabFromHash(),false));
  activeTab = tabFromHash();
  render();
})();
