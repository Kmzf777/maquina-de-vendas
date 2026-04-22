import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

const WEBHOOK_EVENTS = [
  "MESSAGES_UPSERT",
  "MESSAGES_UPDATE",
  "CONNECTION_UPDATE",
];

async function setWebhook(baseUrl: string, instanceName: string, headers: Record<string, string>, backendUrl: string) {
  const webhookUrl = `${backendUrl}/webhook/evolution`;
  try {
    await fetch(`${baseUrl}/webhook/set/${encodeURIComponent(instanceName)}`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        webhook: {
          enabled: true,
          url: webhookUrl,
          events: WEBHOOK_EVENTS,
          webhookByEvents: false,
        },
      }),
    });
  } catch (e) {
    console.error("[evolution/connect] failed to set webhook:", e);
  }
}

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
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

  try {
    const connectRes = await fetch(
      `${baseUrl}/instance/connect/${encodedInstance}`,
      { method: "GET", headers }
    );

    if (connectRes.ok) {
      const data = await connectRes.json();
      const qr = data.base64 ?? data.qrcode?.base64 ?? "";
      if (qr) {
        // Set webhook while waiting for QR scan
        await setWebhook(baseUrl, instanceName, headers, backendUrl);
        return NextResponse.json({ qrcode: qr });
      }
      // Already connected — ensure webhook is set
      await setWebhook(baseUrl, instanceName, headers, backendUrl);
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

      // Set webhook on newly created instance
      await setWebhook(baseUrl, instanceName, headers, backendUrl);

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
