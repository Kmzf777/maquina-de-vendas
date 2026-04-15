import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("agent_profiles")
    .select("id, name")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}
