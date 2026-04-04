import crypto from "node:crypto";
import { deleteRepoPath, getRepoJSON, putRepoContent, putRepoJSON, repoConfig } from "./github.js";

const LIBRARY_STATE_PATH = "state/library_documents.json";
const LIBRARY_UPLOAD_PREFIX = "library/uploads";
const MAX_UPLOAD_BYTES = Number(process.env.MAX_UPLOAD_BYTES || 4_000_000);
const MAX_TEXT_CHARS = Number(process.env.MAX_LIBRARY_TEXT_CHARS || 20_000);
const ALLOWED_UPLOAD_KINDS = new Set(["pdf", "docx", "md", "txt"]);

function isoNow() {
  return new Date().toISOString();
}

function cleanText(text, limit = MAX_TEXT_CHARS) {
  const compact = String(text || "").replace(/\s+/g, " ").trim();
  if (!compact) return "";
  if (compact.length <= limit) return compact;
  return compact.slice(0, limit - 1).trimEnd() + "…";
}

function stripHtml(html) {
  return cleanText(
    String(html || "")
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/g, " ")
  );
}

function deriveTitleFromURL(url) {
  try {
    const parsed = new URL(url);
    const leaf = parsed.pathname.split("/").filter(Boolean).pop();
    return leaf ? decodeURIComponent(leaf).replace(/[-_]+/g, " ") : parsed.hostname;
  } catch {
    return url;
  }
}

function slugify(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "document";
}

function normalizeTags(tags) {
  if (!Array.isArray(tags)) return [];
  return tags.map((tag) => String(tag || "").trim()).filter(Boolean);
}

function normalizeHTTPURL(raw) {
  try {
    const url = new URL(String(raw || "").trim());
    if (!["http:", "https:"].includes(url.protocol)) return "";
    return url.toString();
  } catch {
    return "";
  }
}

function inferKind({ filename = "", mimeType = "", url = "" }) {
  const lowerName = String(filename).toLowerCase();
  const lowerMime = String(mimeType).toLowerCase();
  const lowerURL = String(url).toLowerCase();

  if (lowerName.endsWith(".pdf") || lowerMime.includes("pdf")) return "pdf";
  if (lowerName.endsWith(".docx") || lowerMime.includes("word")) return "docx";
  if (lowerName.endsWith(".md") || lowerName.endsWith(".markdown")) return "md";
  if (lowerName.endsWith(".txt") || lowerMime.startsWith("text/plain")) return "txt";
  if (lowerURL) return "url";
  return "txt";
}

function decodeBase64Payload(raw) {
  const value = String(raw || "");
  const cleaned = value.includes(",") ? value.split(",").pop() : value;
  return Buffer.from(cleaned || "", "base64");
}

function buildRawURL(repo, ref, repoPath) {
  return `https://raw.githubusercontent.com/${repo}/${ref}/${repoPath}`;
}

function titleCaseStem(value) {
  return String(value || "")
    .replace(/\.[^.]+$/, "")
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeRegistry(data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  return {
    updated_at: String(data?.updated_at || ""),
    items: items.map((item) => ({
      id: String(item.id || ""),
      title: String(item.title || item.name || "Untitled document").trim(),
      source_type: String(item.source_type || (item.source_url ? "url" : "upload")),
      kind: String(item.kind || "txt"),
      repo_path: item.repo_path ? String(item.repo_path) : null,
      source_url: item.source_url ? String(item.source_url) : null,
      raw_url: item.raw_url ? String(item.raw_url) : null,
      mime_type: item.mime_type ? String(item.mime_type) : null,
      size_bytes: Number(item.size_bytes || 0),
      tags: normalizeTags(item.tags),
      status: String(item.status || "ready"),
      summary: cleanText(item.summary || item.excerpt || "", 1000),
      extracted_text: cleanText(item.extracted_text || item.text || "", MAX_TEXT_CHARS),
      added_at: String(item.added_at || ""),
      updated_at: String(item.updated_at || ""),
      error: item.error ? String(item.error) : null
    })).filter((item) => item.id)
  };
}

export async function getLibraryRegistry() {
  const payload = await getRepoJSON(LIBRARY_STATE_PATH, { updated_at: "", items: [] });
  return normalizeRegistry(payload.data);
}

async function saveLibraryRegistry(payload, message) {
  const normalized = normalizeRegistry(payload);
  normalized.updated_at = isoNow();
  await putRepoJSON(LIBRARY_STATE_PATH, normalized, message);
  return normalized;
}

async function fetchURLPreview(url) {
  try {
    const response = await fetch(url, {
      headers: { "user-agent": "eurlex-backend/1.0" }
    });
    const html = await response.text();
    const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
    const title = cleanText(titleMatch?.[1] || deriveTitleFromURL(url), 180);
    return {
      title,
      text: stripHtml(html)
    };
  } catch {
    return {
      title: cleanText(deriveTitleFromURL(url), 180),
      text: ""
    };
  }
}

function immediateUploadPreview(kind, buffer) {
  if (kind === "txt" || kind === "md") {
    return cleanText(buffer.toString("utf8"));
  }
  return "";
}

export async function upsertLibraryDocument(input) {
  const current = await getLibraryRegistry();
  const { repository, ref } = repoConfig();

  const title = cleanText(input.title || input.name || "", 180);
  const tags = normalizeTags(input.tags);
  const sourceURL = normalizeHTTPURL(input.url);
  const filename = String(input.filename || "").trim();
  const mimeType = String(input.mime_type || input.mimeType || "").trim();
  const textInput = cleanText(input.text || "", MAX_TEXT_CHARS);

  if (input.url && !sourceURL) {
    throw new Error("Provide a valid http or https URL.");
  }

  if (!sourceURL && !input.content_base64 && !textInput) {
    throw new Error("Provide a URL, uploaded content, or note text.");
  }

  let entry = null;

  if (sourceURL) {
    const existing = current.items.find((item) => item.source_url === sourceURL);
    const preview = await fetchURLPreview(sourceURL);
    entry = {
      id: existing?.id || crypto.createHash("sha1").update(sourceURL).digest("hex").slice(0, 12),
      title: title || preview.title || deriveTitleFromURL(sourceURL),
      source_type: "url",
      kind: "url",
      repo_path: null,
      source_url: sourceURL,
      raw_url: sourceURL,
      mime_type: "text/html",
      size_bytes: 0,
      tags,
      status: preview.text ? "ready" : "pending_processing",
      summary: cleanText(preview.text || sourceURL, 900),
      extracted_text: preview.text,
      added_at: existing?.added_at || isoNow(),
      updated_at: isoNow(),
      error: null
    };
  } else {
    const kind = inferKind({ filename, mimeType });
    if (!ALLOWED_UPLOAD_KINDS.has(kind)) {
      throw new Error("Only TXT, Markdown, PDF, and DOCX uploads are supported in the GitHub-backed library.");
    }
    const baseName = filename || `${slugify(title || "document")}.${kind}`;
    const buffer = input.content_base64
      ? decodeBase64Payload(input.content_base64)
      : Buffer.from(textInput, "utf8");

    if (buffer.length === 0) {
      throw new Error("Uploaded content was empty.");
    }
    if (buffer.length > MAX_UPLOAD_BYTES) {
      throw new Error(`Upload exceeds the ${Math.round(MAX_UPLOAD_BYTES / 1_000_000)} MB limit for the GitHub-backed library.`);
    }

    const id = crypto.createHash("sha1").update(`${baseName}:${buffer.length}:${Date.now()}`).digest("hex").slice(0, 12);
    const ext = kind === "md" ? "md" : kind === "txt" ? "txt" : kind;
    const repoPath = `${LIBRARY_UPLOAD_PREFIX}/${slugify(title || baseName)}-${id}.${ext}`;
    await putRepoContent(
      repoPath,
      buffer.toString("base64"),
      `Upload library document (${title || baseName})`,
      { encoding: "base64" }
    );

    const extracted = textInput || immediateUploadPreview(kind, buffer);
    entry = {
      id,
      title: title || titleCaseStem(baseName),
      source_type: "upload",
      kind,
      repo_path: repoPath,
      source_url: null,
      raw_url: buildRawURL(repository, ref, repoPath),
      mime_type: mimeType || null,
      size_bytes: buffer.length,
      tags,
      status: extracted ? "ready" : "pending_processing",
      summary: cleanText(extracted || `Uploaded ${kind.toUpperCase()} document. Processing will complete on GitHub shortly.`, 900),
      extracted_text: extracted,
      added_at: isoNow(),
      updated_at: isoNow(),
      error: null
    };
  }

  const nextItems = current.items
    .filter((item) => item.id !== entry.id && item.source_url !== entry.source_url)
    .concat(entry)
    .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));

  const payload = await saveLibraryRegistry(
    { updated_at: isoNow(), items: nextItems },
    `Update library registry (${entry.title})`
  );

  return payload;
}

export async function removeLibraryDocument(target) {
  const current = await getLibraryRegistry();
  const identifier = String(target || "").trim();
  if (!identifier) {
    throw new Error("An id is required to delete a document.");
  }

  const match = current.items.find((item) => item.id === identifier || item.repo_path === identifier || item.source_url === identifier);
  if (!match) {
    return current;
  }

  if (match.repo_path) {
    await deleteRepoPath(match.repo_path, `Remove library document (${match.title})`);
  }

  const payload = await saveLibraryRegistry(
    {
      updated_at: isoNow(),
      items: current.items.filter((item) => item.id !== match.id)
    },
    `Remove library document (${match.title})`
  );

  return payload;
}

export { LIBRARY_STATE_PATH, MAX_UPLOAD_BYTES };
