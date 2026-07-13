import { NextResponse } from "next/server";

/**
 * Cotação USD→BRL do painel. Proxy do backend (mesmo padrão de
 * /api/conversions/dashboard). O backend nunca falha — degrada para uma taxa
 * marcada como stale —, mas se ele estiver inalcançável devolvemos 502 e o
 * dashboard cai no modo moeda-única, sem quebrar.
 */
export async function GET() {
  const backendUrl = (
    process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000"
  ).replace(/\/+$/, "");

  try {
    const resp = await fetch(`${backendUrl}/api/fx/rate`, { cache: "no-store" });
    if (!resp.ok) {
      return NextResponse.json({ error: "fx_unavailable" }, { status: resp.status });
    }
    return NextResponse.json(await resp.json());
  } catch {
    return NextResponse.json({ error: "fx_unreachable" }, { status: 502 });
  }
}
