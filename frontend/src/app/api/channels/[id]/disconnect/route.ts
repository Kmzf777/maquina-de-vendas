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
      { error: "Only Evolution channels support disconnect" },
      { status: 400 }
    );
  }

  const config = channel.provider_config;
  const baseUrl = (config.api_url as string).replace(/\/+$/, "");
  const instanceName = config.instance as string;
  const encodedInstance = encodeURIComponent(instanceName);

  try {
    await fetch(`${baseUrl}/instance/logout/${encodedInstance}`, {
      method: "DELETE",
      headers: { apikey: config.api_key as string },
    });
    return NextResponse.json({ ok: true });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
