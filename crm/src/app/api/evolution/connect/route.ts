import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

export async function POST(_req: NextRequest) {
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

  const instanceName = `seller-${user.id}`;
  const headers = {
    apikey: process.env.EVOLUTION_API_KEY!,
    "Content-Type": "application/json",
  };

  try {
    // First try: connect existing instance
    const connectRes = await fetch(
      `${process.env.EVOLUTION_API_URL}/instance/connect/${instanceName}`,
      { headers }
    );

    if (connectRes.ok) {
      const data = await connectRes.json();
      return NextResponse.json({ qrcode: data.base64 ?? data.qrcode?.base64 ?? "" });
    }

    // If 404, instance doesn't exist — create it
    if (connectRes.status === 404) {
      const createRes = await fetch(
        `${process.env.EVOLUTION_API_URL}/instance/create`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({
            instanceName,
            qrcode: true,
            integration: "WHATSAPP-BAILEYS",
          }),
        }
      );

      if (!createRes.ok) {
        const err = await createRes.text();
        return NextResponse.json({ error: err }, { status: createRes.status });
      }

      const data = await createRes.json();
      return NextResponse.json({ qrcode: data.qrcode?.base64 ?? data.base64 ?? "" });
    }

    const err = await connectRes.text();
    return NextResponse.json({ error: err }, { status: connectRes.status });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}
