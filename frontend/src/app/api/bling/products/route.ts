const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const q = searchParams.get("q") || "";
  const limit = searchParams.get("limit") || "50";
  // account NAO tem default aqui: se o chamador nao informar, o backend
  // aplica o dele (config.DEFAULT_ACCOUNT) sozinho. Sintetizar um fallback
  // aqui duplicaria essa regra num segundo lugar, e o proxy nunca deveria
  // decidir qual e a conta padrao.
  const account = searchParams.get("account");
  const url = `${backend()}/api/bling/products?limit=${encodeURIComponent(limit)}${
    q ? `&q=${encodeURIComponent(q)}` : ""
  }${account ? `&account=${encodeURIComponent(account)}` : ""}`;
  try {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "products_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
