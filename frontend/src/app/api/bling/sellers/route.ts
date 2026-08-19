const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function GET() {
  try {
    const resp = await fetch(`${backend()}/api/bling/sellers`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "sellers_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
