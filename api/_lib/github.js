const GITHUB_API = "https://api.github.com";

export function applyCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
}

export function repoConfig() {
  const repository = process.env.GITHUB_REPOSITORY || "DanielTNL/EURLex";
  const [owner, repo] = repository.split("/");
  const token = process.env.GITHUB_BACKEND_TOKEN || process.env.GITHUB_PAT || "";
  const ref = process.env.GITHUB_BACKEND_REF || "main";

  if (!owner || !repo) {
    throw new Error("GITHUB_REPOSITORY must be set like owner/repo.");
  }

  return { owner, repo, token, ref, repository };
}

function encodeRepoPath(filePath) {
  return String(filePath)
    .split("/")
    .map(encodeURIComponent)
    .join("/");
}

async function githubRequest(path, { method = "GET", body, token }) {
  const headers = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${GITHUB_API}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body)
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`GitHub API ${method} ${path} failed with ${response.status}: ${text}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export async function getRepoFile(filePath) {
  const { owner, repo, token, ref } = repoConfig();

  try {
    const payload = await githubRequest(
      `/repos/${owner}/${repo}/contents/${encodeRepoPath(filePath)}?ref=${encodeURIComponent(ref)}`,
      { token }
    );

    return {
      data: Buffer.from(payload.content, "base64").toString("utf8"),
      sha: payload.sha
    };
  } catch (error) {
    if (String(error.message || error).includes("404")) {
      return { data: null, sha: null };
    }
    throw error;
  }
}

export async function getRepoJSON(filePath, fallback) {
  try {
    const { data, sha } = await getRepoFile(filePath);
    if (data == null) {
      return { data: fallback, sha: null };
    }
    return {
      data: JSON.parse(data),
      sha
    };
  } catch (error) {
    if (String(error.message || error).includes("404")) {
      return { data: fallback, sha: null };
    }
    throw error;
  }
}

export async function putRepoJSON(filePath, data, message) {
  return putRepoContent(
    filePath,
    Buffer.from(JSON.stringify(data, null, 2) + "\n", "utf8").toString("base64"),
    message,
    { encoding: "base64" }
  );
}

export async function putRepoContent(filePath, content, message, options = {}) {
  const { owner, repo, token, ref } = repoConfig();
  if (!token) {
    throw new Error("GITHUB_BACKEND_TOKEN or GITHUB_PAT is required for repo writes.");
  }

  const current = await getRepoFile(filePath);
  const encodedContent = options.encoding === "base64"
    ? String(content || "")
    : Buffer.from(String(content || ""), "utf8").toString("base64");

  await githubRequest(`/repos/${owner}/${repo}/contents/${encodeRepoPath(filePath)}`, {
    method: "PUT",
    token,
    body: {
      message,
      content: encodedContent,
      sha: current.sha || undefined,
      branch: ref
    }
  });
}

export async function deleteRepoPath(filePath, message) {
  const { owner, repo, token, ref } = repoConfig();
  if (!token) {
    throw new Error("GITHUB_BACKEND_TOKEN or GITHUB_PAT is required for repo deletes.");
  }

  const current = await getRepoFile(filePath);
  if (!current.sha) {
    return { ok: true, deleted: false };
  }

  await githubRequest(`/repos/${owner}/${repo}/contents/${encodeRepoPath(filePath)}`, {
    method: "DELETE",
    token,
    body: {
      message,
      sha: current.sha,
      branch: ref
    }
  });

  return { ok: true, deleted: true };
}

export async function dispatchWorkflow(workflowFile, inputs = {}) {
  const { owner, repo, token, ref } = repoConfig();
  if (!token) {
    throw new Error("GITHUB_BACKEND_TOKEN or GITHUB_PAT is required for workflow dispatch.");
  }

  await githubRequest(`/repos/${owner}/${repo}/actions/workflows/${encodeURIComponent(workflowFile)}/dispatches`, {
    method: "POST",
    token,
    body: {
      ref,
      inputs
    }
  });

  return { ok: true, workflow: workflowFile, ref };
}
