import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { parseTemplateComponents } from "@/lib/template-parser";
import { dedupeTemplatesByNameLang } from "@/lib/dedupe-templates";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");

  const supabase = await getServiceSupabase();
  let query = supabase
    .from("message_templates")
    .select("id, name, language, category, requested_category, status, created_at, channel_id, components")
    .order("created_at", { ascending: false });

  if (channelId) query = query.eq("channel_id", channelId);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Listagem global (sem channel_id): os 3 canais compartilham a mesma WABA, então cada
  // template aparece 2-3x (uma linha-espelho por canal). Dedupe por (name, language) para
  // a UI — apresentação apenas, não altera o banco. Com channel_id, a visão é por canal
  // (uma linha por nome/idioma), então a dedupe é inócua mas mantida por consistência.
  const rows = channelId ? (data ?? []) : dedupeTemplatesByNameLang(data ?? []);

  const enriched = rows.map((t) => {
    const components = Array.isArray(t.components) ? t.components : [];
    const parsed = parseTemplateComponents(components);
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { components: _components, ...rest } = t as typeof t & { components: unknown[] };
    return { ...rest, ...parsed };
  });

  return NextResponse.json(enriched);
}
