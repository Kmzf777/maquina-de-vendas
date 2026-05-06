import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import ffmpegPath from 'ffmpeg-static';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { writeFile, readFile, unlink } from 'fs/promises';
import { tmpdir } from 'os';
import { join } from 'path';
import { randomBytes } from 'crypto';

const META_API_VERSION = "v21.0";
const MAX_FILE_SIZE = 16 * 1024 * 1024; // 16MB

const META_SUPPORTED_AUDIO_TYPES = new Set([
  'audio/aac',
  'audio/mp4',
  'audio/mpeg',
  'audio/amr',
  'audio/ogg',
  'audio/opus',
]);

const execFileAsync = promisify(execFile);

async function convertToOgg(inputBuffer: Buffer, inputMime: string): Promise<Buffer> {
  const id = randomBytes(8).toString('hex');
  const ext = inputMime.includes('webm') ? 'webm' : 'bin';
  const inputPath = join(tmpdir(), `mv_audio_${id}.${ext}`);
  const outputPath = join(tmpdir(), `mv_audio_${id}.ogg`);
  try {
    await writeFile(inputPath, inputBuffer);
    await execFileAsync(ffmpegPath as string, [
      '-y',
      '-i', inputPath,
      '-c:a', 'libopus',
      '-b:a', '64k',
      outputPath,
    ]);
    return await readFile(outputPath);
  } finally {
    await unlink(inputPath).catch(() => {});
    await unlink(outputPath).catch(() => {});
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: conversationId } = await params;

  const supabase = await getServiceSupabase();

  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return NextResponse.json({ error: "Invalid form data" }, { status: 400 });
  }

  const file = formData.get("file") as File | null;
  if (!file) {
    return NextResponse.json({ error: "file is required" }, { status: 400 });
  }

  if (file.size > MAX_FILE_SIZE) {
    return NextResponse.json(
      { error: "Arquivo muito grande (máx 16MB)" },
      { status: 400 }
    );
  }

  if (file.size === 0) {
    return NextResponse.json({ error: "Arquivo vazio" }, { status: 400 });
  }

  const mimeType = file.type;
  let messageType: "audio" | "image";
  if (mimeType.startsWith("audio/")) {
    messageType = "audio";
  } else if (mimeType.startsWith("image/")) {
    messageType = "image";
  } else {
    return NextResponse.json(
      { error: "Tipo de arquivo não suportado. Use áudio ou imagem." },
      { status: 400 }
    );
  }

  const { data: conv, error: convError } = await supabase
    .from("conversations")
    .select("*, leads(id, phone), channels(id, provider, provider_config)")
    .eq("id", conversationId)
    .single();

  if (convError || !conv) {
    return NextResponse.json({ error: "Conversation not found" }, { status: 404 });
  }

  const channel = conv.channels as {
    id: string;
    provider: string;
    provider_config: Record<string, string>;
  } | null;
  const lead = conv.leads as { id: string; phone: string } | null;

  if (!channel || !lead?.phone) {
    return NextResponse.json({ error: "Invalid conversation data" }, { status: 400 });
  }

  if (channel.provider !== "meta_cloud") {
    return NextResponse.json(
      { error: "Envio de mídia disponível apenas para Meta Cloud" },
      { status: 400 }
    );
  }

  const { phone_number_id, access_token, api_version } = channel.provider_config;
  const version = api_version || META_API_VERSION;

  if (!phone_number_id || !access_token) {
    console.error("[send-media] channel misconfigured — missing phone_number_id or access_token");
    return NextResponse.json({ error: "Canal não configurado corretamente" }, { status: 500 });
  }

  try {
    // Convert unsupported audio formats (e.g. audio/webm from Chrome) to audio/ogg
    let uploadBlob: Blob = file;
    let uploadMime = mimeType;
    let uploadFilename = file.name || 'audio';
    if (messageType === 'audio') {
      const baseMime = mimeType.split(';')[0].trim();
      if (!META_SUPPORTED_AUDIO_TYPES.has(baseMime)) {
        console.log(`[send-media] converting ${mimeType} → audio/ogg`);
        const inputBuffer = Buffer.from(await file.arrayBuffer());
        const oggBuffer = await convertToOgg(inputBuffer, mimeType);
        uploadBlob = new Blob([new Uint8Array(oggBuffer)], { type: 'audio/ogg' });
        uploadMime = 'audio/ogg';
        uploadFilename = 'audio.ogg';
      }
    }

    // Step 1: Upload to Meta Media API
    const uploadForm = new FormData();
    uploadForm.append("file", uploadBlob, uploadFilename);
    uploadForm.append("messaging_product", "whatsapp");
    uploadForm.append("type", uploadMime);

    const uploadResp = await fetch(
      `https://graph.facebook.com/${version}/${phone_number_id}/media`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${access_token}` },
        body: uploadForm,
      }
    );

    if (!uploadResp.ok) {
      const err = await uploadResp.text();
      console.error("[send-media] Meta upload failed:", err);
      return NextResponse.json(
        { error: "Falha ao enviar arquivo para WhatsApp" },
        { status: 502 }
      );
    }

    const { id: mediaId } = (await uploadResp.json()) as { id: string };

    // Step 2: Send message via Meta Graph API
    const sendPayload = {
      messaging_product: "whatsapp",
      to: lead.phone,
      type: messageType,
      [messageType]: { id: mediaId },
    };

    const sendResp = await fetch(
      `https://graph.facebook.com/${version}/${phone_number_id}/messages`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(sendPayload),
      }
    );

    if (!sendResp.ok) {
      const err = await sendResp.text();
      console.error("[send-media] Meta send failed:", err);
      return NextResponse.json(
        { error: "Falha ao enviar mensagem" },
        { status: 502 }
      );
    }

    // Step 3: Save to DB
    await supabase.from("messages").insert({
      lead_id: lead.id,
      conversation_id: conversationId,
      role: "assistant",
      content: "",
      sent_by: "seller",
      message_type: messageType,
      media_url: mediaId,
    });

    await supabase
      .from("conversations")
      .update({
        unread_count: 0,
        last_msg_at: new Date().toISOString(),
      })
      .eq("id", conversationId);

    return NextResponse.json({ status: "sent" });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Failed to send media";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
