import { applyCors, repoConfig } from "./_lib/github.js";
import { MAX_UPLOAD_BYTES } from "./_lib/library.js";

export default async function handler(req, res) {
  applyCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();

  const backendConfigured = Boolean(process.env.OPENAI_API_KEY);
  const githubWritesConfigured = Boolean(process.env.GITHUB_BACKEND_TOKEN || process.env.GITHUB_PAT);
  const repository = repoConfig().repository;

  return res.status(200).json({
    ok: true,
    backendConfigured,
    githubWritesConfigured,
    repository,
    dataBase: process.env.DATA_BASE || "https://danieltnl.github.io/EURLex/data",
    maxUploadBytes: MAX_UPLOAD_BYTES,
    documentsEnabled: true
  });
}
