// docs/assets/chat.js
const API_BASE = localStorage.getItem('API_BASE') || 'https://<your-vercel>.vercel.app';

const qs = sel => document.querySelector(sel);
function escapeHtml(s){ return (s||'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;","">":"&gt;","\"":"&quot;","'":"&#39;"}[c])) }

function getFilters(){
  const f = (window.FeedFilters || {});
  return {
    tags: Array.from(f.selectedTags || []),
    sources: Array.from(f.selectedSources || []),
    categories: Array.from(f.selectedCats || []),
    date_from_days: f.dateWindowDays || 0
  };
}

function ensurePanel(){
  if (qs('#chatFab')) return;

  const fab = document.createElement('button');
  fab.id = 'chatFab';
  fab.className = 'chat-fab';
  fab.title = 'Ask AI';
  fab.innerHTML = '💬';
  document.body.appendChild(fab);

  const panel = document.createElement('div');
  panel.id = 'chatPanel';
  panel.className = 'chat-panel hidden';
  panel.innerHTML = `
    <div class="chat-head">
      <strong>Ask AI</strong>
      <div class="spacer"></div>
      <div class="chat-tools">
        <label class="file"><input id="chatFile" type="file" multiple accept=".txt,.md,.csv,.pdf" />Attach</label>
        <button id="chatExport" class="icon-btn" title="Export to Google Docs" disabled>↥ Export</button>
        <label class="remote"><input id="chatRemote" type="checkbox" /> <span>Remote</span></label>
        <button id="chatClose" class="icon-btn" title="Close">✕</button>
      </div>
    </div>
    <div id="chatMsgs" class="chat-msgs"></div>
    <form id="chatForm" class="chat-form">
      <input id="chatInput" type="text" placeholder="Ask about EU docs, EUR-Lex, ECB..." autocomplete="off" />
      <button class="btn" type="submit">Send</button>
    </form>
    <div id="chatHint" class="chat-hint">${API_BASE ? '' : 'Set API_BASE: localStorage.setItem(\"API_BASE\",\"https://<your-vercel>.vercel.app\")'}</div>
  `;
  document.body.appendChild(panel);

  const msgs   = qs('#chatMsgs');
  const input  = qs('#chatInput');
  const remote = qs('#chatRemote');
  const exportBtn = qs('#chatExport');
  const fileInput = qs('#chatFile');

  function add(role, html){
    const el = document.createElement('div');
    el.className = `msg ${role}`;
    el.innerHTML = html;
    msgs.appendChild(el);
    msgs.scrollTop = msgs.scrollHeight;
  }

  fab.onclick = () => panel.classList.toggle('hidden');
  qs('#chatClose').onclick = () => panel.classList.add('hidden');

  // store last answer for export
  let lastAnswer = '';
  let lastResults = [];

  // attachments (client-side extracted text)
  const attachments = [];
  fileInput.onchange = async () => {
    if (!fileInput.files?.length) return;
    for (const f of fileInput.files) {
      const text = await readTextFromFile(f).catch(()=> '');
      if (text) attachments.push({ name: f.name, mime: f.type || 'text/plain', text: text.slice(0, 200000) }); // cap
    }
    add('assistant', `<em>Attached ${attachments.length} file(s).</em>`);
  };

  async function readTextFromFile(file){
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (file.type.startsWith('text/') || ['txt','md','csv','json'].includes(ext)){
      return await file.text();
    }
    if (ext === 'pdf'){
      // light-weight PDF text (best-effort)
      try{
        const pdfMod = await import('https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.mjs');
        const buf = await file.arrayBuffer();
        const pdf = await pdfMod.getDocument({ data: buf }).promise;
        let out = '';
        const maxPages = Math.min(pdf.numPages, 20);
        for (let i=1;i<=maxPages;i++){
          const page = await pdf.getPage(i);
          const tc = await page.getTextContent();
          out += tc.items.map(x=>x.str).join(' ') + '\n';
        }
        return out;
      }catch(e){ console.warn('pdf extract failed:', e); return ''; }
    }
    // other types: skip
    return '';
  }

  const history = [];
  qs('#chatForm').onsubmit = async (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    add('user', escapeHtml(q));
    history.push({ role:'user', content:q });
    input.value = '';

    if (!API_BASE){
      add('assistant', `<em>API_BASE not set.</em>`);
      return;
    }

    try{
      const payload = {
        messages: history,
        top_k: 8,
        filters: getFilters(),
        remote: !!remote.checked,
        attachments
      };
      const r = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error('Chat API failed');
      const j = await r.json();
      lastAnswer = j.answer || '';
      lastResults = j.results || [];
      history.push({ role:'assistant', content:lastAnswer });
      const sources = lastResults.map((it,i)=>`<a href="${escapeHtml(it.url||'#')}" target="_blank">[${i+1}]</a>`).join(' ');
      add('assistant', `${escapeHtml(lastAnswer || '(no answer)')}<div class="cit">${sources}</div>`);
      exportBtn.disabled = !lastAnswer;
    }catch(err){
      console.warn(err);
      add('assistant', `<em>${escapeHtml(err.message || String(err))}</em>`);
    }
  };

  // Export to Google Docs
  exportBtn.onclick = async () => {
    if (!API_BASE || !lastAnswer) return;
    exportBtn.disabled = true;
    try{
      const title = (history.findLast ? history.findLast(m=>m.role==='user') : history[history.length-1]).content.slice(0,80);
      const payload = {
        title: `AI — ${title}`,
        answer: lastAnswer,
        sources: lastResults.map((r,i)=>({ n:i+1, title:r.title, url:r.url, date:(r.added||r.date||'').slice(0,10), source:r.source||r.kind }))
      };
      const r = await fetch(`${API_BASE}/api/export_doc`, {
        method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(payload)
      });
      const j = await r.json();
      if (j?.url){
        add('assistant', `Saved to Google Docs: <a href="${escapeHtml(j.url)}" target="_blank">${escapeHtml(j.url)}</a>`);
      } else {
        add('assistant', `<em>Export failed.</em>`);
      }
    }catch(e){
      add('assistant', `<em>${escapeHtml(e.message || String(e))}</em>`);
    }finally{
      exportBtn.disabled = false;
    }
  };
}

ensurePanel();
