import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PUT(req: NextRequest, { params }: { params: Promise<{ model: string }> }) {
  const { model } = await params;
  const body = await req.json();
  const sb = await getServiceSupabase();

  const { error } = await sb
    .from("model_pricing")
    .update({
      price_per_input_token: body.price_per_input_token,
      price_per_output_token: body.price_per_output_token,
      updated_at: new Date().toISOString(),
    })
    .eq("model", model);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
