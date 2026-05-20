import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  await supabase.from("campaigns").update({ status: "paused", updated_at: new Date().toISOString() }).eq("id", id);
  return NextResponse.json({ status: "paused" });
}
