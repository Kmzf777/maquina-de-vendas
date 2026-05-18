import { NextResponse, type NextRequest } from "next/server";

// ⚠️ LOGIN TEMPORARIAMENTE DESATIVADO
// O sistema de auth (Supabase) está implementado mas desativado enquanto bugs são corrigidos.
// Para reativar: substituir este arquivo pela versão original em git history
// (commit onde middleware.ts tinha createServerClient + supabase.auth.getUser).
// Ver também: CLAUDE.md seção "Login desativado temporariamente".
export async function middleware(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/leads/:path*",
    "/conversas/:path*",
    "/campanhas/:path*",
    "/qualificacao/:path*",
    "/vendas/:path*",
    "/canais/:path*",
    "/estatisticas/:path*",
    "/config/:path*",
    "/api/channels/:path*",
    "/api/stats/:path*",
    "/api/agent-profiles/:path*",
    "/api/evolution/:path*",
    "/api/admin/:path*",
    "/api/broadcasts/:path*",
    "/api/cadences/:path*",
    "/api/campaigns/:path*",
    "/api/leads/:path*",
    "/api/conversations/:path*",
    "/api/deals/:path*",
    "/api/templates/:path*",
    "/api/template-presets/:path*",
    "/api/tags/:path*",
    "/api/pipelines/:path*",
    "/api/chat/:path*",
    "/api/media/:path*",
    "/api/quick-send-phones/:path*",
  ],
};
