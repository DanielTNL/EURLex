// api/export_doc.js
import { google } from 'googleapis';

export default async function handler(req, res){
  res.setHeader('Access-Control-Allow-Origin','*');
  res.setHeader('Access-Control-Allow-Headers','Content-Type, Authorization');
  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'POST') return res.status(405).json({ error:'POST only' });

  try{
    const { title='Ask AI note', answer='', sources=[] } = req.body || {};
    const svc = JSON.parse(process.env.GOOGLE_SERVICE_ACCOUNT_JSON || '{}');

    const auth = new google.auth.JWT({
      email: svc.client_email,
      key: svc.private_key,
      scopes: ['https://www.googleapis.com/auth/drive','https://www.googleapis.com/auth/documents']
    });

    const docs  = google.docs({ version:'v1', auth });
    const drive = google.drive({ version:'v3', auth });

    const doc = await docs.documents.create({ requestBody: { title } });
    const docId = doc.data.documentId;

    const content =
`# ${title}

${answer}

## Sources
${sources.map(s=>`[${s.n}] ${s.title} — ${s.source||''} — ${s.date||''}
${s.url}`).join('\n\n')}
`;

    await docs.documents.batchUpdate({
      documentId: docId,
      requestBody: { requests: [{ insertText: { location: { index: 1 }, text: content } }] }
    });

    const folderId = process.env.GOOGLE_DOCS_FOLDER_ID;
    if (folderId){
      await drive.files.update({ fileId: docId, addParents: folderId, fields: 'id, parents' });
    }
    const share = process.env.GOOGLE_DOCS_SHARE_WITH;
    if (share){
      await drive.permissions.create({
        fileId: docId,
        requestBody: { type: 'user', role: 'writer', emailAddress: share },
        sendNotificationEmail: false
      });
    }

    const url = `https://docs.google.com/document/d/${docId}/edit`;
    res.json({ url, id: docId });
  }catch(e){
    console.error(e);
    res.status(500).json({ error: e?.message || String(e) });
  }
}
