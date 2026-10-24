/* Executive navigation taxonomy. Edit GROUPS and ROUTES to move an entry; existing Django permissions remain authoritative. */
(()=>{const GROUPS=[["مدیریت","◈"],["بازاریابی","◎"],["درمان","✚"],["مالی","▧"],["پرسنل","♙"],["شعب","△"],["تنظیمات","⚙"]];
const ROUTES=[
["مدیریت",/\/(live|action-center|meeting-minutes|reports|my-office|kpi|server-health|quality|management|targets|notifications)\b/],
["بازاریابی",/\/(lead-management|lead-command|instagram|referrals|referral|call-center|whatsapp|bulk-sms|marketing-sms|sms-management|website-lead)\b/],
["درمان",/\/(doctor|consultant|appointments|patient|scan|device-issues|device-booking|diet|treatment|reception|service-requests|customer-requests)\b/],
["مالی",/\/(finance|payments|payroll)\b/],
["پرسنل",/\/(employees|attendance|shift|tasks|my-tasks|blackboard|guidelines|sop|requests|messages|profile)\b/],
["شعب",/\/(camp|branch)\b/],
["تنظیمات",/\/(credentials|credential|api-server|staff-security|security|device-capacity|treatment-catalog|treatment-content|call-center-group)\b/]
];
const SPECIAL=[["تنظیمات",/credential_settings|panel-preview|تنظیمات برنامه غذایی|تنظیمات خدمات|صفحات پرسنل|گروه‌های کال/],["مدیریت",/وضعیت سرور|کنترل کیفیت|تارگت|صورت.جلس|مرکز اقدام/],["مالی",/درخواست پرداخت|هزینه‌ها|درآمد/],["پرسنل",/حقوق/],["بازاریابی",/اتصال اینستاگرام|لیدهای سایت|پیامک/]];
function classify(a){const label=(a.textContent||"").trim();for(const [g,re] of SPECIAL)if(re.test(label))return g;const u=new URL(a.href,location.href);for(const [g,re] of ROUTES)if(re.test(u.pathname))return g;return "مدیریت"}
function run(){const nav=document.querySelector(".app-sidebar .app-nav");if(!nav||nav.dataset.grouped||!document.body.classList.contains("gl-executive-nav-enabled"))return;
const source=[...nav.children];const links=[];
for(const el of source){if(el.matches("a[href]")&&!el.classList.contains("mobile-more-toggle")&&el.getAttribute("href")!=="#")links.push(el);
else if(el.matches("details.gl-settings-menu"))links.push(...el.querySelectorAll(".gl-settings-submenu > a[href]"));}
/* Move only authorized executive payment links into the central menu.
   Do not alter permission checks: links are rendered server-side first. */
const footer=document.querySelector(".app-sidebar .sidebar-footer");
const footerFinance=footer?[...footer.querySelectorAll('a[href]')].filter(a=>/\/payments\//.test(a.getAttribute("href")||"")):[];
links.push(...footerFinance);
const seen=new Set(),byGroup=new Map(GROUPS.map(([name])=>[name,[]]));
for(const a of links){if(a.closest(".mobile-more-menu"))continue;const href=a.getAttribute("href");if(!href||href==="#")continue;const norm=href.replace(/#.*$/,"");if(seen.has(norm)){if(footerFinance.includes(a))a.remove();continue;}seen.add(norm);byGroup.get(classify(a)).push(a)}
/* Finance submenu: explicit order and labels; only existing permission-granted anchors. */
const financeOrder=[
  [/^\/finance\/?$/,0,"درآمد"],
  [/^\/payments\/expenses\/?$/,1,"هزینه‌ها"],
  [/^\/payments\/admin\/?$/,2,"دستور پرداخت"],
  [/^\/payments\/accounting\/?$/,3,"حسابداری"],
  [/^\/payments\/?$/,4,"درخواست پرداخت"]
];
const financeItems=byGroup.get("مالی")||[];
for(const a of financeItems){
 const pathname=new URL(a.href,location.href).pathname;
 const rule=financeOrder.find(([regex])=>regex.test(pathname));
 if(rule){const label=a.querySelector("span:last-child");if(label)label.textContent=rule[2];else a.textContent=rule[2];}
 if(/^\/payments\/admin\/?$/.test(pathname))a.dataset.finRank="2";
 else if(/^\/payments\/?$/.test(pathname))a.dataset.finRank="4";
 else if(/^\/payments\/expenses\/?$/.test(pathname))a.dataset.finRank="1";
 else if(/^\/payments\/accounting\/?$/.test(pathname))a.dataset.finRank="3";
 else if(/^\/finance\/?$/.test(pathname))a.dataset.finRank="0";
 else a.dataset.finRank="8";
}
financeItems.sort((a,b)=>Number(a.dataset.finRank)-Number(b.dataset.finRank));
const region=document.createDocumentFragment();for(const [name,ico] of GROUPS){const items=byGroup.get(name);if(!items.length)continue;const det=document.createElement("details");det.className="gl-nav-group";const summary=document.createElement("summary");summary.innerHTML='<span class="nav-ico" aria-hidden="true">'+ico+'</span><span>'+name+'</span><span class="settings-caret" aria-hidden="true">⌄</span>';det.appendChild(summary);const wrap=document.createElement("div");wrap.className="gl-nav-children";for(const a of items)wrap.appendChild(a);det.appendChild(wrap);if(!new URLSearchParams(location.search).has("shortcut") && items.some(a=>a.classList.contains("is-active")||a.getAttribute("href")===location.pathname))det.open=true;region.appendChild(det)}
const previous=document.createElement("div");previous.hidden=true;previous.className="gl-legacy-menu-backup";for(const el of [...nav.children])previous.appendChild(el);nav.appendChild(previous);nav.appendChild(region);nav.classList.add("gl-grouped-nav");nav.dataset.grouped="1";nav.querySelectorAll(".gl-nav-group").forEach(item=>item.addEventListener("toggle",()=>{if(item.open)nav.querySelectorAll(".gl-nav-group").forEach(other=>{if(other!==item)other.open=false})}));}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",run);else run();
})();
