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

    // Fire tag_added automation trigger for each newly added tag (fire-and-forget)
    try {
      const { data: tagRows } = await supabase
        .from("tags")
        .select("id, name")
        .in("id", tagIds);

      if (tagRows && tagRows.length > 0) {
        const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
        for (const tag of tagRows) {
          void fetch(`${backendUrl}/api/automation/trigger`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              event_type: "tag_added",
              lead_id: id,
              data: { tag_name: tag.name },
            }),
          }).catch(() => {});
        }
      }
    } catch {
      // Trigger dispatch is non-critical — do not fail the request
    }
  }

  return NextResponse.json({ ok: true });
}
