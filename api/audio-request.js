import { applyCors, dispatchWorkflow } from "./_lib/github.js";

export default async function handler(req, res) {
  applyCors(res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });

  try {
    const promptHint = String(req.body?.prompt_hint || "").trim();
    const endDate = String(req.body?.end_date || "").trim();

    await dispatchWorkflow("weekly_audio_request.yml", {
      prompt_hint: promptHint,
      end_date: endDate
    });

    return res.status(200).json({
      ok: true,
      workflow: "weekly_audio_request.yml",
      message: "The weekly voice overview has been queued on GitHub. It will appear in the Voice tab after the workflow finishes and the published audio feed refreshes."
    });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ error: error?.message || String(error) });
  }
}
