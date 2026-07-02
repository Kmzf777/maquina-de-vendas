import { type NextRequest } from "next/server";

export async function GET(request: NextRequest) {
  const all = request.nextUrl.searchParams.get("all") === "true";
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  const url = `${backendUrl}/api/conversions/google-export.csv${all ? "?all=true" : ""}`;

  const resp = await fetch(url, { method: "GET" });
  if (!resp.ok) {
    return new Response(JSON.stringify({ error: "Falha ao gerar CSV de conversões." }), {
      status: resp.status,
      headers: { "Content-Type": "application/json" },
    });
  }
  const body = await resp.text();
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": 'attachment; filename="google_conversions.csv"',
    },
  });
}
