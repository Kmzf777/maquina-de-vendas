import { getCurrentUser } from "@/lib/supabase/pipeline-access";

const backend = () =>
  (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

export async function GET() {
  let role: string | undefined;
  try {
    ({ role } = await getCurrentUser());
  } catch {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  try {
    const resp = await fetch(`${backend()}/api/bling/status`, { cache: "no-store" });
    if (!resp.ok) return Response.json({ error: "unavailable" }, { status: resp.status });
    const status = await resp.json();

    // O vendedor PRECISA desta rota: é dela que o modal de venda descobre se
    // entra em modo Bling. Devolver 403 para não-admin deixava a integração
    // invisível para justamente quem a usa, e o modal nunca ativava.
    //
    // O payload completo continua restrito: ele carrega expiração de token e
    // escopos do OAuth, que são informação de administração e não têm por que
    // circular na tela de venda.
    if (role !== "admin") {
      return Response.json({
        enabled: !!status.enabled,
        connected: !!status.connected,
      });
    }
    return Response.json(status);
  } catch {
    return Response.json({ error: "backend_unreachable" }, { status: 502 });
  }
}
