import { NextResponse, type NextRequest } from "next/server";

const FASTAPI_URL = (
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000"
).replace(/\/+$/, "");

// Proxy puro para o FastAPI, espelhando `leads/[id]/optout/route.ts`.
// Corpo devolvido pelo backend: {"blocked": false, "deals_restaurados": n,
// "deals_pendentes": m}. `deals_pendentes` > 0 significa card na Blacklist sem origem
// conhecida no snapshot — o backend NÃO adivinha destino, e a UI avisa o operador para
// mover o card no Kanban. Repassamos o corpo intacto justamente por isso.
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  let upstream: Response;
  try {
    upstream = await fetch(`${FASTAPI_URL}/api/leads/${id}/unblock`, {
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
