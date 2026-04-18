import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ phone: string }> }
) {
  const { phone } = await params;
  const supabase = await getServiceSupabase();

  const { error } = await supabase
    .from("quick_send_phones")
    .delete()
    .eq("phone", decodeURIComponent(phone));

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
