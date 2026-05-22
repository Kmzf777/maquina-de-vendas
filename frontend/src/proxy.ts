import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { isAdminOnlyPage, isAdminOnlyApiRoute } from "@/lib/auth/roles";

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const isApiRoute = pathname.startsWith("/api/");

  if (!user) {
    if (isApiRoute) {
      return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
    }
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const role = user.app_metadata?.role as string | undefined;

  if (role !== "admin" && role !== "vendedor") {
    if (isApiRoute) {
      return NextResponse.json(
        { error: "Role não configurado. Contate o administrador." },
        { status: 403 }
      );
    }
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (role !== "admin") {
    if (isApiRoute && isAdminOnlyApiRoute(pathname)) {
      return NextResponse.json(
        { error: "Permissão insuficiente" },
        { status: 403 }
      );
    }
    if (!isApiRoute && isAdminOnlyPage(pathname)) {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }
  }

  return supabaseResponse;
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
    "/api/automation/:path*",
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
