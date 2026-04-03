import { applyCors, repoConfig } from "./_lib/github.js";

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
    repository
  });
}
