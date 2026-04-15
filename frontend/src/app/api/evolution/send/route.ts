import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(req: NextRequest) {
  const { phone, text } = await req.json();
  if (!phone || !text) {
    return NextResponse.json(
      { error: "phone and text are required" },
      { status: 400 }
    );
  }

  const baseUrl = process.env.EVOLUTION_API_URL!.replace(/\/+$/, "");
  const instanceName = process.env.EVOLUTION_INSTANCE!;
  const encodedInstance = encodeURIComponent(instanceName);

  try {
    const res = await fetch(
      `${baseUrl}/message/sendText/${encodedInstance}`,
      {
        method: "POST",
        headers: {
          apikey: process.env.EVOLUTION_API_KEY!,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ number: phone, text }),
      }
    );

    if (!res.ok) {
      const err = await res.text();
      return NextResponse.json({ error: err }, { status: res.status });
    }

    // Auto-create lead if it doesn't exist
    const supabase = await getServiceSupabase();
    const { data: existingLead } = await supabase
      .from("leads")
      .select("id")
      .eq("phone", phone)
      .maybeSingle();

    if (!existingLead) {
      const { data: newLead, error: insertError } = await supabase
        .from("leads")
        .insert({
          phone,
          name: null,
          status: "active",
          stage: "secretaria",
          human_control: true,
          channel: "evolution",
        })
        .select()
        .single();

      if (insertError) {
        return NextResponse.json({ ok: true, leadError: insertError.message });
      }

      return NextResponse.json({ ok: true, lead: newLead });
    }

    return NextResponse.json({ ok: true });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
