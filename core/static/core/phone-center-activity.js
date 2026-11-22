'use strict';

window.createPhoneCenterActivity = function ({e, fa, chip, button, options, detailRows, routeStrip, showDialog}) {
  const statuses = {
    active:['در مکالمه','green'],
    waiting:['در صف','amber'],
    answered:['پاسخ داده شد','green'],
    missed:['بی‌پاسخ','red'],
    diverted:['ارجاع شد','violet'],
  };
  const directions = {inbound:'ورودی', outbound:'خروجی'};
  const activeSamples = [
    {id:'GL-108', day:0, time:'12:05', branch:'نیاوران', direction:'inbound', person:'یاسمن', queue:'پاسخ‌گویی اولیه', seconds:81, status:'active'},
    {id:'GL-109', day:0, time:'12:06', branch:'پونک', direction:'inbound', person:'صف کال‌سنتر', queue:'مشاوره', seconds:42, status:'waiting'},
    {id:'GL-110', day:0, time:'12:06', branch:'اصفهان', direction:'inbound', person:'پذیرش شعبه', queue:'نوبت‌دهی', seconds:18, status:'waiting'},
  ];
  const historySamples = [
    {id:'GL-107', day:0, time:'12:02', branch:'پونک', direction:'inbound', person:'کال‌سنتر', queue:'مشاوره', seconds:196, status:'answered', recorded:true},
    {id:'GL-106', day:0, time:'11:56', branch:'نیاوران', direction:'inbound', person:'یاسمن ← پذیرش', queue:'نوبت‌دهی', seconds:168, status:'diverted', recorded:true},
    {id:'GL-105', day:0, time:'11:43', branch:'اصفهان', direction:'inbound', person:'پذیرش شعبه', queue:'نوبت‌دهی', seconds:50, status:'missed'},
    {id:'GL-104', day:0, time:'11:30', branch:'افسریه', direction:'outbound', person:'کال‌سنتر', queue:'پیگیری', seconds:245, status:'answered', recorded:true},
    {id:'GL-103', day:0, time:'11:10', branch:'نیاوران', direction:'inbound', person:'پذیرش شعبه', queue:'نوبت‌دهی', seconds:38, status:'missed'},
    {id:'GL-102', day:0, time:'10:24', branch:'پونک', direction:'inbound', person:'کال‌سنتر', queue:'مشاوره', seconds:122, status:'answered', recorded:true},
    {id:'GL-101', day:0, time:'09:15', branch:'افسریه', direction:'inbound', person:'پذیرش شعبه', queue:'پاسخ‌گویی اولیه', seconds:74, status:'answered'},
    {id:'GL-100', day:1, time:'15:16', branch:'اصفهان', direction:'inbound', person:'کال‌سنتر', queue:'مشاوره', seconds:238, status:'answered'},
    {id:'GL-099', day:1, time:'11:38', branch:'نیاوران', direction:'inbound', person:'پذیرش شعبه', queue:'نوبت‌دهی', seconds:63, status:'missed'},
    {id:'GL-098', day:2, time:'16:31', branch:'پونک', direction:'inbound', person:'پذیرش شعبه', queue:'نوبت‌دهی', seconds:147, status:'answered'},
    {id:'GL-097', day:3, time:'12:16', branch:'نیاوران', direction:'inbound', person:'کال‌سنتر ← پذیرش', queue:'مشاوره', seconds:309, status:'diverted'},
    {id:'GL-096', day:4, time:'12:03', branch:'اصفهان', direction:'inbound', person:'پذیرش شعبه', queue:'نوبت‌دهی', seconds:198, status:'answered'},
    {id:'GL-095', day:5, time:'11:51', branch:'افسریه', direction:'inbound', person:'کال‌سنتر', queue:'پاسخ‌گویی اولیه', seconds:33, status:'missed'},
    {id:'GL-094', day:6, time:'10:07', branch:'پونک', direction:'inbound', person:'کال‌سنتر', queue:'مشاوره', seconds:114, status:'answered'},
  ];
  const allSamples = [...activeSamples, ...historySamples];
  const branches = [...new Set(historySamples.map(call => call.branch))].sort((a,b) => a.localeCompare(b,'fa'));
  const pageSize = 5;
  const defaultFilters = {q:'', branch:'', direction:'', status:'', period:'', sort:'newest'};
  const dateFormat = new Intl.DateTimeFormat('fa-IR', {dateStyle:'medium', timeZone:'Asia/Tehran'});
  const weekdayFormat = new Intl.DateTimeFormat('fa-IR', {weekday:'short', timeZone:'Asia/Tehran'});
  let filters = {...defaultFilters};
  let page = 1;
  let chartPeriod = 'week';

  const byId = id => document.getElementById(id);
  const sampleDate = day => new Date(Date.UTC(2026, 10, 22 - day, 12));
  const statusChip = call => chip(...statuses[call.status],true);
  const duration = seconds => [Math.floor(seconds / 60), seconds % 60]
    .map(value => String(value).padStart(2,'0')).join(':');
  const timeOfSample = call => {
    const [hour, minute] = call.time.split(':').map(Number);
    return -call.day * 1440 + hour * 60 + minute;
  };

  function normalize(value) {
    const numerals = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩';
    return value.normalize('NFKC').toLocaleLowerCase('fa')
      .replace(/[۰-۹٠-٩]/g, digit => String(numerals.indexOf(digit) % 10))
      .replace(/[يى]/g,'ی').replace(/ك/g,'ک').replace(/\u200c/g,' ')
      .replace(/\s+/g,' ').trim();
  }

  function matchHistory() {
    const query = normalize(filters.q).split(' ').filter(Boolean);
    return historySamples.filter(call => {
      const status = statuses[call.status][0];
      const values = normalize([call.id, call.branch, call.person, call.queue, status, directions[call.direction], call.time].join(' '));
      return (!filters.branch || call.branch === filters.branch) &&
        (!filters.direction || call.direction === filters.direction) &&
        (!filters.status || call.status === filters.status) &&
        (!filters.period || call.day <= Number(filters.period)) &&
        query.every(word => values.includes(word));
    }).sort((a,b) => {
      const byStart = timeOfSample(b) - timeOfSample(a);
      if (filters.sort === 'oldest') return -byStart;
      if (filters.sort === 'longest') return b.seconds - a.seconds || byStart;
      return byStart;
    });
  }

  function resultsPage() {
    const records = matchHistory();
    const total = records.length;
    const pages = Math.max(1,Math.ceil(total / pageSize));
    page = Math.min(page, pages);
    const start = (page - 1) * pageSize;
    return {records:records.slice(start,start+pageSize), total, pages, start};
  }

  function resultCount(result) {
    if (!result.total) return '۰ تماس نمونه';
    return 'نمایش '+fa(result.start + 1)+' تا '+fa(result.start + result.records.length)+
      ' از '+fa(result.total)+' تماس نمونه';
  }

  function historyRows(records) {
    if (!records.length) {
      return '<p class="empty-state">با فیلترهای فعلی تماسی پیدا نشد.</p>';
    }
    return records.map(call => '<article class="history-record">'+
      '<div class="history-record-main"><strong class="ltr">'+e(call.id)+'</strong>'+
      '<small>'+e(dateFormat.format(sampleDate(call.day)))+' · <bdi dir="ltr">'+e(call.time)+'</bdi></small>'+
      chip(directions[call.direction])+'</div>'+
      '<dl class="history-record-meta">'+
      '<div><dt>شعبه</dt><dd>'+e(call.branch)+'</dd></div>'+
      '<div><dt>صف</dt><dd>'+e(call.queue)+'</dd></div>'+
      '<div><dt>پاسخ‌دهنده یا مقصد</dt><dd>'+e(call.person)+'</dd></div>'+
      '<div><dt>'+e(call.status === 'missed' ? 'مدت انتظار' : 'مدت تماس')+'</dt><dd><bdi dir="ltr">'+duration(call.seconds)+'</bdi></dd></div>'+
      '</dl><div class="history-record-status">'+statusChip(call)+
      button('جزئیات','call','compact','data-id="'+e(call.id)+'" aria-label="جزئیات تماس '+e(call.id)+'"')+
      '</div></article>').join('');
  }

  function pagination(result) {
    return '<nav id="history-pagination" class="history-pagination spread" aria-label="صفحه‌بندی تماس‌های نمونه"'+
      (result.pages <= 1 ? ' hidden' : '')+'><span id="history-page-count" class="small">'+pageCount(result)+'</span>'+
      '<div class="row">'+button('قبلی','history-page','compact','id="history-prev" data-step="-1"'+
      (page === 1 ? ' disabled' : ''))+button('بعدی','history-page','compact','id="history-next" data-step="1"'+
      (page === result.pages ? ' disabled' : ''))+'</div></nav>';
  }

  function pageCount(result) {
    return 'صفحهٔ '+fa(page)+' از '+fa(result.pages);
  }

  function filtersApplied() {
    return Object.keys(defaultFilters).some(name => filters[name] !== defaultFilters[name]);
  }

  function filterSelect(label, name, choices) {
    return '<label>'+label+'<select name="'+name+'">'+options(choices,filters[name])+'</select></label>';
  }

  function historyView() {
    const result = resultsPage();
    return '<section class="panel activity-section"><div class="panel-head spread">'+
      '<div><h2>سابقهٔ تماس‌ها</h2><p class="small">تماس‌های پایان‌یافتهٔ بازهٔ نمونهٔ '+e(dateFormat.format(sampleDate(6)))+
      ' تا '+e(dateFormat.format(sampleDate(0)))+'</p></div>'+chip('دادهٔ نمونه','violet',true)+'</div>'+
      '<form id="filters" class="filters activity-filters" role="search" aria-label="جست‌وجو و فیلتر تماس‌ها">'+
      '<label>جست‌وجوی تماس<input name="q" type="search" maxlength="100" value="'+e(filters.q)+'" placeholder="شناسه، پاسخ‌دهنده یا صف"></label>'+
      filterSelect('شعبه','branch',[['','همهٔ شعبه‌ها'],...branches])+
      filterSelect('نوع تماس','direction',[['','همهٔ تماس‌ها'],...Object.entries(directions)])+
      filterSelect('نتیجه','status',[['','همهٔ وضعیت‌ها'],...['answered','missed','diverted'].map(id => [id,statuses[id][0]])])+
      filterSelect('بازه','period',[['','همهٔ روزهای نمونه'],['0','آخرین روز نمونه'],['2','سه روز آخر نمونه']])+
      filterSelect('ترتیب','sort',[['newest','جدیدترین'],['oldest','قدیمی‌ترین'],['longest','بیشترین مدت']])+
      '</form><div class="activity-toolbar spread"><p id="history-result-count" class="activity-meta small" aria-live="polite">'+
      resultCount(result)+'</p>'+button('پاک کردن فیلترها','clear-call-filters','compact ghost',
      'id="history-clear"'+(filtersApplied() ? '' : ' disabled'))+'</div>'+
      '<div id="history-rows" class="history-grid">'+historyRows(result.records)+'</div>'+pagination(result)+'</section>';
  }

  function activeRow(call) {
    return button('<span class="call-person"><span class="avatar" aria-hidden="true">☎</span>'+
      '<span><strong>'+e(call.branch)+'</strong><small>'+e(call.queue)+'</small></span></span>'+
      '<span><strong>'+e(call.person)+'</strong><small><bdi dir="ltr">'+duration(call.seconds)+'</bdi></small></span>'+
      statusChip(call),'call','call-row','data-id="'+e(call.id)+'" aria-label="جزئیات تماس نمونه '+e(call.id)+'"');
  }

  function chartData() {
    const inbound = historySamples.filter(call => call.direction === 'inbound');
    const groups = chartPeriod === 'week'
      ? Array.from({length:7},(_, index) => {
        const day = 6 - index;
        return [weekdayFormat.format(sampleDate(day)), inbound.filter(call => call.day === day)];
      })
      : [9,10,11,12].map(hour => [fa(hour)+':۰۰',
        inbound.filter(call => call.day === 0 && Number(call.time.slice(0,2)) === hour)]);
    return groups.map(([label,calls]) => {
      const missed = calls.filter(call => call.status === 'missed').length;
      return {label, handled:calls.length - missed, missed};
    });
  }

  function chart() {
    const buckets = chartData();
    const max = Math.max(1,...buckets.flatMap(bucket => [bucket.handled,bucket.missed]));
    const total = buckets.reduce((sum,bucket) => sum + bucket.handled + bucket.missed,0);
    const missed = buckets.reduce((sum,bucket) => sum + bucket.missed,0);
    const label = buckets.map(bucket => bucket.label+'، '+fa(bucket.handled)+' پاسخ یا ارجاع و '+fa(bucket.missed)+' بی‌پاسخ').join('، ');
    const bar = (value, type) => value
      ? '<span class="bar '+type+'" style="height:'+value / max * 87+'%"></span>' : '';
    return '<div class="chart-totals row"><span class="small">کل ورودی <strong>'+fa(total)+'</strong></span>'+
      '<span class="small">پاسخ یا ارجاع <strong>'+fa(total - missed)+'</strong></span>'+
      '<span class="small">بی‌پاسخ <strong>'+fa(missed)+'</strong></span></div>'+
      '<div class="chart" role="img" aria-label="'+e('نمودار نمونهٔ تماس ورودی، '+label)+'">'+
      '<div class="bars">'+buckets.map(bucket => '<div class="bar-group" title="'+e(bucket.label+'، '+
        fa(bucket.handled)+' پاسخ یا ارجاع، '+fa(bucket.missed)+' بی‌پاسخ')+'">'+bar(bucket.handled,'')+bar(bucket.missed,'miss')+'</div>').join('')+
      '</div><div class="chart-labels">'+buckets.map(bucket => '<span>'+e(bucket.label)+'</span>').join('')+'</div></div>'+
      '<div class="legend"><span><i style="background:var(--green)" aria-hidden="true"></i>پاسخ یا ارجاع</span>'+
      '<span><i style="background:var(--red)" aria-hidden="true"></i>بی‌پاسخ</span></div>';
  }

  function overview() {
    const waiting = activeSamples.filter(call => call.status === 'waiting').length;
    const ranges = [['today','روز نمونه'],['week','هفت روز نمونه']];
    return '<section class="stack activity-section" aria-labelledby="sample-activity-title">'+
      '<div class="section-heading spread"><h2 id="sample-activity-title">نمایش نمونهٔ تماس‌ها</h2>'+
      '<button type="button" class="btn compact ghost" data-tab="history">مشاهدهٔ سابقهٔ نمونه</button></div>'+
      '<div class="duo"><section class="panel"><div class="panel-head spread"><h3>مکالمه و صف انتظار</h3>'+
      chip(fa(waiting)+' در صف نمونه','amber',true)+'</div>'+
      '<div class="call-list">'+activeSamples.map(activeRow).join('')+'</div></section>'+
      '<section class="panel"><div class="panel-head spread"><h3>روند تماس‌های ورودی نمونه</h3>'+
      '<div class="segment" role="group" aria-label="بازهٔ نمودار">'+ranges.map(([id,label]) =>
        '<button type="button" data-period="'+id+'" aria-pressed="'+(chartPeriod === id)+'">'+label+'</button>'
      ).join('')+'</div></div><div id="chart">'+chart()+'</div></section></div></section>';
  }

  function queueView() {
    const queues = ['صف کال‌سنتر','پذیرش شعبه','صف پیگیری'];
    return '<section class="panel"><div class="panel-head spread"><h2>صف‌های انتظار</h2>'+
      chip('دادهٔ نمونه','violet')+'</div>'+detailRows(queues.map(queue => {
        const waiting = activeSamples.filter(call => call.status === 'waiting' && call.person === queue).length;
        return [e(queue), waiting ? chip(fa(waiting)+' منتظر','amber') : chip('بدون انتظار')];
      }))+'</section>';
  }

  function selectCall(id) {
    const call = allSamples.find(item => item.id === id);
    if (!call) return;
    const isWaiting = ['waiting','missed'].includes(call.status);
    showDialog('تماس نمونهٔ <bdi dir="ltr">'+e(call.id)+'</bdi>',
      '<div class="activity-toolbar spread">'+statusChip(call)+chip('دادهٔ نمونه','violet')+'</div>'+
      detailRows([
        ['تاریخ و ساعت', e(dateFormat.format(sampleDate(call.day)))+' · <bdi dir="ltr">'+e(call.time)+'</bdi>'],
        ['شعبه',e(call.branch)],
        ['نوع تماس',e(directions[call.direction])],
        ['صف',e(call.queue)],
        ['پاسخ‌دهنده یا مقصد',e(call.person)],
        [isWaiting ? 'مدت انتظار' : 'مدت تماس','<bdi dir="ltr">'+duration(call.seconds)+'</bdi>'],
        ['ثبت ضبط در نمونه',call.recorded ? 'ثبت شده' : 'ثبت نشده'],
      ])+routeStrip(['تماس '+directions[call.direction],call.queue,statuses[call.status][0]]));
  }

  function updateHistory(changedPage = false) {
    const rows = byId('history-rows');
    if (!rows) return;
    const result = resultsPage();
    rows.innerHTML = historyRows(result.records);
    byId('history-result-count').textContent = resultCount(result);
    byId('history-page-count').textContent = pageCount(result);
    byId('history-pagination').hidden = result.pages <= 1;
    const previous = byId('history-prev');
    const next = byId('history-next');
    const focused = document.activeElement;
    previous.disabled = page === 1;
    next.disabled = page === result.pages;
    byId('history-clear').disabled = !filtersApplied();
    if (changedPage && focused === previous && previous.disabled) next.focus();
    if (changedPage && focused === next && next.disabled) previous.focus();
  }

  function filterHistory(form) {
    const values = new FormData(form);
    filters = Object.fromEntries(Object.keys(defaultFilters).map(name => [name,values.get(name) ?? defaultFilters[name]]));
    page = 1;
    updateHistory();
  }

  function handleClick(control) {
    const period = control.dataset.period;
    if (period === 'today' || period === 'week') {
      chartPeriod = period;
      const chartContainer = byId('chart');
      if (!chartContainer) return true;
      chartContainer.innerHTML = chart();
      control.closest('.segment').querySelectorAll('[data-period]').forEach(item => {
        item.setAttribute('aria-pressed',String(item.dataset.period === chartPeriod));
      });
      return true;
    }
    switch (control.dataset.action) {
      case 'call':
        selectCall(control.dataset.id);
        return true;
      case 'history-page':
        if (control.disabled) return true;
        page = Math.max(1,page + Number(control.dataset.step));
        updateHistory(true);
        return true;
      case 'clear-call-filters': {
        const form = byId('filters');
        if (!form) return true;
        for (const [name,value] of Object.entries(defaultFilters)) {
          form.elements[name].value = value;
        }
        filterHistory(form);
        form.elements.q.focus();
        return true;
      }
      default:
        return false;
    }
  }

  function handleInput(target) {
    if (target.form?.id !== 'filters' || target.name !== 'q') return false;
    filterHistory(target.form);
    return true;
  }

  function handleChange(target) {
    if (target.form?.id !== 'filters' || target.name === 'q') return false;
    filterHistory(target.form);
    return true;
  }

  function handleSubmit(form) {
    if (form.id !== 'filters') return false;
    filterHistory(form);
    return true;
  }

  return {overview,historyView,queueView,handleClick,handleInput,handleChange,handleSubmit};
};
