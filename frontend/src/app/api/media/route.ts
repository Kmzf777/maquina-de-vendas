import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: NextRequest) {
  // Auth check: require a valid session
  const authClient = await createClient();
  const { data: { user } } = await authClient.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { searchParams } = request.nextUrl;
  const mediaId = searchParams.get("media_id");
  const conversationId = searchParams.get("conversation_id");

  if (!mediaId || !conversationId) {
    return NextResponse.json({ error: "Missing media_id or conversation_id" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();
  const { data: conv, error: dbError } = await supabase
    .from("conversations")
    .select("channels(provider_config)")
    .eq("id", conversationId)
    .single();

  if (dbError) {
    return NextResponse.json({ error: "DB error" }, { status: 500 });
  }

  if (!conv) {
    return NextResponse.json({ error: "Conversation not found" }, { status: 404 });
  }

  const channelsData = conv.channels as unknown;
  const channel = Array.isArray(channelsData) ? channelsData[0] : channelsData;
  const config = (channel as { provider_config: Record<string, string> } | null)
    ?.provider_config;
  const accessToken = config?.access_token;
  const apiVersion = config?.api_version ?? "v21.0";

  if (!accessToken) {
    return NextResponse.json({ error: "No access token configured" }, { status: 403 });
  }

  // Step 1: Resolve media_id → temporary download URL
  const infoRes = await fetch(
    `https://graph.facebook.com/${apiVersion}/${mediaId}`,
    { headers: { Authorization: `Bearer ${accessToken}` } }
  );
  if (!infoRes.ok) {
    return NextResponse.json({ error: "Meta media info fetch failed" }, { status: 502 });
  }
  const info = await infoRes.json() as { url?: string; mime_type?: string };
  const downloadUrl = info.url;
  const mimeType = info.mime_type ?? "audio/ogg";

  if (!downloadUrl) {
    return NextResponse.json({ error: "No download URL from Meta" }, { status: 502 });
  }

  // SSRF guard: only allow Meta's CDN domain
  const allowed = new URL(downloadUrl);
  if (!allowed.hostname.endsWith(".fbcdn.net") || allowed.protocol !== "https:") {
    return NextResponse.json({ error: "Unexpected media host" }, { status: 502 });
  }

  // Step 2: Download audio bytes
  const audioRes = await fetch(downloadUrl, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!audioRes.ok) {
    return NextResponse.json({ error: "Audio download failed" }, { status: 502 });
  }

  const audioBuffer = await audioRes.arrayBuffer();

  return new NextResponse(audioBuffer, {
    headers: {
      "Content-Type": mimeType,
      "Cache-Control": "private, max-age=3600",
    },
  });
}
