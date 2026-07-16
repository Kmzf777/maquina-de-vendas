import { NextResponse, type NextRequest } from "next/server";

const FASTAPI_URL =
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000";

const UPSTREAM = `${FASTAPI_URL}/api/cadence/mirror-visibility`;

/** Proxy do toggle de visibilidade do espelho do motor (Redis via FastAPI).
 *  Fail-safe: erro no upstream degrada para OCULTO — nunca expõe por falha. */
export async function GET() {
  try {
    const upstream = await fetch(UPSTREAM, { cache: "no-store" });
    if (!upstream.ok) return NextResponse.json({ visible: false });
    return NextResponse.json(await upstream.json());
  } catch {
    return NextResponse.json({ visible: false });
  }
}

export async function POST(req: NextRequest) {
  try {
    const upstream = await fetch(UPSTREAM, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await req.text(),
    });
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
