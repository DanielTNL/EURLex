import crypto from "node:crypto";
import { applyCors, getRepoJSON, putRepoJSON } from "./_lib/github.js";

const SOURCES_PATH = "state/custom_feeds.json";

function normalizeURL(raw) {
  try {
    return new URL(String(raw || "").trim()).toString();
  } catch {
    return "";
  }
}

function normalizePayload(data) {
  const feeds = Array.isArray(data?.feeds) ? data.feeds : [];
  return {
    updated_at: data?.updated_at || "",
    feeds: feeds.map((feed) => ({
      id: String(feed.id || crypto.createHash("sha1").update(String(feed.url || "")).digest("hex").slice(0, 12)),
      name: String(feed.name || feed.url || "Custom source").trim(),
      url: normalizeURL(feed.url),
      tags: Array.isArray(feed.tags) ? feed.tags.map((tag) => String(tag).trim()).filter(Boolean) : [],
      added_at: String(feed.added_at || "")
    })).filter((feed) => feed.url)
  };
}

export default async function handler(req, res) {
  applyCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();

  try {
    if (req.method === "GET") {
      const { data } = await getRepoJSON(SOURCES_PATH, { updated_at: "", feeds: [] });
      return res.status(200).json(normalizePayload(data));
    }

    if (req.method === "POST") {
      const url = normalizeURL(req.body?.url);
      const name = String(req.body?.name || "").trim();
      const tags = Array.isArray(req.body?.tags) ? req.body.tags : [];

      if (!url) {
        return res.status(400).json({ error: "A valid RSS or Atom feed URL is required." });
      }

      const current = normalizePayload((await getRepoJSON(SOURCES_PATH, { updated_at: "", feeds: [] })).data);
      const existing = current.feeds.find((feed) => feed.url === url);
      const nextFeed = {
        id: existing?.id || crypto.createHash("sha1").update(url).digest("hex").slice(0, 12),
        name: name || existing?.name || url,
        url,
        tags: tags.map((tag) => String(tag).trim()).filter(Boolean),
        added_at: existing?.added_at || new Date().toISOString()
      };

      const nextFeeds = current.feeds
        .filter((feed) => feed.url !== url)
        .concat(nextFeed)
        .sort((a, b) => a.name.localeCompare(b.name));

      const payload = {
        updated_at: new Date().toISOString(),
        feeds: nextFeeds
      };

      await putRepoJSON(SOURCES_PATH, payload, `Update custom feeds (${nextFeed.name})`);
      return res.status(200).json(payload);
    }

    if (req.method === "DELETE") {
      const target = String(req.body?.id || req.body?.url || "").trim();
      if (!target) {
        return res.status(400).json({ error: "An id or url is required to remove a source." });
      }

      const current = normalizePayload((await getRepoJSON(SOURCES_PATH, { updated_at: "", feeds: [] })).data);
      const nextFeeds = current.feeds.filter((feed) => feed.id !== target && feed.url !== target);
      const payload = {
        updated_at: new Date().toISOString(),
        feeds: nextFeeds
      };

      await putRepoJSON(SOURCES_PATH, payload, `Remove custom feed (${target})`);
      return res.status(200).json(payload);
    }

    return res.status(405).json({ error: "Method not allowed." });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ error: error?.message || String(error) });
  }
}
