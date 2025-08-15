const API_BASE = localStorage.getItem('API_BASE') || '';

const $ = id => document.getElementById(id);
const els = {
  q: $('q'), askAi: $('askAi'), feed: $('feed'),
  srcBar: $('srcBar'), tagBar: $('tagBar'),
  resources: $('resources'),
  notice: $('notice'),
  answerSection: $('answerSection'), answer: $('answer'), aiResults: $('aiResults')
};

let POSTS=[], TAGS=new Map(), selectedTags=new Set(), selectedSources=new Set(), dateWindowDays=0;

const esc = s => (s||'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const fmt = d => new Date(d).toISOString().slice(0,10);
const inWin = iso => !dateWindowDays || !iso || (new Date(iso).getTime() >= Date.now()-dateWindowDays*864e5);

async function jget(p){ const r=await fetch(p+'?v='+Date.now(),{cache:'no-store'}); if(!r.ok) throw new Error('Fetch '+p); return r.json(); }
function card(p){ return `<article class="card item">
  <h3><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></h3>
  <div class="meta">${esc(p.source||'Source')} • ${esc((p.added?fmt(p.added):p.date)||'')}</div>
  <p class="summary">${esc((p.summary||'').slice(0,360))}${(p.summary||'').length>360?'…':''}</p>
  <div>${(p.tags||[]).slice(0,8).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>
</article>`; }

function showNotice(msg){ els.notice.textContent=msg; els.notice.hidden=!msg; }

async function load(){
  try{
    const [posts, audio] = await Promise.all([
      jget('./data/posts.json'),
      jget('./data/audio.json').catch(()=>({google_drive:"",items:[]})),
    ]);
    POSTS = posts||[];

    // Resources
    const cards=[];
    if(audio.google_drive){ cards.push(`<article class="card"><h3>Google Drive</h3><p><a href="${esc(audio.google_drive)}" target="_blank">Open the Drive folder</a></p></article>`); }
    for(const a of (audio.items||[]).slice(0,12)){
      cards.push(`<article class="card"><h3>${esc(a.title)}</h3><div class="meta">${esc(a.date||'')}</div><audio controls preload="none" style="width:100%"><source src="${esc(a.raw_url)}" type="audio/mpeg"></audio></article>`);
    }
    els.resources.innerHTML = cards.join('') || '<p>Add Google Drive link and MP3s to show resources.</p>';

    // Facets
    const srcs = new Set();
    TAGS = new Map();
    for(const p of POSTS){ srcs.add(p.source||'Other'); (p.tags||[]).forEach(t=>TAGS.set(t,(TAGS.get(t)||0)+1)); }

    els.srcBar.innerHTML = Array.from(srcs).sort().map(s=>`<button class="pill" data-src="${esc(s)}" aria-pressed="${selectedSources.has(s)}">${esc(s)}</button>`).join('');
    els.srcBar.querySelectorAll('.pill').forEach(b=>b.onclick=()=>{ const v=b.dataset.src; if(selectedSources.has(v)) selectedSources.delete(v); else selectedSources.add(v); b.setAttribute('aria-pressed', selectedSources.has(v)); render(); });

    const topTags = Array.from(TAGS.entries()).sort((a,b)=>b[1]-a[1]).slice(0,100);
    els.tagBar.innerHTML = topTags.map(([t,c])=>`<button class="pill" data-tag="${esc(t)}" aria-pressed="${selectedTags.has(t)}">${esc(t)} · ${c}</button>`).join('');
    els.tagBar.querySelectorAll('.pill').forEach(b=>b.onclick=()=>{ const v=b.dataset.tag; if(selectedTags.has(v)) selectedTags.delete(v); else selectedTags.add(v); b.setAttribute('aria-pressed', selectedTags.has(v)); render(); });

    document.querySelectorAll('input[name="datewin"]').forEach(r=> r.onchange = ()=>{ dateWindowDays = Number(r.value); render(); });
    els.q.oninput = ()=>{ render(); debounceAsk(); };
    els.askAi.onchange = ()=> maybeAsk();

    render();
  }catch(e){ console.error(e); showNotice('Could not load data: '+e.message); }
}

function passes(p){
  if(dateWindowDays && !inWin(p.added||p.date)) return false;
  if(selectedSources.size && !selectedSources.has(p.source||'Other')) return false;
  if(selectedTags.size){ for(const t of selectedTags){ if(!(p.tags||[]).includes(t)) return false; } }
  const q = els.q.value.trim().toLowerCase();
  if(q){ const hay=(p.title+' '+(p.summary||'')+' '+(p.tags||[]).join(' ')).toLowerCase(); if(!hay.includes(q)) return false; }
  return true;
}

function render(){
  const arr = POSTS.filter(p=>passes(p)).sort((a,b)=> new Date(b.added||b.date) - new Date(a.added||a.date));
  els.feed.innerHTML = arr.map(card).join('') || '<p>No documents match.</p>';
  maybeAsk();
}

/* Ask AI */
let askTimer; function debounceAsk(){ clearTimeout(askTimer); askTimer = setTimeout(maybeAsk, 400); }
async function maybeAsk(){
  const q = els.q.value.trim();
  if(!els.askAi.checked || !q){ els.answerSection.hidden=true; return; }
  if(!API_BASE){ showNotice('Ask AI is enabled but API_BASE is not set. Open console and run: localStorage.setItem("API_BASE","https://<your-vercel>.vercel.app")'); els.answerSection.hidden=true; return; }
  try{
    const payload={ query:q, top_k:10, remote:false, tags:Array.from(selectedTags), sources:Array.from(selectedSources), date_from_days:dateWindowDays };
    const r = await fetch(`${API_BASE}/api/search`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
    if(!r.ok) throw new Error('AI search failed');
    const j = await r.json();
    els.answerSection.hidden=false;
    els.answer.innerHTML = `<p>${esc(j.answer || 'No model answer (server missing API key).')}</p>`;
    els.aiResults.innerHTML = (j.results||[]).map(p=>card(p)).join('');
  }catch(e){ console.warn(e); els.answerSection.hidden=true; }
}

if('serviceWorker' in navigator){ navigator.serviceWorker.register('./assets/sw.js').catch(()=>{}); }
import './theme.js';
load();
