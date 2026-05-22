import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaigns")
    .select("*")
    .eq("env_tag", APP_ENV)
    .order("created_at", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data });
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaigns")
    .insert({
      name: body.name,
      description: body.description ?? null,
      status: "draft",
      channel_id: body.channel_id ?? null,
      priority: body.priority ?? null,
      frequency_cap: body.frequency_cap ?? null,
      env_tag: APP_ENV,
    })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
