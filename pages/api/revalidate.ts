import type { NextApiRequest, NextApiResponse } from 'next';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.query.secret !== process.env.REVALIDATE_SECRET) {
    return res.status(401).json({ message: 'Invalid token' });
  }
  const { paths = ["/"] } = (req.body || {}) as { paths?: string[] };
  try {
    for (const p of paths) await res.revalidate(p);
    return res.json({ revalidated: true, paths });
  } catch (e:any) {
    return res.status(500).json({ revalidated: false, error: e?.message });
  }
}
