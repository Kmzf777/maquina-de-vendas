const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  // Sem default sintetico: ausente, o backend aplica o dele (config.DEFAULT_ACCOUNT).
  const account = searchParams.get("account");
  const url = `${backend()}/api/bling/sellers${
    account ? `?account=${encodeURIComponent(account)}` : ""
  }`;
  try {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "sellers_unavailable" }, { status: resp.status });
    return Response.json(await resp.json());
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
