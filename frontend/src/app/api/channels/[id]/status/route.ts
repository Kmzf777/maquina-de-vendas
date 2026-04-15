import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
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
      { error: "Only Evolution channels have connection status" },
      { status: 400 }
    );
  }

  const config = channel.provider_config;
  const baseUrl = (config.api_url as string).replace(/\/+$/, "");
  const instanceName = config.instance as string;
  const encodedInstance = encodeURIComponent(instanceName);

  try {
    const res = await fetch(
      `${baseUrl}/instance/connectionState/${encodedInstance}`,
      { headers: { apikey: config.api_key as string } }
    );

    if (!res.ok) {
      return NextResponse.json({ connected: false });
    }

    const data = await res.json();
    const connected = data?.instance?.state === "open";
    const number = connected ? data?.instance?.phoneNumber : undefined;

    // If connected and phone not yet saved, update it
    if (connected && number && !channel.phone) {
      await supabase
        .from("channels")
        .update({ phone: number.replace(/\D/g, "") })
        .eq("id", id);
    }

    return NextResponse.json({
      connected,
      ...(number ? { number } : {}),
    });
  } catch {
    return NextResponse.json({ connected: false });
  }
}
