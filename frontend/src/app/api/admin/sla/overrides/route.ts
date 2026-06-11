import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { createClient as createServerClient } from "@/lib/supabase/server";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET() {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_overrides")
    .select("*")
    .order("start_date", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(req: NextRequest) {
  const gate = await requireAdmin();
  if (!gate.ok) return NextResponse.json({ error: gate.error }, { status: gate.status });

  const { user_id, start_date, end_date, reason } = await req.json();
  if (!start_date || !end_date) {
    return NextResponse.json({ error: "start_date e end_date obrigatórios" }, { status: 400 });
  }
  if (end_date < start_date) {
    return NextResponse.json({ error: "end_date deve ser >= start_date" }, { status: 400 });
  }

  // created_by = admin logado
  const authClient = await createServerClient();
  const {
    data: { user },
  } = await authClient.auth.getUser();

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sla_overrides")
    .insert({
      user_id: user_id ?? null,
      start_date,
      end_date,
      reason: reason ?? null,
      created_by: user?.id ?? null,
    })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data, { status: 201 });
}
