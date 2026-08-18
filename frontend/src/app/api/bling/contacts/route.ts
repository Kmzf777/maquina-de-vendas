const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function POST(req: Request) {
  const body = await req.json();
  try {
    const resp = await fetch(`${backend()}/api/bling/contacts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return Response.json(await resp.json(), { status: resp.status });
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
