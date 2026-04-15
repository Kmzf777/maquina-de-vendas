import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { tagIds } = await request.json() as { tagIds: string[] };

  const { error: deleteError } = await supabase
    .from("lead_tags")
    .delete()
    .eq("lead_id", id);

  if (deleteError) {
    return NextResponse.json({ error: deleteError.message }, { status: 500 });
  }

  if (tagIds.length > 0) {
    const rows = tagIds.map((tagId) => ({ lead_id: id, tag_id: tagId }));
    const { error: insertError } = await supabase
      .from("lead_tags")
      .insert(rows);

    if (insertError) {
      return NextResponse.json({ error: insertError.message }, { status: 500 });
    }
  }

  return NextResponse.json({ ok: true });
}
