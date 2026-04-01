import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data: channel, error } = await supabase
    .from("channels")
    .select("*")
    .eq("id", id)
    .single();

  if (error || !channel) {
    return NextResponse.json({ error: "Channel not found" }, { status: 404 });
  }

  if (channel.provider !== "evolution") {
    return NextResponse.json(
      { error: "Only Evolution channels support QR connection" },
      { status: 400 }
    );
  }

  const config = channel.provider_config;
  const baseUrl = (config.api_url as string).replace(/\/+$/, "");
  const instanceName = config.instance as string;
  const encodedInstance = encodeURIComponent(instanceName);
  const headers = {
    apikey: config.api_key as string,
    "Content-Type": "application/json",
  };

  try {
    const connectRes = await fetch(
      `${baseUrl}/instance/connect/${encodedInstance}`,
      { method: "GET", headers }
    );

    if (connectRes.ok) {
      const data = await connectRes.json();
      const qr = data.base64 ?? data.qrcode?.base64 ?? "";
      if (qr) {
        return NextResponse.json({ qrcode: qr });
      }
      return NextResponse.json({ connected: true });
    }

    if (connectRes.status === 404) {
      const createRes = await fetch(`${baseUrl}/instance/create`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          instanceName,
          qrcode: true,
          integration: "WHATSAPP-BAILEYS",
        }),
      });

      if (!createRes.ok) {
        const err = await createRes.text();
        return NextResponse.json({ error: err }, { status: createRes.status });
      }

      const data = await createRes.json();
      const qr = data.qrcode?.base64 ?? data.base64 ?? "";
      return NextResponse.json({ qrcode: qr });
    }

    const err = await connectRes.text();
    return NextResponse.json({ error: err }, { status: connectRes.status });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
