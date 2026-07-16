import { NextResponse } from "next/server";

const FASTAPI_URL =
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000";

/** Proxy da DEFINIÇÃO da cadência — fonte de verdade é o FastAPI
 *  (backend/app/follow_up/cadence.py via /api/cadence/definition). */
export async function GET() {
  try {
    const upstream = await fetch(`${FASTAPI_URL}/api/cadence/definition`, {
      cache: "no-store",
    });
    if (!upstream.ok) {
      return NextResponse.json(
        { error: `backend respondeu ${upstream.status}` },
        { status: 502 },
      );
    }
    return NextResponse.json(await upstream.json());
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
