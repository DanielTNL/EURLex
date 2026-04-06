import crypto from "node:crypto";
import { applyCors, getRepoJSON, putRepoJSON } from "./_lib/github.js";

const CUSTOM_SOURCES_PATH = "state/custom_feeds.json";
const SOURCE_OVERRIDES_PATH = "state/source_overrides.json";
const PUBLISHED_SOURCES_PATH = "docs/data/sources.json";

function stableId(sourceId, url) {
  return crypto
    .createHash("sha1")
    .update(`${String(sourceId || "").trim()}|${String(url || "").trim()}`)
    .digest("hex")
    .slice(0, 12);
}

function normalizeURL(raw) {
  try {
    return new URL(String(raw || "").trim()).toString();
  } catch {
    return "";
  }
}

function cleanTags(tags) {
  return Array.isArray(tags)
    ? tags.map((tag) => String(tag).trim()).filter(Boolean)
    : [];
}

function normalizeManagedSource(item, fallback = {}) {
  const url = normalizeURL(item?.url || fallback.url);
  const sourceId = String(item?.source_id || item?.sourceId || fallback.source_id || fallback.sourceId || item?.name || fallback.name || url).trim();
  const id = String(item?.id || fallback.id || stableId(sourceId, url));
  return {
    id,
    source_id: sourceId,
    name: String(item?.name || fallback.name || url || "Source").trim(),
    url,
    tags: cleanTags(item?.tags ?? fallback.tags),
    kind: String(item?.kind || item?.type || fallback.kind || "rss").trim() || "rss",
    origin: String(item?.origin || fallback.origin || "custom").trim() || "custom",
    enabled: item?.enabled ?? fallback.enabled ?? true,
    added_at: String(item?.added_at || fallback.added_at || ""),
    updated_at: String(item?.updated_at || fallback.updated_at || "")
  };
}

function normalizeCustomPayload(data) {
  const feeds = Array.isArray(data?.feeds) ? data.feeds : [];
  return {
    updated_at: data?.updated_at || "",
    feeds: feeds
      .map((feed) => normalizeManagedSource(feed, { origin: "custom", kind: "rss", enabled: true }))
      .filter((feed) => feed.url)
  };
}

function normalizeOverridesPayload(data) {
  const entries = Array.isArray(data?.entries) ? data.entries : [];
  return {
    updated_at: data?.updated_at || "",
    entries: entries
      .map((entry) => normalizeManagedSource(entry, { origin: "built_in", kind: "rss", enabled: true }))
      .filter((entry) => entry.id)
  };
}

function normalizePublishedSource(item) {
  const normalized = normalizeManagedSource(item, {
    origin: item?.origin || "built_in",
    kind: item?.kind || "rss",
    enabled: item?.enabled ?? true
  });
  if (!normalized.url) return null;
  return normalized;
}

function publishedItems(data) {
  const items = Array.isArray(data?.items)
    ? data.items
    : Array.isArray(data?.sources)
      ? data.sources
      : [];
  return items.map(normalizePublishedSource).filter(Boolean);
}

function mergeSources(published, customPayload, overridesPayload) {
  const builtIns = new Map();
  for (const item of published.filter((entry) => entry.origin !== "custom")) {
    builtIns.set(item.id, item);
  }

  const customs = new Map();
  for (const item of published.filter((entry) => entry.origin === "custom")) {
    customs.set(item.id, item);
  }
  for (const item of customPayload.feeds) {
    customs.set(item.id, item);
  }

  for (const override of overridesPayload.entries) {
    const target = builtIns.get(override.id) || customs.get(override.id);
    const merged = normalizeManagedSource(
      {
        ...target,
        ...override,
        id: override.id || target?.id,
        source_id: override.source_id || target?.source_id,
        origin: target?.origin || override.origin || "built_in"
      },
      target || override
    );

    if (target?.origin === "custom" || override.origin === "custom") {
      customs.set(merged.id, merged);
    } else {
      builtIns.set(merged.id, merged);
    }
  }

  return [...builtIns.values(), ...customs.values()]
    .filter((item) => item.enabled !== false)
    .sort((a, b) => {
      if (a.origin !== b.origin) return a.origin.localeCompare(b.origin);
      return a.name.localeCompare(b.name);
    });
}

async function loadRegistry() {
  const [publishedRaw, customRaw, overridesRaw] = await Promise.all([
    getRepoJSON(PUBLISHED_SOURCES_PATH, { items: [] }),
    getRepoJSON(CUSTOM_SOURCES_PATH, { updated_at: "", feeds: [] }),
    getRepoJSON(SOURCE_OVERRIDES_PATH, { updated_at: "", entries: [] })
  ]);

  const published = publishedItems(publishedRaw.data);
  const customPayload = normalizeCustomPayload(customRaw.data);
  const overridesPayload = normalizeOverridesPayload(overridesRaw.data);
  const sources = mergeSources(published, customPayload, overridesPayload);

  return {
    updated_at: overridesPayload.updated_at || customPayload.updated_at || "",
    queued_processing: false,
    message: "",
    sources,
    feeds: sources,
    customPayload,
    overridesPayload
  };
}

async function saveCustomFeeds(payload, message) {
  await putRepoJSON(CUSTOM_SOURCES_PATH, payload, message);
}

async function saveOverrides(payload, message) {
  await putRepoJSON(SOURCE_OVERRIDES_PATH, payload, message);
}

function findByTarget(sources, target) {
  return sources.find((source) => source.id === target || source.url === target || source.source_id === target);
}

export default async function handler(req, res) {
  applyCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();

  try {
    if (req.method === "GET") {
      const registry = await loadRegistry();
      return res.status(200).json({
        updated_at: registry.updated_at,
        queued_processing: false,
        sources: registry.sources,
        feeds: registry.sources
      });
    }

    if (req.method === "POST") {
      const registry = await loadRegistry();
      const body = req.body || {};
      const url = normalizeURL(body.url);
      const targetId = String(body.id || "").trim();
      const name = String(body.name || "").trim();
      const tags = cleanTags(body.tags);

      if (!url) {
        return res.status(400).json({ error: "A valid RSS or Atom feed URL is required." });
      }

      const existing = targetId
        ? findByTarget(registry.sources, targetId)
        : registry.sources.find((source) => source.url === url);

      const isCustom = !existing || existing.origin === "custom" || body.origin === "custom";

      if (isCustom) {
        const currentCustom = normalizeCustomPayload(registry.customPayload);
        const nextFeed = normalizeManagedSource(
          {
            id: existing?.id || targetId || stableId(body.source_id || name || url, url),
            source_id: body.source_id || existing?.source_id || name || url,
            name: name || existing?.name || url,
            url,
            tags,
            kind: body.kind || existing?.kind || "rss",
            origin: "custom",
            enabled: true,
            added_at: existing?.added_at || new Date().toISOString()
          },
          { origin: "custom", kind: "rss", enabled: true }
        );

        const nextFeeds = currentCustom.feeds
          .filter((feed) => feed.id !== nextFeed.id && feed.url !== (existing?.url || nextFeed.url))
          .concat(nextFeed)
          .sort((a, b) => a.name.localeCompare(b.name));

        const payload = {
          updated_at: new Date().toISOString(),
          feeds: nextFeeds
        };

        await saveCustomFeeds(payload, `Update managed source (${nextFeed.name})`);
      } else {
        const currentOverrides = normalizeOverridesPayload(registry.overridesPayload);
        const nextOverride = normalizeManagedSource(
          {
            id: existing.id,
            source_id: existing.source_id,
            name: name || existing.name,
            url,
            tags,
            kind: body.kind || existing.kind,
            origin: existing.origin,
            enabled: body.enabled ?? true,
            added_at: existing.added_at,
            updated_at: new Date().toISOString()
          },
          existing
        );

        const nextEntries = currentOverrides.entries
          .filter((entry) => entry.id !== nextOverride.id)
          .concat(nextOverride)
          .sort((a, b) => a.name.localeCompare(b.name));

        await saveOverrides(
          {
            updated_at: new Date().toISOString(),
            entries: nextEntries
          },
          `Update source override (${nextOverride.name})`
        );
      }

      const nextRegistry = await loadRegistry();
      return res.status(200).json({
        updated_at: new Date().toISOString(),
        queued_processing: true,
        message: "The source registry has been updated in GitHub. The source-refresh workflow will pick up the change and fold new material into the published corpus.",
        sources: nextRegistry.sources,
        feeds: nextRegistry.sources
      });
    }

    if (req.method === "DELETE") {
      const registry = await loadRegistry();
      const target = String(req.body?.id || req.body?.url || "").trim();
      if (!target) {
        return res.status(400).json({ error: "An id or url is required to remove a source." });
      }

      const existing = findByTarget(registry.sources, target);
      if (!existing) {
        return res.status(200).json({
          updated_at: new Date().toISOString(),
          queued_processing: false,
          sources: registry.sources,
          feeds: registry.sources
        });
      }

      if (existing.origin === "custom") {
        const currentCustom = normalizeCustomPayload(registry.customPayload);
        const payload = {
          updated_at: new Date().toISOString(),
          feeds: currentCustom.feeds.filter((feed) => feed.id !== existing.id && feed.url !== existing.url)
        };
        await saveCustomFeeds(payload, `Remove managed source (${existing.name})`);
      } else {
        const currentOverrides = normalizeOverridesPayload(registry.overridesPayload);
        const tombstone = normalizeManagedSource(
          {
            ...existing,
            enabled: false,
            updated_at: new Date().toISOString()
          },
          existing
        );
        const payload = {
          updated_at: new Date().toISOString(),
          entries: currentOverrides.entries
            .filter((entry) => entry.id !== existing.id)
            .concat(tombstone)
            .sort((a, b) => a.name.localeCompare(b.name))
        };
        await saveOverrides(payload, `Disable managed source (${existing.name})`);
      }

      const nextRegistry = await loadRegistry();
      return res.status(200).json({
        updated_at: new Date().toISOString(),
        queued_processing: true,
        message: "The source registry has been updated in GitHub. The next refresh will reflect the change in discovery and published data.",
        sources: nextRegistry.sources,
        feeds: nextRegistry.sources
      });
    }

    return res.status(405).json({ error: "Method not allowed." });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ error: error?.message || String(error) });
  }
}
