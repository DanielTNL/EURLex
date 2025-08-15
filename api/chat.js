// api/chat.js
const DATA_BASE_DEFAULT = "https://danieltnl.github.io/EURLex/data";
const OPENAI_URL = "https://api.openai.com/v1/chat/completions";

function stripHtml(html){
  return String(html||'').replace(/<script[\s\S]*?<\/script>/gi,'')
                         .replace(/<style[\s\S]*?<\/style>/gi,'')
                         .replace(/<[^>]+>/g,' ')
                         .replace(/\s+/g,' ').trim();
}
async function fetchText(url){
  try{ const r = await fetch(url,{headers:{'user-agent':'eurlex-bot/1.0'}}); return stripHtml(await r.text()).slice(0,8000); }
  catch{ return ''; }
}

export default async function handler(req,res){
  res.setHeader('Access-Control-Allow-Origin','*');
  res.setHeader('Access-Control-Allow-Headers','Content-Type, Authorization');
  if(req.method==='OPTIONS') return res.status(204).end();
  if(req.method!=='POST') return res.status(405).json({error:'POST only'});

  try{
    const body = req.body || {};
    const { messages = [], top_k = 8, filters = {}, remote = false, attachments = [] } = body;

    const DATA_BASE = process.env.DATA_BASE || DATA_BASE_DEFAULT;
    const [posts, reports] = await Promise.all([
      fetch(`${DATA_BASE}/posts.json`,{cache:'no-store'}).then(r=>r.json()).catch(()=>[]),
      fetch(`${DATA_BASE}/reports.json`,{cache:'no-store'}).then(r=>r.json()).catch(()=>[])
    ]);

    const items = [
      ...posts.map(p=>({...p, kind:'post'})),
      ...reports.map(r=>({...r, kind:'report', url:r.url_html}))
    ];

    const lastUser = messages[messages.length-1]?.content || '';
    const qTokens = lastUser.toLowerCase().split(/\s+/).filter(Boolean);
    const within = (iso) => {
      const days = Number(filters.date_from_days||0);
      if(!days || !iso) return true;
      return new Date(iso).getTime() >= Date.now() - days*86400000;
    };

    const good = (it)=>{
      if((filters.sources||[]).length && !(filters.sources||[]).includes(it.source||'Other')) return false;
      const bag = new Set([...(it.tags||[]), ...(it.categories||[])]);
      for(const c of (filters.categories||[])) if(!bag.has(c)) return false;
      for(const t of (filters.tags||[])) if(!bag.has(t)) return false;
      return within(it.added||it.date);
    };

    const score = (it)=>{
      if(!good(it)) return -1;
      const hay = ((it.title||'')+' '+(it.summary||it.abstract||'')+' '+(it.tags||[]).join(' ')+' '+(it.source||'')).toLowerCase();
      let s = 0; for(const t of qTokens) if(hay.includes(t)) s++;
      const when = new Date(it.added||it.date||0);
      if(!isNaN(when)) { const days=(Date.now()-when.getTime())/86400000; s += Math.max(0,3-Math.min(3,Math.floor(days/7))); }
      return s;
    };

    const ranked = items.map(it=>({it,s:score(it)})).filter(x=>x.s>=0).sort((a,b)=>b.s-a.s).slice(0, Math.max(1, Number(top_k)));
    const top = ranked.map(x=>x.it);

    let fetched = [];
    if(remote){
      fetched = await Promise.all(top.map(async (r,i)=>({ i, url:r.url, text:r.url ? await fetchText(r.url) : '' })));
    }

    // Build context (docs + attachments)
    const blocks = top.map((r,i)=>{
      const date = (r.added||r.date||'').slice(0,10);
      const sum = (r.summary || r.abstract || '').replace(/\s+/g,' ').slice(0,900);
      const ext = (remote && (fetched[i]?.text)) ? `\n[REMOTE]\n${fetched[i].text.slice(0,1500)}\n` : '';
      return `[${i+1}] ${r.title} — ${r.source||r.kind} — ${date}\n${sum}\nURL: ${r.url}\n${ext}`;
    }).join('\n\n');

    const attBlocks = (attachments||[]).slice(0,4).map((a,i)=>`[A${i+1}] ${a.name}\n${String(a.text||'').slice(0,2000)}`).join('\n\n');

    const apiKey = process.env.OPENAI_API_KEY;
    if(!apiKey){ return res.json({ answer:null, results:top }); }

    const payload = {
      model: 'gpt-4o-mini',
      temperature: 0.2,
      messages: [
        { role:'system', content:'You are an expert EU policy analyst. Cite sources like [1] or [A1]. Keep answers concise.' },
        ...messages.filter(m=>m.role!=='system'),
        { role:'user', content: `Question: ${lastUser}\n\nRelevant documents:\n${blocks}\n\nAttachments (if any):\n${attBlocks}\n\nAnswer with citations.` }
      ]
    };

    const openaiResp = await fetch(OPENAI_URL,{ method:'POST', headers:{'Authorization':`Bearer ${apiKey}`,'Content-Type':'application/json'}, body:JSON.stringify(payload) }).then(r=>r.json());
    const answer = openaiResp?.choices?.[0]?.message?.content || null;

    res.json({ answer, results: top });
  }catch(err){
    console.error(err);
    res.status(500).json({ error: err?.message || String(err) });
  }
}
