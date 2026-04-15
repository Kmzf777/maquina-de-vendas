import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const sb = await getServiceSupabase();
  const { data, error } = await sb
    .from("model_pricing")
    .select("*")
    .order("model");

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data });
}
