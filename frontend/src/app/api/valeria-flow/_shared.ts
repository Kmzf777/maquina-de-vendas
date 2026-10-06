import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireAdmin } from "@/lib/admin-auth";

/**
 * Proxy admin-only para `backend/app/button_flow/valeria_flow_router.py`.
 *
 * Repassa o `access_token` de sessão do Supabase como `Authorization: Bearer` para o
 * FastAPI. Além deste router, só as rotas admin do /trafego (atribuição manual de
 * campanha, `/api/traffic/*`) o reutilizam. Todo outro proxy para o backend
 * (`/api/campaigns/*`, `/api/quotes`, `/api/channels/[id]/templates`, ...) chama
 * routers SEM `require_role` — não há credencial para repassar porque o backend
 * não pede nenhuma. Este router é diferente por dois fatos, não por gosto:
 *
 *   1. `valeria_flow_router.py` declara `dependencies=[Depends(require_role(["admin"]))]`
 *      no `APIRouter` inteiro — todo endpoint dele já exige um JWT Supabase com
 *      `app_metadata.role == "admin"` (`backend/app/auth/dependencies.py` +
 *      `backend/app/auth/jwt.py`, que decodifica HS256 com `audience="authenticated"`,
 *      exatamente o formato do `session.access_token` do supabase-js).
 *   2. `POST /activate` não edita texto: ele cria um `agent_profiles` novo e
 *      REPONTA `channels.agent_profile_id` (ver o handler no backend). O backend
 *      é publicamente alcançável em `api.canastrainteligencia.com` (regra 4 do
 *      CLAUDE.md) — sem o Bearer, qualquer requisição externa a este endpoint
 *      tomaria o número de WhatsApp do canal escolhido, não só editaria uma frase.
 *
 * Um leitor futuro que "simplificar" isto de volta ao padrão comum (sem Bearer)
 * reabre esse buraco. Não simplifique sem reler os dois pontos acima.
 *
 * Duas regras de segurança que valem para todo uso deste arquivo:
 *   - Sessão ausente/sem token é 401 daqui, e NUNCA um fallback para a service-role
 *     key (`getServiceSupabase`) só para a chamada "funcionar" sem admin logado.
 *   - O token nunca é logado nem colocado em querystring/URL — só no header
 *     `Authorization` da chamada server-to-server.
 */

function backendUrl(): string {
  return (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
}

type Gate = { ok: true; token: string } | { ok: false; response: NextResponse };

async function gateAdmin(): Promise<Gate> {
  const admin = await requireAdmin();
  if (!admin.ok) {
    return { ok: false, response: NextResponse.json({ error: admin.error }, { status: admin.status }) };
  }

  // Segunda leitura de sessão, só para pegar o access_token — `requireAdmin` não o
  // expõe (ele só confirma `ok`/`role`). Mesmo cookie, mesmo usuário.
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  if (!token) {
    return { ok: false, response: NextResponse.json({ error: "Não autenticado" }, { status: 401 }) };
  }
  return { ok: true, token };
}

/**
 * Repassa `status` e corpo do upstream tal qual: o 400 do backend traz uma
 * mensagem em português escrita para o operador (ex.: rótulo de botão acima do
 * limite de 20 caracteres da Meta) e a tela mostra esse texto verbatim. Envelopar
 * num erro genérico esconderia a única coisa que a pessoa precisa ler.
 */
export async function adminProxy(path: string, init?: RequestInit): Promise<NextResponse> {
  const gate = await gateAdmin();
  if (!gate.ok) return gate.response;

  let upstream: Response;
  try {
    upstream = await fetch(`${backendUrl()}${path}`, {
      ...init,
      headers: {
        ...(init?.headers ?? {}),
        Authorization: `Bearer ${gate.token}`,
      },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "Backend indisponível" }, { status: 502 });
  }

  const payload = await upstream.json().catch(() => ({}));
  return NextResponse.json(payload, { status: upstream.status });
}
