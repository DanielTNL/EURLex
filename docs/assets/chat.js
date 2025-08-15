// Use localStorage override if present, otherwise fallback to your Vercel base
const API_BASE = localStorage.getItem('API_BASE') || 'https://<your-vercel>.vercel.app';

const qs = sel => document.querySelector(sel);
const $$ = sel => Array.from(document.querySelectorAll(sel));

function getFiltersFallback(){
  // Try to read filters exposed by app.js / live.js; otherwise defaults.
  const f = (window.FeedFilters || {});
  return {
    tags: Array.from(f.selectedTags || []),
    sources: Array.from(f.selectedSources || []),
    categories: Array.from(f.selectedCats || []),
    date_from_days: f.dateWindowDays || 0
  };
}

function ensurePanel(){
  if (qs('#chatFab')) return; // already on page

  // Floating Action Button
  const fab = document.createElement('button');
  fab.id = 'chatFab';
  fab.className = 'chat-fab';
  fab.title = 'Ask AI';
  fab.innerHTML = '💬';
  document.body.appendChild(fab);

  // Panel
  const panel = document.createElement('div');
  panel.id = 'chatPanel';
  panel.className = 'chat-panel hidden';
  panel.innerHTML = `
    <div class="chat-head">
      <strong>Ask AI</strong>
      <div class="spacer"></div>
      <label class="remote">
        <input id="chatRemote" type="checkbox" />
        <span title="Also fetch content from result links">Remote</span>
      </label>
      <button id="chatClose" class="icon-btn" title="Close">✕</button>
    </div>
    <div id="chatMsgs" class="chat-msgs"></div>
    <form id="chatForm" class="chat-form">
      <input id="chatInput" type="text" placeholder="Ask about EU docs, EUR-Lex, ECB..." autocomplete="off" />
      <button class="btn" type="submit">Send</button>
    </form>
    <div id="chatHint" class="chat-hint">${API_BASE ? '' : 'Set API_BASE in console: localStorage.setItem("API_BASE","https://<your-vercel>.vercel.app")'}</div>
  `;
  document.body.appendChild(panel);

  // Handlers
  fab.onclick = () => panel.classList.toggle('hidden');
  qs('#chatClose').onclick = () => panel.classList.add('hidden');

  const msgs = qs('#chatMsgs');
  const input = qs('#chatInput');
  const form = qs('#chatForm');

  /** simple renderer */
  function add(role, html){
    const el = document.createElement('div');
    el.className = `msg ${role}`;
    el.innerHTML = html;
    msgs.appendChild(el);
    msgs.scrollTop = msgs.scrollHeight;
  }

  // keep a chat history array for multi-turn
  const history = [];

  form.onsubmit = async (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    add('user', escapeHtml(q));
    history.push({ role: 'user', content: q });
    input.value = '';

    if (!API_BASE){
      add('assistant', `<em>API_BASE not set.</em>`);
      return;
    }

    try{
      const filters = getFiltersFallback();
      const payload = {
        messages: history,
        top_k: 8,
        filters,
        remote: qs('#chatRemote').checked === true
      };
      const r = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: {'content-type':'application/json'},
        body: JSON.stringify(payload)
      });
      if(!r.ok) throw new Error('Chat API failed');
      const j = await r.json();
      const answer = j.answer || '(no answer)';
      history.push({ role: 'assistant', content: answer });
      const sources = (j.results||[]).map((it,i)=>`<a href="${escapeHtml(it.url||'#')}" target="_blank">[${i+1}]</a>`).join(' ');
      add('assistant', `${escapeHtml(answer)}<div class="cit">${sources}</div>`);
    }catch(err){
      console.warn(err);
      add('assistant', `<em>${escapeHtml(err.message || String(err))}</em>`);
    }
  };
}

function escapeHtml(s){ return (s||'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])) }

ensurePanel();
