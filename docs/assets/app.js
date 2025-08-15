// Set this in the console after Vercel deploy: localStorage.setItem('API_BASE','https://<your-vercel>.vercel.app')
const API_BASE = localStorage.getItem('API_BASE') || '';

let POSTS=[], REPORTS=[], AUDIO={google_drive:"", items:[]};
let TAGS=new Map(), selectedTags=new Set(), selectedSources=new Set(), selectedCats=new Set();
let typePosts=true, typeReports=true, dateWindowDays=0; // default: All

const $ = id => document.getElementById(id);
const els = {
  q: $('q'), askAi: $('askAi'), feed: $('feed'), keyItems: $('keyItems'),
  timeline: $('timeline'), answerSection: $('answerSection'), answer: $('answer'),
  aiResults: $('aiResults'), notice: $('notice'), lastSynced: $('lastSynced'),
  fltTypePosts: $('fltTypePosts'), fltTypeReports: $('fltTypeReports'),
  srcBar: $('srcBar'), catBar: $('catBar'), pillbar: $('pillbar'),
  refreshBtn: $('refreshBtn'), clearBtn: $('clearBtn'), resources: $('resources')
};

const esc = s => (s||'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const fmt = d => new Date(d).toISOString().slice(0,10);

async function jget(path){ const r=await fetch(path+'?v='+Date.now(),{cache:'no-store'}); if(!r.ok) throw new Error('Fetch '+path); return r.json(); }
function notice(msg){ els.notice.textContent = msg; els.notice.hidden = !msg; }

async function loadData(){
  try{
    const [posts,reports,audio] = await Promise.all([
      jget('./data/posts.json'),
      jget('./data/reports.json'),
      jget('./data/audio.json').catch(()=>({google_drive:"",items:[]})),
    ]);
    POSTS=posts||[]; REPORTS=reports||[]; AUDIO=audio||{google_drive:"",items:[]};

    // facets
    TAGS=new Map(); const sources=new Set();
    for(const p of POSTS){ (p.tags||[]).forEach(t=>TAGS.set(t,(TAGS.get(t)||0)+1)); sources.add(p.source||'Other'); }
    for(const r of REPORTS){ (r.tags||[]).forEach(t=>TAGS.set(t,(TAGS.get(t)||0)+1)); }

    // render source pills (static)
    els.srcBar.innerHTML = Array.from(sources).sort().map(s=>`<button class="pill" data-src="${esc(s)}" aria-pressed="${selectedSources.has(s)}">${esc(s)}</button>`).join('');
    els.srcBar.querySelectorAll('.pill').forEach(b=>b.onclick=()=>{ const v=b.dataset.src; if(selectedSources.has(v)) selectedSources.delete(v); else selectedSources.add(v); b.setAttribute('aria-pressed', selectedSources.has(v)); renderAll(); });

    // category pills (static)
    els.catBar.querySelectorAll('.pill').forEach(b=>b.onclick=()=>{ const v=b.dataset.cat; if(selectedCats.has(v)) selectedCats.delete(v); else selectedCats.add(v); b.setAttribute('aria-pressed', selectedCats.has(v)); renderAll(); });

    // tag pills (top 80, scrollable container)
    const topTags = Array.from(TAGS.entries()).sort((a,b)=>b[1]-a[1]).slice(0,80);
    els.pillbar.innerHTML = topTags.map(([t,c])=>`<button class="pill" data-tag="${esc(t)}" aria-pressed="${selectedTags.has(t)}">${esc(t)} · ${c}</button>`).join('');
    els.pillbar.querySelectorAll('.pill').forEach(b=>b.onclick=()=>{ const v=b.dataset.tag; if(selectedTags.has(v)) selectedTags.delete(v); else selectedTags.add(v); b.setAttribute('aria-pressed', selectedTags.has(v)); renderAll(); });

    // controls
    els.fltTypePosts.onchange = ()=>{ typePosts=els.fltTypePosts.checked; renderAll(); };
    els.fltTypeReports.onchange = ()=>{ typeReports=els.fltTypeReports.checked; renderAll(); };
    document.querySelectorAll('input[name="datewin"]').forEach(r=> r.onchange = ()=>{ dateWindowDays = Number(r.value); renderAll(); });
    els.q.oninput = ()=>{ renderAll(); debounceAsk(); };
    els.askAi.onchange = ()=> maybeAsk();
    els.refreshBtn.onclick = ()=>{ caches && caches.keys().then(keys=>keys.forEach(k=>caches.delete(k))); loadData(); };
    els.clearBtn.onclick = ()=>{ selectedTags.clear(); selectedSources.clear(); selectedCats.clear(); els.q.value=''; document.querySelector('input[name="datewin"][value="0"]').checked=true; dateWindowDays=0; renderAll(); };

    renderAll(); els.lastSynced.textContent = new Date().toLocaleString();
  }catch(e){ console.error(e); notice('Could not load data: '+e.message); }
}

const inWin = iso => !dateWindowDays || !iso || (new Date(iso).getTime() >= Date.now()-dateWindowDays*864e5);
function passes(item, isReport=false){
  if(isReport && !typeReports) return false;
  if(!isReport && !typePosts) return false;
  if(!inWin(item.added||item.date)) return false;
  if(selectedSources.size && !isReport && !selectedSources.has(item.source||'Other')) return false;
  if(selectedCats.size && !(item.tags||[]).some(t=>selectedCats.has(t))) return false;
  if(selectedTags.size){ for(const t of selectedTags){ if(!(item.tags||[]).includes(t)) return false; } }
  const q=els.q.value.trim().toLowerCase();
  if(q){ const hay=(item.title+' '+(item.summary||item.abstract||'')+' '+(item.tags||[]).join(' ')).toLowerCase(); if(!hay.includes(q)) return false; }
  return true;
}

const card = p => `<article class="card item">
  <h3><a href="${esc(p.url||'#')}" target="_blank" rel="noopener">${esc(p.title||'(no title)')}</a></h3>
  <div class="meta">${esc(p.source||'Report')} • ${esc((p.added?fmt(p.added):p.date)||'')}</div>
  <p class="summary">${esc((p.summary||p.abstract||'').slice(0,280))}${(p.summary||p.abstract||'').length>280?'…':''}</p>
  <div>${(p.tags||[]).slice(0,6).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
</article>`;

function renderFeed(){
  let items = POSTS.filter(p=>passes(p,false));
  items.sort((a,b)=> new Date(b.added||b.date) - new Date(a.added||a.date));
  items = items.slice(0, 10); // show only the latest 10 on the homepage
  els.feed.innerHTML = items.length ? items.map(card).join('') : '<p>No items match.</p>';
}

function renderKeyItems(){
  const list=[]; for(const r of REPORTS){ for(const k of (r.key_items||[])){ list.push({text:k, tags:r.tags||[], date:r.date, url:r.url_html||'#'}); } }
  const arr = list.filter(x => passes({title:x.text, summary:'', tags:x.tags, date:x.date}, true));
  els.keyItems.innerHTML = arr.length ? arr.map(x=>`<li><a href="${esc(x.url)}" target="_blank">${esc(x.text)}</a> <span class="tag">${esc(x.date)}</span></li>`).join('') : '<li>No key items.</li>';
}

function renderTimeline(){
  const arr = REPORTS.filter(r=>passes(r,true)).sort((a,b)=> new Date(b.date)-new Date(a.date));
  els.timeline.innerHTML = arr.length ? arr.map(r=>`
    <div class="tl-row"><div class="tl-date">${esc(r.date)}</div>
    <div class="tl-node"><div><a href="${esc(r.url_html||'#')}" target="_blank">${esc(r.title)}</a></div>
    <div class="meta">${(r.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></div></div>`).join('') : '<p>No reports yet.</p>';
}

function renderResources(){
  const cards = [];
  if(AUDIO.google_drive){ cards.push(`<article class="card"><h3>Google Drive</h3><p><a href="${esc(AUDIO.google_drive)}" target="_blank" rel="noopener">Open the Drive folder</a></p></article>`); }
  for(const a of (AUDIO.items||[]).slice(0,12)){
    cards.push(`<article class="card"><h3>${esc(a.title)}</h3><div class="meta">${esc(a.date||'')}</div><audio controls preload="none" style="width:100%"><source src="${esc(a.raw_url)}" type="audio/mpeg"></audio></article>`);
  }
  els.resources.innerHTML = cards.join('') || '<p>Add MP3s or Google Drive link to show resources here.</p>';
}

function renderAll(){ renderFeed(); renderKeyItems(); renderTimeline(); renderResources(); maybeAsk(); }

/* Ask AI */
let askTimer; function debounceAsk(){ clearTimeout(askTimer); askTimer=setTimeout(maybeAsk,400); }
async function maybeAsk(){
  const q = els.q.value.trim();
  if(!els.askAi.checked || !q){ els.answerSection.hidden=true; return; }
  if(!API_BASE){ notice('Ask AI is enabled but API_BASE is not set. Open console and run: localStorage.setItem("API_BASE","https://<your-vercel>.vercel.app")'); els.answerSection.hidden=true; return; }
  try{
    const payload={ query:q, top_k:8, remote:false, tags:Array.from(selectedTags), sources:Array.from(selectedSources), date_from_days:dateWindowDays };
    const r = await fetch(`${API_BASE}/api/search`, {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
    if(!r.ok) throw new Error('AI search failed');
    const j = await r.json();
    els.answerSection.hidden=false;
    els.answer.innerHTML = `<p>${esc(j.answer || 'No model answer (server missing API key).')}</p>`;
    els.aiResults.innerHTML = (j.results||[]).map(card).join('');
  }catch(e){ console.warn(e); els.answerSection.hidden=true; }
}

/* SW */
if('serviceWorker' in navigator){ navigator.serviceWorker.register('./assets/sw.js').catch(()=>{}); }
/* Always-blue theme (no UI to change) */
import './theme.js';

loadData();
