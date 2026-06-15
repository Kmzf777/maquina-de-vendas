import { NextResponse, type NextRequest } from "next/server";

const FASTAPI_URL = (
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000"
).replace(/\/+$/, "");

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  let upstream: Response;
  try {
    upstream = await fetch(`${FASTAPI_URL}/api/leads/${id}/optout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return NextResponse.json(
      { error: "Falha ao conectar ao backend" },
      { status: 502 }
    );
  }

  const body = await upstream.json().catch(() => ({}));
  return NextResponse.json(body, { status: upstream.status });
}
