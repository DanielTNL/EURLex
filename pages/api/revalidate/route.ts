import { NextRequest, NextResponse } from 'next/server';

export async function POST(req: NextRequest) {
  const url = new URL(req.url);
  if (url.searchParams.get('secret') !== process.env.REVALIDATE_SECRET) {
    return NextResponse.json({ message: 'Invalid token' }, { status: 401 });
  }
  const { paths = ["/"] } = await req.json().catch(() => ({}));
  try {
    // @ts-expect-error revalidate is available in route handlers
    for (const p of paths) await (global as any).res?.revalidate?.(p) || (await import('next/cache')).revalidatePath(p);
    return NextResponse.json({ revalidated: true, paths });
  } catch (e:any) {
    return NextResponse.json({ revalidated: false, error: e?.message }, { status: 500 });
  }
}
