const { chromium } = require('playwright');
const fs=require('fs');
(async()=>{
 const f=JSON.parse(fs.readFileSync('/tmp/school-browser-fixture.json','utf8'));
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const reports=[]; fs.mkdirSync('schools-qa',{recursive:true});
 for(const [role,path] of [['admin','/schools/'],['consultant','/schools/'],['consultant','/schools/'+f.program+'/'],['consultant','/schools/new/'],['parent','/customer/family/'],['public','/customer/schools/'+f.token+'/'],['doctor','/schools/clinical/'+f.child+'/']]){
  for(const width of [1440,390]){
   const ctx=await browser.newContext({viewport:{width,height:1000}});
   if(role!=='public') await ctx.addCookies([{name:'sessionid',value:f.sessions[role],domain:'127.0.0.1',path:'/'}]);
   const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
   const res=await page.goto('http://127.0.0.1:8787'+path,{waitUntil:'networkidle'});
   const label=role+'-'+path.replace(/\W/g,'_')+'-'+width;
   await page.screenshot({path:'schools-qa/'+label+'.png',fullPage:true});
   const metrics=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,background:getComputedStyle(document.querySelector('.school-panel')||document.body).backgroundColor,body:document.body.innerText.slice(0,100)}));
   reports.push({role,path,width,status:res.status(),errors,...metrics});
   await ctx.close();
  }
 }
 fs.writeFileSync('schools-qa/results.json',JSON.stringify(reports,null,2));
 console.log(JSON.stringify(reports,null,2));
 if(reports.some(r=>r.status!==200||r.errors.length||r.scroll>r.width+2)) process.exitCode=1;
 await browser.close();
})();
