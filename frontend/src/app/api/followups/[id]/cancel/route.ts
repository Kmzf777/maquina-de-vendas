import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

/** Cancelamento GUARDADO de um toque pela operação.
 *  Só pending/awaiting_reopen são canceláveis — o filtro .in_ garante que um job já
 *  enviado ou reivindicado pelo worker ('processing') NUNCA seja rebaixado; a corrida
 *  com o claim atômico do worker resolve a favor de quem chegou primeiro. */
export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("follow_up_jobs")
    .update({ status: "cancelled", cancel_reason: "cancelled_by_operator" })
    .eq("id", id)
    .eq("env_tag", APP_ENV)
    .in("status", ["pending", "awaiting_reopen"])
    .select("id, status, cancel_reason");

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  if (!data || data.length === 0) {
    return NextResponse.json(
      { error: "Job não é cancelável (já enviado, em processamento ou inexistente)" },
      { status: 409 },
    );
  }
  return NextResponse.json(data[0]);
}
