import { NextRequest, NextResponse } from "next/server";
import { createClient as createServerClient } from "@/lib/supabase/server";
import { createClient } from "@supabase/supabase-js";

export async function POST(req: NextRequest) {
  // Verificar que o chamador é admin
  const supabase = await createServerClient();
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();

  if (authError || !user) {
    return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
  }

  if (user.app_metadata?.role !== "admin") {
    return NextResponse.json(
      { error: "Permissão insuficiente" },
      { status: 403 }
    );
  }

  // Validar body
  const body = await req.json();
  const { user_id, role } = body as { user_id?: string; role?: string };

  if (!user_id || !role || !["admin", "vendedor"].includes(role)) {
    return NextResponse.json(
      { error: "Parâmetros inválidos. Informe user_id e role (admin|vendedor)." },
      { status: 400 }
    );
  }

  // Setar role via Admin API (service role)
  const adminClient = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );

  const { error } = await adminClient.auth.admin.updateUserById(user_id, {
    app_metadata: { role },
  });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, user_id, role });
}
