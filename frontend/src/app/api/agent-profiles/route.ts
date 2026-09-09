import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

/**
 * Perfis de agente para o seletor do wizard de disparo.
 *
 * `kind` entrou no select porque sem ele o operador não distingue um perfil de fluxo de
 * botões (roteiro fechado, todo texto declarado em backend/app/button_flow/flows.py) de
 * uma ValerIA generativa — os dois chegavam aqui só como nome. E é o `kind` que decide
 * quais perfis podem ser escolhidos num canal `mode='human'`
 * (create-broadcast-modal.tsx, passo 1).
 *
 * O segundo select existe por causa da ordem de aplicação da migration: em 2026-09-09 o
 * information_schema de produção ainda não tinha `agent_profiles.kind` — a migration
 * supabase/migrations/20260820_button_flow_agent.sql é aplicada à mão e não estava lá.
 * Um select cego na coluna devolve 42703 (undefined_column) → 500 → o `.catch` do modal
 * (create-broadcast-modal.tsx:192) zera a lista e o operador fica SEM NENHUM agente para
 * escolher, quebrando o disparo que já funciona hoje no canal da ValerIA. Então: tenta com
 * `kind` e, só nesse erro específico, repete sem a coluna assumindo 'llm' — o mesmo DEFAULT
 * que a migration vai criar.
 */
export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("agent_profiles")
    .select("id, name, kind")
    .order("created_at", { ascending: false });

  if (!error) return NextResponse.json(data);

  // 42703 = undefined_column: banco ainda sem a migration 20260820.
  if (error.code !== "42703") {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const semKind = await supabase
    .from("agent_profiles")
    .select("id, name")
    .order("created_at", { ascending: false });

  if (semKind.error) {
    return NextResponse.json({ error: semKind.error.message }, { status: 500 });
  }
  return NextResponse.json((semKind.data ?? []).map((p) => ({ ...p, kind: "llm" })));
}
