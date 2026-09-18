import { NextResponse, type NextRequest } from "next/server";

const FASTAPI_URL = (
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000"
).replace(/\/+$/, "");

// Proxy puro para o FastAPI, espelhando `leads/[id]/optout/route.ts`. O bloqueio tem
// efeitos colaterais transacionais (opt_out + Blacklist + cancelamento de enrollments e
// follow-ups + snapshot para o desbloqueio) que vivem em `block_lead` no backend — o
// Next não reimplementa nada disso, só repassa status e corpo.
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  let upstream: Response;
  try {
    upstream = await fetch(`${FASTAPI_URL}/api/leads/${id}/block`, {
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
