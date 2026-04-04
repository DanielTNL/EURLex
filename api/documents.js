import { applyCors } from "./_lib/github.js";
import { getLibraryRegistry, MAX_UPLOAD_BYTES, removeLibraryDocument, upsertLibraryDocument } from "./_lib/library.js";

export default async function handler(req, res) {
  applyCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();

  try {
    if (req.method === "GET") {
      const payload = await getLibraryRegistry();
      return res.status(200).json({
        ...payload,
        max_upload_bytes: MAX_UPLOAD_BYTES
      });
    }

    if (req.method === "POST") {
      const payload = await upsertLibraryDocument(req.body || {});
      return res.status(200).json({
        ...payload,
        queued_processing: true,
        message: "The document intake has been saved to GitHub. Text-like items are available immediately; PDFs and DOCX files finish processing through GitHub Actions."
      });
    }

    if (req.method === "DELETE") {
      const target = req.body?.id || req.body?.repo_path || req.body?.source_url;
      const payload = await removeLibraryDocument(target);
      return res.status(200).json({
        ...payload,
        queued_processing: true
      });
    }

    return res.status(405).json({ error: "Method not allowed." });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ error: error?.message || String(error) });
  }
}
