import { NextResponse, type NextRequest } from "next/server";
import { feelingValidationError } from "@/lib/valeria-score";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";

export async function PUT(request: NextRequest, context: { params: Promise<{ leadId: string }> }) {
  let user: Awaited<ReturnType<typeof getCurrentUser>>;
  try {
    user = await getCurrentUser();
  } catch {
    return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
  }
  if (user.role !== "vendedor") return NextResponse.json({ error: "Apenas vendedores podem registrar Feeling." }, { status: 403 });
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Dados de Feeling inválidos." }, { status: 422 });
  }
  const validationError = feelingValidationError(body);
  if (validationError) return NextResponse.json({ error: validationError }, { status: 422 });
  const { leadId } = await context.params;
  const { feeling, justification } = body as { feeling: "baixo" | "medio" | "alto"; justification: string };
  const supabase = await getServiceSupabase();
  const { data: lead, error: leadError } = await supabase.from("leads").select("id").eq("id", leadId).eq("stage", "atacado").maybeSingle();
  if (leadError) return NextResponse.json({ error: leadError.message }, { status: 500 });
  if (!lead) return NextResponse.json({ error: "Lead de atacado não encontrado." }, { status: 404 });
  const { data, error } = await supabase
    .from("lead_seller_feelings")
    .upsert({ lead_id: leadId, user_id: user.userId, seller_email: user.email ?? null, feeling, justification: justification.trim(), updated_at: new Date().toISOString() }, { onConflict: "lead_id,user_id" })
    .select("lead_id, user_id, seller_email, feeling, justification, updated_at")
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}
