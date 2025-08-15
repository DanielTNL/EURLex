
// ---- Configure this in the browser console once you deploy the API ----
// localStorage.setItem('API_BASE','https://<your-vercel>.vercel.app');

const API_BASE = localStorage.getItem('API_BASE') || '';

let POSTS = [];
let REPORTS = [];
let TAGS = new Map();
let selectedTags = new Set();
let selectedSources = new Set();
let selectedCats = new Set();
let typePosts = true, typeReports = true;
let dateWindowDays = 7;

const els = {
  q: document.getElementById('q'),
  askAi: document.getElementById('askAi'),
  pillbar: document.getElementById('pillbar'),
  feed: document.getElementById('feed'),
  keyItems: document.getElementById('keyItems'),
  timeline: document.getElementById('timeline'),
  answerSection: document.getElementById('answerSection'),
  answer: document.getElementById('answer'),
  aiResults: document.getElementById('aiResults'),
  notice: document.getElementById('notice'),
  lastSynced: document.getElementById('lastSynced'),
  fltSources: document.getElementById('fltSources'),
  fltCats: document.getElementById('fltCats'),
  fltTypePosts: document.getElementById('fltTypePosts'),
  fltTypeReports: document.getElementById('fltTypeReports'),
  refreshBtn: document.getElementById('refreshBtn'),
  clearBtn: document.getElementById('clearBtn'),
};

function showNotice(msg, kind='info'){
  els.notice.textContent = msg;
  els.notice.hidden = !msg;
}

const escapeHTML = s => (s||'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const fmtDate = d => new Date(d).toISOString().slice(0,10);

async function loadJSON(path){
  const r = await fetch(path + '?v=' + Date.now(), {cache:'no-store'});
  if(!r.ok) throw new Error('Fetch failed: ' + path);
  return r.json();
}

async function loadData(){
  try{
    showNotice('');
    const [posts, reports] = await Promise.all([
      loadJSON('./data/posts.json'),
      loadJSON('./data/reports.json')
    ]);
    POSTS = posts; REPORTS = reports;
    buildFacets();
    renderFilters();
    renderAll();
    els.lastSynced.textContent = new Date().toLocaleString();
  }catch(e){
    console.error(e);
    showNotice('Could not load data: ' + e.message);
  }
}

function buildFacets(){
  TAGS = new Map();
  const sources = new Set();

  for(const p of POSTS){
    sources.add(p.source || 'Unknown');
    for(const t of (p.tags||[])) TAGS.set(t,(TAGS.get(t)||0)+1);
  }
  for(const r of REPORTS){
    for(const t of (r.tags||[])) TAGS.set(t,(TAGS.get(t)||0)+1);
  }

  // Fill sources select
  els.fltSources.innerHTML = Array.from(sources).sort().map(s=>`<option>${escapeHTML(s)}</option>`).join('');
  // Preselect none (means “all”)
}

function renderFilters(){
  // Tag pills (top 60)
  const pills = Array.from(TAGS.entries()).sort((a,b)=>b[1]-a[1]).slice(0,60);
  els.pillbar.innerHTML = pills.map(([t,c]) =>
    `<button class="pill" aria-pressed="${selectedTags.has(t)}" data-tag="${escapeHTML(t)}">${escapeHTML(t)} · ${c}</button>`
  ).join('');
  els.pillbar.querySelectorAll('.pill').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const tag = btn.dataset.tag;
      if(selectedTags.has(tag)) selectedTags.delete(tag); else selectedTags.add(tag);
      btn.setAttribute('aria-pressed', selectedTags.has(tag));
      renderAll();
    });
  });

  // Inputs
  els.fltSources.onchange = ()=>{ selectedSources = new Set(Array.from(els.fltSources.selectedOptions).map(o=>o.value)); renderAll(); };
  els.fltCats.onchange = ()=>{ selectedCats = new Set(Array.from(els.fltCats.selectedOptions).map(o=>o.value)); renderAll(); };
  els.fltTypePosts.onchange = ()=>{ typePosts = els.fltTypePosts.checked; renderAll(); };
  els.fltTypeReports.onchange = ()=>{ typeReports = els.fltTypeReports.checked; renderAll(); };
  document.querySelectorAll('input[name="datewin"]').forEach(r => r.onchange = ()=>{ dateWindowDays = Number(r.value); renderAll(); });

  els.q.addEventListener('input', ()=>{ renderAll(); debounceAskAi(); });
  els.askAi.addEventListener('change', ()=>{ maybeAskAi(); });

  els.refreshBtn.onclick = ()=>{ caches && caches.keys().then(keys=>keys.forEach(k=>caches.delete(k))); loadData(); };
  els.clearBtn.onclick = ()=>{ selectedTags.clear(); selectedSources.clear(); selectedCats.clear(); els.q.value=''; renderFilters(); renderAll(); };
}

function withinDateWindow(iso){
  if(!iso || !dateWindowDays) return true;
  const since = Date.now() - dateWindowDays*24*3600*1000;
  return new Date(iso).getTime() >= since;
}

function passesFilters(item, isReport=false){
  // type
  if(isReport && !typeReports) return false;
  if(!isReport && !typePosts) return false;

  // date
  const dt = item.added || item.date;
  if(!withinDateWindow(dt)) return false;

  // sources
  if(!isReport && selectedSources.size && !selectedSources.has(item.source||'Unknown')) return false;

  // categories (we added category names to tags in builder)
  if(selectedCats.size){
    const tags = new Set(item.tags||[]);
    let ok=false;
    for(const c of selectedCats){ if(tags.has(c)) {ok=true; break;} }
    if(!ok) return false;
  }

  // tags
  if(selectedTags.size){
    const tags = new Set(item.tags||[]);
    for(const t of selectedTags){ if(!tags.has(t)) return false; }
  }

  // keyword search
  const q = els.q.value.trim().toLowerCase();
  if(q){
    const hay = (item.title + ' ' + (item.summary||item.abstract||'') + ' ' + (item.tags||[]).join(' ')).toLowerCase();
    if(!hay.includes(q)) return false;
  }

  return true;
}

function cardForItem(p){
  const tags = (p.tags||[]).map(t=>`<span class="tag">${escapeHTML(t)}</span>`).join('');
  const when = escapeHTML((p.added ? fmtDate(p.added) : p.date) || '');
  return `<article class="card">
    <h3><a href="${escapeHTML(p.url)}" target="_blank" rel="noopener">${escapeHTML(p.title)}</a></h3>
    <div class="meta">${escapeHTML(p.source || (p.added ? 'Post' : 'Report'))} • ${when}</div>
    <p class="summary">${escapeHTML((p.summary||p.abstract||'').slice(0,300))}${(p.summary||p.abstract||'').length>300?'…':''}</p>
    <div>${tags}</div>
  </article>`;
}

function renderFeed(){
  let items = POSTS.filter(p=>passesFilters(p,false));
  els.feed.innerHTML = items.length ? items.map(cardForItem).join('') : '<p>No items match.</p>';
}

function renderKeyItems(){
  const list = [];
  for(const r of REPORTS){ for(const k of (r.key_items||[])){ list.push({text:k, tags:r.tags||[], date:r.date, url:r.url_html||'#'}); } }
  const items = list.filter(x=>{
    // category/tag filters
    if(selectedCats.size && !x.tags.some(t=>selectedCats.has(t))) return false;
    if(selectedTags.size){ for(const t of selectedTags){ if(!x.tags.includes(t)) return false; } }
    // date
    if(!withinDateWindow(x.date)) return false;
    // search
    const q = els.q.value.trim().toLowerCase();
    if(q && !(x.text + ' ' + x.tags.join(' ')).toLowerCase().includes(q)) return false;
    return true;
  });
  els.keyItems.innerHTML = items.length ? items.map(x=>`<li><a href="${escapeHTML(x.url)}">${escapeHTML(x.text)}</a> <span class="tag">${escapeHTML(x.date)}</span></li>`).join('') : '<li>No key items.</li>';
}

function renderTimeline(){
  const items = REPORTS.filter(r=>passesFilters(r,true));
  els.timeline.innerHTML = items.length ? items.map(r=>`
    <div class="tl-row">
      <div class="tl-date">${escapeHTML(r.date)}</div>
      <div class="tl-node">
        <div><a href="${escapeHTML(r.url_html||'#')}" target="_blank" rel="noopener">${escapeHTML(r.title)}</a></div>
        <div class="meta">${(r.tags||[]).map(t=>`<span class="tag">${escapeHTML(t)}</span>`).join('')}</div>
      </div>
    </div>`).join('') : '<p>No reports yet.</p>';
}

function renderAll(){ renderFeed(); renderKeyItems(); renderTimeline(); }

// ---- Ask AI ----
let askTimer;
function debounceAskAi(){ clearTimeout(askTimer); askTimer = setTimeout(maybeAskAi, 400); }
async function maybeAskAi(){
  const q = els.q.value.trim();
  if(!els.askAi.checked || !q){ els.answerSection.hidden = true; return; }
  if(!API_BASE){ showNotice('Ask AI is enabled but API_BASE is not set. Open the console and run: localStorage.setItem(\"API_BASE\",\"https://<your-vercel>.vercel.app\")'); els.answerSection.hidden = true; return; }
  try{
    const payload = {
      query: q,
      top_k: 8,
      remote: false,
      tags: Array.from(selectedTags)
    };
    const r = await fetch(`${API_BASE}/api/search`, { method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(payload) });
    if(!r.ok) throw new Error('AI search failed');
    const j = await r.json();
    els.answerSection.hidden = false;
    els.answer.innerHTML = `<p>${escapeHTML(j.answer || 'No model answer (missing API key on server).')}</p>`;
    els.aiResults.innerHTML = (j.results||[]).map(cardForItem).join('');
  }catch(e){ console.warn(e); els.answerSection.hidden = true; }
}

// ---- SW registration (new strategy relies on dynamic fetch for /data) ----
if('serviceWorker' in navigator){
  navigator.serviceWorker.register('./assets/sw.js').catch(()=>{});
}

// Boot
loadData();
