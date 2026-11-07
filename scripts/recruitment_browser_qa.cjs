/* Browser checks run only against the disposable, seeded CI application. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const fixturePath = process.argv[2];
const output = path.resolve(process.argv[3] || 'qa-artifacts');
if (process.env.RECRUITMENT_UI_QA !== '1' || !fixturePath) {
  throw new Error('RECRUITMENT_UI_QA=1 and an isolated fixture are required.');
}
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const origin = 'http://127.0.0.1:8010';
const workspacePath = '/management/recruitment/';
fs.mkdirSync(output, {recursive:true});

async function assertNoOverflow(page, label) {
  const result = await page.evaluate(() => ({
    viewport:document.documentElement.clientWidth,
    content:document.documentElement.scrollWidth,
    dialog:document.querySelector('#rh-dialog')?.open
      ? document.querySelector('#rh-dialog').getBoundingClientRect().toJSON() : null,
  }));
  if (result.content > result.viewport + 2) {
    result.overflowElements = await page.evaluate(() => [...document.querySelectorAll('body *')]
      .map(el=>({el,rect:el.getBoundingClientRect(),css:getComputedStyle(el)}))
      .filter(({rect,css})=>rect.width>0 && rect.height>0 && css.visibility!=='hidden'
        && (rect.left < -2 || rect.right > document.documentElement.clientWidth+2))
      .slice(0,25).map(({el,rect,css})=>({tag:el.tagName,id:el.id,classes:el.className,
        left:rect.left,right:rect.right,width:rect.width,minWidth:css.minWidth,
        display:css.display,overflowX:css.overflowX,position:css.position})));
  }
  assert(result.content <= result.viewport + 2, `${label}: page overflow ${JSON.stringify(result)}`);
  if (result.dialog) {
    assert(result.dialog.left >= -1 && result.dialog.right <= result.viewport+1,
      `${label}: dialog falls outside viewport ${JSON.stringify(result)}`);
  }
}

async function waitReady(page) {
  await page.locator('#recruitment-workspace').waitFor();
  await page.waitForFunction(() =>
    document.querySelector('#rh-content')?.getAttribute('aria-busy') !== 'true'
    && !document.querySelector('#rh-content .rh-loading'));
  await page.evaluate(() => Promise.race([
    document.fonts.ready, new Promise(resolve=>setTimeout(resolve,2000)),
  ]));
}

async function select(page, name, value) {
  await page.locator(`#rh-dialog [name="${name}"]`).selectOption(String(value));
}

async function fill(page, name, value) {
  await page.locator(`#rh-dialog [name="${name}"]`).fill(String(value));
}

async function submit(page, suffix, expectedStatus=200, formKind=null) {
  const responsePromise=page.waitForResponse(response =>
    response.url() === origin + workspacePath + 'api/' + suffix
    && response.request().method() === 'POST');
  const selector=formKind ? `#rh-dialog form[data-form="${formKind}"] button[type="submit"]`
    : '#rh-dialog form button[type="submit"]';
  const submittedForm=await page.locator(selector).first().evaluateHandle(button=>button.closest('form'));
  await page.locator(selector).first().click();
  const response=await responsePromise;
  const data=await response.json();
  assert.equal(response.status(),expectedStatus,JSON.stringify(data));
  assert.equal(data.ok,expectedStatus>=200 && expectedStatus<300,JSON.stringify(data));
  // A response arrives before the UI finishes its follow-up refresh/render.
  await page.waitForFunction(form=>!form.isConnected || form.dataset.busy!=='1',submittedForm);
  await submittedForm.dispose();
  return data;
}

async function closeDialog(page) {
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>!document.querySelector('#rh-dialog').open);
}

(async()=>{
  const browser=await chromium.launch({headless:true});
  const errors=[];
  const failures=[];
  let page;
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'fa-IR',timezoneId:'Asia/Tehran'});
    await context.addCookies([fixture.cookie]);
    page=await context.newPage();
    page.on('pageerror',error=>errors.push(error.message));
    page.on('response',response=>{
      if (response.url().startsWith(origin) && response.status()>=500)
        failures.push(`${response.status()} ${response.url()}`);
    });
    await page.goto(origin+workspacePath,{waitUntil:'domcontentloaded'});
    await waitReady(page);
    assert.equal(await page.locator('#rh-title').textContent(),'استخدام');
    const management=page.locator('.gl-nav-group').filter({has:page.locator('summary').filter({hasText:'مدیریت'})});
    assert.equal(await management.locator(`a[href="${workspacePath}"]`).count(),1,
      'Recruitment must appear exactly once inside Management.');
    await page.evaluate(()=>{window.__recruitmentQaDocument='same-document';});
    await assertNoOverflow(page,'desktop initial');
    await page.screenshot({path:path.join(output,'01-desktop-positions.png'),fullPage:true});

    // All six views must switch within the current document.
    for(const tab of ['applications','followups','ads','onboarding','talent','jobs']) {
      await page.locator(`[data-tab="${tab}"]`).click();
      await waitReady(page);
      assert(await page.locator(`[data-tab="${tab}"]`).evaluate(el=>el.classList.contains('is-active')),
        `Tab ${tab} did not become active.`);
      assert.equal(await page.evaluate(()=>window.__recruitmentQaDocument),'same-document');
      await assertNoOverflow(page,`desktop tab ${tab}`);
    }

    // Native dialog close must restore focus to its opener.
    const createJob=page.locator('.rh-actions [data-action="create-job"]');
    await createJob.click();
    await page.locator('#rh-dialog[open]').waitFor();
    await closeDialog(page);
    assert(await createJob.evaluate(el=>el===document.activeElement),'Dialog focus did not return to opener.');

    await createJob.click();
    const title='هماهنگ‌کننده استخدام — آزمون مرورگر';
    await fill(page,'title',title);
    await select(page,'country',fixture.country_id);
    await select(page,'owner',fixture.user_id);
    await select(page,'organization','office');
    await select(page,'status','open');
    await fill(page,'headcount','1');
    await fill(page,'description','شرح کار آزمایشی برای کنترل ذخیره‌سازی فرم.');
    await fill(page,'requirements','دقت و پیگیری');
    await fill(page,'expected_outcomes','ثبت کامل اطلاعات و پیگیری به‌موقع');
    await fill(page,'salary_min','40000000');
    await fill(page,'salary_max','20000000');
    await submit(page,'jobs/',400);
    assert.equal(await page.locator('#rh-dialog [name="title"]').inputValue(),title,
      'Validation error erased entered data.');
    assert(await page.locator('#rh-dialog').evaluate(el=>el.open),'Invalid form closed prematurely.');
    await fill(page,'salary_max','50000000');
    const createdJob=await submit(page,'jobs/');
    assert(createdJob.job.id,'Job response omitted id.');
    await page.waitForFunction(()=>!document.querySelector('#rh-dialog').open);
    await waitReady(page);

    await page.locator('.rh-actions [data-action="create-application"]').click();
    await page.locator('#rh-dialog[open]').waitFor();
    await fill(page,'name','متقاضی آزمایشی مرورگر');
    await fill(page,'phone','۰۹۰۰۰۰۰۰۹۹۹');
    await select(page,'job',createdJob.job.id);
    await select(page,'owner',fixture.user_id);
    await fill(page,'next_action','تماس اولیه آزمایشی');
    const tomorrow=new Date(Date.now()+86400000);
    await fill(page,'next_action_at',tomorrow.toISOString().slice(0,16));
    await fill(page,'requested_salary','35000000');
    const createdApplication=await submit(page,'applications/');
    assert(createdApplication.application.id,'Application response omitted id.');
    await page.waitForFunction(()=>!document.querySelector('#rh-dialog').open);
    await waitReady(page);

    // Search for the saved record, open its real detail, and verify that it is persisted.
    await page.locator('[data-tab="applications"]').click();
    await waitReady(page);
    await page.locator('#rh-search').fill('متقاضی آزمایشی مرورگر');
    await page.getByText('متقاضی آزمایشی مرورگر',{exact:true}).first().waitFor();
    await page.getByText('متقاضی آزمایشی مرورگر',{exact:true}).first().click();
    await page.locator('#rh-dialog[open]').waitFor();
    await page.locator('#rh-dialog-body').getByText('متقاضی آزمایشی مرورگر',{exact:true}).first().waitFor();
    await assertNoOverflow(page,'desktop detail');
    await page.screenshot({path:path.join(output,'02-desktop-applicant.png'),fullPage:true});

    const applicationEndpoint=`applications/${createdApplication.application.id}/`;
    await page.locator('[data-detail-tab="evaluation"]').click();
    for(const input of await page.locator('#rh-dialog [data-score]').all()) await input.fill('84');
    await fill(page,'evidence','نتیجه آزمون مرورگر: تکلیف مرتبط کامل شد.');
    await select(page,'recommendation','advance');
    const evaluation=await submit(page,applicationEndpoint,200,'evaluate');
    assert.equal(evaluation.application.evaluations.length,1,'Independent evaluation did not persist.');
    assert.equal(Number(evaluation.application.evaluations[0].total),84,'Evaluation weighting changed scores.');
    await page.locator('#rh-dialog .rh-evaluation').waitFor();

    await page.locator('[data-detail-tab="history"]').click();
    await fill(page,'text','یادداشت آزمایشی مرورگر برای پیگیری تماس');
    const note=await submit(page,applicationEndpoint,200,'note');
    assert(note.application.activities.some(activity=>activity.text.includes('یادداشت آزمایشی مرورگر')),
      'Saved note is missing from audit history.');
    await page.locator('.rh-timeline').getByText('یادداشت آزمایشی مرورگر برای پیگیری تماس',{exact:true}).waitFor();

    await page.locator('[data-detail-tab="followup"]').click();
    await select(page,'stage','rejected');
    await fill(page,'decision_reason','');
    await submit(page,applicationEndpoint,400,'update');
    assert.equal(await page.locator('#rh-dialog [name="stage"]').inputValue(),'rejected',
      'Rejected decision validation lost form state.');
    await select(page,'stage','screening');
    await fill(page,'next_action','پیگیری ثبت‌شده در آزمون مرورگر');
    const followup=await submit(page,applicationEndpoint,200,'update');
    assert.equal(followup.application.stage,'screening');
    await page.waitForFunction(()=>document.querySelector('#rh-dialog [name="next_action"]')?.value==='پیگیری ثبت‌شده در آزمون مرورگر');
    await closeDialog(page);
    await page.locator('#rh-search').fill('');

    await page.locator('.rh-actions [data-action="create-ad"]').click();
    await select(page,'job',createdJob.job.id);
    await fill(page,'title','آگهی ثبت‌شده در آزمون مرورگر');
    await fill(page,'body','متن ساختگی؛ هیچ انتشار خارجی انجام نمی‌شود.');
    await select(page,'status','active');
    await submit(page,'ads/',400,'ad');
    assert.equal(await page.locator('#rh-dialog [name="title"]').inputValue(),'آگهی ثبت‌شده در آزمون مرورگر');
    await select(page,'status','draft');
    await submit(page,'ads/',200,'ad');
    await page.waitForFunction(()=>!document.querySelector('#rh-dialog').open);
    await waitReady(page);

    for(const [label,width,height] of [['tablet',820,1180],['mobile',390,844]]) {
      await page.setViewportSize({width,height});
      await page.locator('[data-tab="jobs"]').click();
      await waitReady(page);
      await assertNoOverflow(page,`${label} positions`);
      await page.screenshot({path:path.join(output,`03-${label}-positions.png`),fullPage:true});
      await page.locator('[data-tab="applications"]').click();
      await waitReady(page);
      await assertNoOverflow(page,`${label} applicants`);
      await page.getByText('متقاضی آزمایشی 1',{exact:true}).first().click();
      await page.locator('#rh-dialog[open]').waitFor();
      await page.locator('#rh-dialog .rh-detail-person h3').filter({hasText:'متقاضی آزمایشی 1'}).waitFor();
      await assertNoOverflow(page,`${label} detail`);
      await page.screenshot({path:path.join(output,`04-${label}-applicant.png`),fullPage:true});
      await closeDialog(page);
    }
    assert.equal(await page.evaluate(()=>window.__recruitmentQaDocument),'same-document',
      'Recruitment workflow unexpectedly reloaded the page.');
    assert.deepEqual(errors,[],'Uncaught frontend errors');
    assert.deepEqual(failures,[],'Server failed during browser workflow');
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({
      ok:true,viewports:['1440x1000','820x1180','390x844'],
      checks:['management-menu','six-tabs','same-document','dialog-focus','server-validation-preserves-input',
        'create-job','create-application','persisted-applicant-detail','evaluation','audit-note',
        'required-rejection-reason','followup','ad-registration','responsive-overflow','no-js-errors'],
    },null,2));
    console.log('Recruitment browser workflow passed at desktop, tablet, and mobile sizes.');
  } catch(error) {
    if(page) await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});
    fs.writeFileSync(path.join(output,'failure.json'),JSON.stringify({message:error.message,stack:error.stack,errors,failures},null,2));
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
