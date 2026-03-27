import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

export async function GET(_req: NextRequest) {
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

  try {
    const res = await fetch(
      `${process.env.EVOLUTION_API_URL}/instance/connectionState/${instanceName}`,
      { headers: { apikey: process.env.EVOLUTION_API_KEY! } }
    );

    if (!res.ok) {
      return NextResponse.json({ connected: false });
    }

    const data = await res.json();
    const connected = data?.instance?.state === "open";

    return NextResponse.json({
      connected,
      ...(connected && data?.instance?.phoneNumber
        ? { number: data.instance.phoneNumber }
        : {}),
    });
  } catch {
    return NextResponse.json({ connected: false });
  }
}
