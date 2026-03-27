import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

export async function POST(req: NextRequest) {
  const cookieStore = await cookies();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    {
      cookies: {
        getAll() { return cookieStore.getAll(); },
        setAll() {},
      },
    }
  );
  const anonSupabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() { return cookieStore.getAll(); },
        setAll() {},
      },
    }
  );
  const { data: { user } } = await anonSupabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { phone, text } = await req.json();
  if (!phone || !text) {
    return NextResponse.json(
      { error: "phone and text are required" },
      { status: 400 }
    );
  }

  const instanceName = `seller-${user.id}`;

  try {
    // Send the message
    const res = await fetch(
      `${process.env.EVOLUTION_API_URL}/message/sendText/${instanceName}`,
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
          seller_stage: "novo",
          human_control: true,
          channel: "evolution",
        })
        .select()
        .single();

      if (insertError) {
        // Message was sent successfully, but lead creation failed — still return ok
        return NextResponse.json({ ok: true, leadError: insertError.message });
      }

      return NextResponse.json({ ok: true, lead: newLead });
    }

    return NextResponse.json({ ok: true });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
