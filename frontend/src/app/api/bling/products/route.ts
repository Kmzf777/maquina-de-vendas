const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const q = searchParams.get("q") || "";
  const limit = searchParams.get("limit") || "50";
  const url = `${backend()}/api/bling/products?limit=${encodeURIComponent(limit)}${
    q ? `&q=${encodeURIComponent(q)}` : ""
  }`;
  try {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "products_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
