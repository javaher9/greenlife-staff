// Member inbox release 2026-11-15
/* Cache only the public companion shell. Never cache account/API/clinical responses. */
const CACHE='greenlife-me-shell-20261115-members2';
const SHELL=['/meal-journey.js','/meal-journey.css','/assets/pause-soft-30-v1.mp3','/assets/table/dining-table-v1.png','/app-readability.css','/mind-luxe.css','/assets/mind-breath-luxe-v1.png','/assets/mind-tomorrow-luxe-v1.png','/nutrition-hub.js','/nutrition-hub.css','/assets/nutrition-icons.png','/nutrition-data.js','/nutrition-save.js',"/nutrition-table.js","/nutrition-table.css","/assets/table/table-0.woff2","/assets/table/table-1.webp","/assets/table/table-2.webp",'/assets/icons-luxe/mind.webp','/assets/icons-luxe/food.webp','/assets/icons-luxe/move.webp','/entry-luxe.css','/visit-tracking.js','/visit-tracking.css','/visit.js','/visit.css','/movement-plans.js','/movement-art.js','/entry.js','/entry.css','/movement.js','/movement.css','/diet.js','/diet.css','/hypnosis-library.js','/hypnosis-library.css','/calm.css','/weekly.css','/rescue.js','/rescue.css','/my/','/my/index.html','/my/companion.css','/my/companion.js','/my/catalog.js','/my/member-core.js','/my/playback.js','/my/features.js','/my/features.css','/my/install.js','/account.js','/account.css','/migration-receiver.js','/my/heart-core.js','/my/heart-ui.js','/my/heart.css','/assets/heart-red-3d.png','/my/manifest.webmanifest','/my/icons/icon-192.png','/my/icons/icon-512.png','/journey-core.js','/assets/me-brand.css','/assets/greenlife-me-approved-v1.png','/assets/vazirmatn.woff2','/assets/estedad.woff','/assets/wall-portrait.webp','/assets/future-garden.webp','/assets/future-table.webp','/assets/hypnosis-same-woman.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL.map(url=>new Request(url,{cache:'reload'}))))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('greenlife-me-shell-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
  const url=new URL(e.request.url);
  if(e.request.method!=='GET'||url.origin!==self.location.origin)return;
  if(e.request.mode==='navigate'){
    if(!['/my/','/my/index.html'].includes(url.pathname))return;
    e.respondWith(fetch(e.request).catch(()=>caches.match('/my/index.html')));return;
  }
  if(SHELL.includes(url.pathname))e.respondWith(fetch(e.request).then(response=>{if(response.ok){const copy=response.clone();e.waitUntil(caches.open(CACHE).then(c=>c.put(url.pathname,copy)));}return response;}).catch(()=>caches.match(url.pathname)));
});
