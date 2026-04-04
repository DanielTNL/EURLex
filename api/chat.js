import { getRepoJSON } from "./_lib/github.js";

const DATA_BASE_DEFAULT = "https://danieltnl.github.io/EURLex/data";
const OPENAI_URL = "https://api.openai.com/v1/chat/completions";
const LIBRARY_STATE_PATH = "state/library_documents.json";

function cleanText(text, limit = 8_000) {
  const compact = String(text || "")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (!compact) return "";
  if (compact.length <= limit) return compact;
  return compact.slice(0, limit - 1).trimEnd() + "…";
}

async function fetchJSON(url, fallback) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) return fallback;
    return await response.json();
  } catch {
    return fallback;
  }
}

async function fetchText(url) {
  try {
    const response = await fetch(url, { headers: { "user-agent": "eurlex-bot/1.0" } });
    return cleanText(await response.text(), 8_000);
  } catch {
    return "";
  }
}

function within(dateLike, filters) {
  const days = Number(filters?.date_from_days || 0);
  if (!days || !dateLike) return true;
  const value = new Date(dateLike).getTime();
  if (Number.isNaN(value)) return true;
  return value >= Date.now() - days * 86_400_000;
}

function itemBag(item) {
  return cleanText([
    item.title,
    item.original_title,
    item.summary,
    item.text,
    item.reference,
    item.source,
    ...(item.tags || []),
    ...(item.categories || [])
  ].join(" "), 12_000).toLowerCase();
}

function good(item, filters) {
  if ((filters?.sources || []).length && !filters.sources.includes(item.source || "Other")) {
    return false;
  }

  const bag = new Set([...(item.tags || []), ...(item.categories || [])]);
  for (const value of filters?.categories || []) {
    if (!bag.has(value)) return false;
  }
  for (const value of filters?.tags || []) {
    if (!bag.has(value)) return false;
  }

  return within(item.date, filters);
}

function scoreItem(item, tokens, filters) {
  if (!good(item, filters)) return -1;
  const haystack = itemBag(item);
  let score = 0;
  for (const token of tokens) {
    if (haystack.includes(token)) score += 1;
  }

  const when = new Date(item.date || 0);
  if (!Number.isNaN(when.getTime())) {
    const days = (Date.now() - when.getTime()) / 86_400_000;
    score += Math.max(0, 3 - Math.min(3, Math.floor(days / 7)));
  }

  if (item.kind === "briefing" || item.kind === "sunday_edition") score += 1;
  if (item.kind === "library") score += 1;

  return score;
}

function mapPost(post) {
  return {
    id: post.id || post.url,
    kind: "post",
    title: post.display_title || post.title || "Untitled post",
    original_title: post.original_title || "",
    summary: post.display_summary || post.summary || "",
    text: "",
    url: post.url || "",
    source: post.source || "Source",
    date: post.added || "",
    tags: post.tags || [],
    categories: post.categories || [],
    reference: post.reference || ""
  };
}

function mapReport(report) {
  return {
    id: report.id || report.url_html,
    kind: "report",
    title: report.display_title || report.title || "Untitled report",
    original_title: report.original_title || "",
    summary: report.abstract || "",
    text: "",
    url: report.url_html || "",
    source: "EURLex reports",
    date: report.date || "",
    tags: report.tags || [],
    categories: report.tags || [],
    reference: ""
  };
}

function mapBriefing(item) {
  return {
    id: item.date || item.title,
    kind: "briefing",
    title: item.headline || item.title || "Daily briefing",
    original_title: item.title || "",
    summary: item.summary || item.intro || "",
    text: cleanText([
      item.intro || "",
      item.summary || "",
      ...(item.key_points || []),
      ...((item.sections || []).flatMap((section) => [section.title || "", section.body || ""]))
    ].join(" "), 12_000),
    url: item.report?.url || "",
    source: "Daily briefing",
    date: item.date || "",
    tags: ["briefing", ...(item.categories || [])],
    categories: item.categories || [],
    reference: ""
  };
}

function mapSundayEdition(item) {
  return {
    id: item.week_end || item.title,
    kind: "sunday_edition",
    title: item.headline || item.title || "Sunday Edition",
    original_title: item.title || "",
    summary: item.summary || item.intro || "",
    text: cleanText([
      item.intro || "",
      item.summary || "",
      ...(item.key_points || []),
      ...((item.sections || []).flatMap((section) => [section.title || "", section.body || ""]))
    ].join(" "), 14_000),
    url: item.report?.url || "",
    source: "Sunday Edition",
    date: item.week_end || item.edition_date || "",
    tags: ["weekly", ...(item.categories || [])],
    categories: item.categories || [],
    reference: ""
  };
}

function mapLibrary(item) {
  return {
    id: item.id || item.path || item.raw_url,
    kind: "library",
    title: item.title || "Library document",
    original_title: "",
    summary: item.summary || "",
    text: item.extracted_text || "",
    url: item.raw_url || item.source_url || "",
    source: item.source_type === "url" ? "Library URL" : "Library upload",
    date: item.updated_at || item.added_at || "",
    tags: item.tags || [],
    categories: item.tags || [],
    reference: ""
  };
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });

  try {
    const body = req.body || {};
    const { messages = [], top_k = 8, filters = {}, remote = false, attachments = [] } = body;
    const model = process.env.OPENAI_MODEL_CHAT || process.env.OPENAI_MODEL || "gpt-4o-mini";
    const dataBase = process.env.DATA_BASE || DATA_BASE_DEFAULT;

    const [posts, reports, briefings, sundayEditions, publishedLibrary, registry] = await Promise.all([
      fetchJSON(`${dataBase}/posts.json`, []),
      fetchJSON(`${dataBase}/reports.json`, []),
      fetchJSON(`${dataBase}/briefings.json`, { items: [] }),
      fetchJSON(`${dataBase}/sunday-editions.json`, { items: [] }),
      fetchJSON(`${dataBase}/library.json`, { items: [] }),
      getRepoJSON(LIBRARY_STATE_PATH, { items: [] }).catch(() => ({ data: { items: [] } }))
    ]);

    const items = [
      ...(posts || []).map(mapPost),
      ...(reports || []).map(mapReport),
      ...((briefings?.items || []).map(mapBriefing)),
      ...((sundayEditions?.items || []).map(mapSundayEdition)),
      ...((publishedLibrary?.items || []).map(mapLibrary)),
      ...(((registry?.data?.items) || []).map(mapLibrary))
    ];

    const deduped = [];
    const seen = new Set();
    for (const item of items) {
      const key = `${item.kind}:${item.id || item.url || item.title}`;
      if (seen.has(key)) continue;
      seen.add(key);
      deduped.push(item);
    }

    const lastUser = messages[messages.length - 1]?.content || "";
    const tokens = lastUser.toLowerCase().split(/\s+/).filter(Boolean);
    const ranked = deduped
      .map((item) => ({ item, score: scoreItem(item, tokens, filters) }))
      .filter((entry) => entry.score >= 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, Math.max(1, Number(top_k)));

    const top = ranked.map((entry) => entry.item);

    const fetched = remote
      ? await Promise.all(top.map(async (item) => {
          const shouldFetch =
            item.url &&
            !item.url.endsWith(".pdf") &&
            !item.url.endsWith(".docx") &&
            !item.url.includes("raw.githubusercontent.com");
          return shouldFetch ? fetchText(item.url) : "";
        }))
      : [];

    const blocks = top.map((item, index) => {
      const date = String(item.date || "").slice(0, 10);
      const remoteText = remote && fetched[index] ? `\n[REMOTE]\n${fetched[index].slice(0, 1800)}` : "";
      return [
        `[${index + 1}] ${item.title} — ${item.source} — ${date}`,
        item.reference ? `Reference: ${item.reference}` : "",
        item.original_title && item.original_title !== item.title ? `Original title: ${item.original_title}` : "",
        cleanText(item.summary || "", 1000),
        item.text ? `Full text excerpt: ${cleanText(item.text, 2500)}` : "",
        item.url ? `URL: ${item.url}` : "",
        remoteText
      ].filter(Boolean).join("\n");
    }).join("\n\n");

    const attachmentBlocks = (attachments || []).slice(0, 6).map((attachment, index) =>
      `[A${index + 1}] ${attachment.name}\n${cleanText(attachment.text || "", 3_000)}`
    ).join("\n\n");

    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) {
      return res.status(200).json({ answer: null, results: top });
    }

    const payload = {
      model,
      temperature: 0.2,
      messages: [
        {
          role: "system",
          content: "You are an expert EU policy analyst. Answer clearly in polished UK English. Prefer concise sections. Cite sources like [1] or [A1]. Distinguish between the platform corpus and any remote live fetches."
        },
        ...messages.filter((message) => message.role !== "system"),
        {
          role: "user",
          content: [
            `Question: ${lastUser}`,
            "",
            "Relevant corpus documents:",
            blocks || "(none)",
            "",
            "Attachments:",
            attachmentBlocks || "(none)",
            "",
            remote
              ? "Web mode is ON. Use the remote snippets only as supplemental context and say when something comes from the live fetch."
              : "Web mode is OFF. Answer only from the platform corpus and attachments."
          ].join("\n")
        }
      ]
    };

    const openaiResponse = await fetch(OPENAI_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    }).then((response) => response.json());

    const answer = openaiResponse?.choices?.[0]?.message?.content || null;
    return res.status(200).json({ answer, results: top });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ error: error?.message || String(error) });
  }
}
