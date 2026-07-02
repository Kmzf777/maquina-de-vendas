export async function GET() {
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  try {
    const resp = await fetch(`${backendUrl}/api/conversions/stats`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "stats_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "stats_unreachable" }, { status: 502 });
  }
}
