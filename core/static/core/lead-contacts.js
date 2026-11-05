(function(){
  'use strict';
  function latin(value){return String(value||'').replace(/[۰-۹٠-٩]/g,function(c){var n=c.charCodeAt(0);return String(n>=1776?n-1776:n-1632);});}
  function element(tag,text,attrs){var e=document.createElement(tag);if(text!==null)e.textContent=text;Object.keys(attrs||{}).forEach(function(k){e.setAttribute(k,attrs[k]);});return e;}
  function wa(number){number=latin(number).replace(/[^0-9+]/g,'');if(/^09\d{9}$/.test(number))number='98'+number.slice(1);return 'https://wa.me/'+number.replace(/^\+/,'');}
  function syncLinks(control){var select=control.querySelector('[data-contact-select]'),scope=control.closest('.cc-work-row,.cc-card');if(!scope)return;var number=select.value;scope.querySelectorAll('a.ccx-action.call,.cc-phone a').forEach(function(a){a.href='tel:'+number;a.dataset.phone=number;});scope.querySelectorAll('a.ccx-action.wa,[data-contact-whatsapp]').forEach(function(a){a.href=wa(number);});var label=scope.querySelector('.cc-phone b');if(label)label.textContent=number;}
  document.querySelectorAll('[data-contact-select]').forEach(function(select){select.addEventListener('change',function(){syncLinks(select.closest('.lead-contact-control'));});});
  document.querySelectorAll('.lead-extra-phones-input').forEach(function(source){
    var box=source.closest('.lead-extra-fields')||source.parentElement,rows=element('div'),add=element('button','＋ شمارهٔ دیگر',{type:'button'});
    function sync(){source.value=Array.from(rows.querySelectorAll('input')).map(function(i){return latin(i.value).trim();}).filter(Boolean).join('\n');}
    function addRow(value){if(rows.children.length>=10)return;var row=element('div',null,{class:'lead-phone-edit-row'}),input=element('input',null,{type:'tel','aria-label':'شمارهٔ دیگر',maxlength:'30',dir:'ltr'}),remove=element('button','×',{type:'button','aria-label':'برداشتن شمارهٔ دیگر'});input.value=value||'';input.addEventListener('input',sync);remove.addEventListener('click',function(){row.remove();sync();});row.append(input,remove);rows.append(row);return input;}
    source.value.split(/[\n,،;]+/).map(function(x){return x.trim();}).filter(Boolean).forEach(addRow);
    source.hidden=true;box.append(rows,add);add.addEventListener('click',function(){var input=addRow('');if(input)input.focus();});if(source.form)source.form.addEventListener('submit',sync);
  });
  var dialog=document.getElementById('leadContactDialog');if(!dialog)return;
  var form=dialog.querySelector('form'),fields=dialog.querySelector('[data-contact-fields]'),message=dialog.querySelector('[data-contact-message]'),history=dialog.querySelector('[data-contact-history]'),add=dialog.querySelector('[data-contact-add]'),save=dialog.querySelector('[data-contact-save]');
  var current=null,version='',busy=false,sequence=0;
  function setBusy(value){busy=value;save.disabled=value;add.disabled=value;fields.querySelectorAll('input,button').forEach(function(e){e.disabled=value;});}
  function request(url,options){var abort=new AbortController(),timer=setTimeout(function(){abort.abort();},15000);return fetch(url,Object.assign({credentials:'same-origin',cache:'no-store',signal:abort.signal},options)).then(function(r){if(r.redirected)throw new Error('نشست یا امنیت صفحه تازه‌سازی شد؛ صفحه را دوباره باز کنید.');return r.json().then(function(d){if(!r.ok||!d.ok)throw new Error(d.error||'دریافت اطلاعات انجام نشد.');return d;});}).finally(function(){clearTimeout(timer);});}
  function row(value,primary){if(fields.children.length>=11)return;var wrap=element('div',null,{class:'lead-phone-edit-row'}),label=element('label'),radio=element('input',null,{type:'radio',name:'primary'}),input=element('input',null,{type:'tel',dir:'ltr',maxlength:'30',required:'','aria-label':'شماره تلفن'}),remove=element('button','×',{type:'button','aria-label':'برداشتن این شماره'});radio.checked=primary;label.append(radio,document.createTextNode('اصلی'));input.value=value;input.addEventListener('input',function(){input.value=latin(input.value);});remove.addEventListener('click',function(){if(fields.children.length===1)return;var selected=radio.checked;wrap.remove();if(selected)fields.querySelector('input[type=radio]').checked=true;});wrap.append(label,input,remove);fields.append(wrap);return input;}
  document.querySelectorAll('[data-contact-edit]').forEach(function(button){button.addEventListener('click',function(){
    current=button.closest('.lead-contact-control');var ticket=++sequence;version='';fields.replaceChildren();history.replaceChildren();message.textContent='در حال دریافت شماره‌ها…';dialog.showModal();setBusy(true);
    request(current.dataset.contactUrl).then(function(data){if(ticket!==sequence)return;version=data.version;data.numbers.forEach(function(n,i){row(n,i===0);});
      (data.history||[]).forEach(function(item){var a=element('article');a.append(element('strong',item.actor+' · '+item.at),element('div','قبل: '+item.before.join(' / ')),element('div','بعد: '+item.after.join(' / ')));history.append(a);});if(!history.children.length)history.textContent='هنوز ویرایشی ثبت نشده است.';message.textContent='';
    }).catch(function(error){if(ticket===sequence)message.textContent=error.message||'اتصال برقرار نشد؛ دوباره امتحان کنید.';}).finally(function(){if(ticket===sequence){setBusy(false);save.disabled=!version;}});
  });});
  dialog.querySelectorAll('[data-contact-close]').forEach(function(b){b.addEventListener('click',function(){if(!busy)dialog.close();});});
  dialog.addEventListener('cancel',function(e){if(busy)e.preventDefault();});
  dialog.addEventListener('close',function(){sequence++;});
  add.addEventListener('click',function(){if(!busy){var input=row('',false);if(input)input.focus();}});
  form.addEventListener('submit',function(e){e.preventDefault();if(busy||!version||!form.reportValidity())return;var values=Array.from(fields.children),primary=values.find(function(r){return r.querySelector('input[type=radio]').checked;});if(!primary)return;var number=primary.querySelector('input[type=tel]').value,others=values.filter(function(r){return r!==primary;}).map(function(r){return r.querySelector('input[type=tel]').value;});setBusy(true);message.textContent='در حال ذخیره…';
    request(current.dataset.contactUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value},body:JSON.stringify({phone:number,additional:others,version:version})}).then(function(data){
      var select=current.querySelector('[data-contact-select]');select.replaceChildren();data.numbers.forEach(function(n,i){select.append(element('option',n+(i===0?' · اصلی':''),{value:n}));});select.value=data.phone;syncLinks(current);version=data.version;message.textContent='شماره‌ها ذخیره شد ✓';
      // Refresh cached search/counters and every secondary display from the server.
      window.location.reload();
    }).catch(function(error){message.textContent=error.name==='AbortError'?'پاسخ سرور نرسید؛ پنجره را دوباره باز کنید تا وضعیت ثبت بررسی شود.':error.message;}).finally(function(){setBusy(false);});
  });
})();
