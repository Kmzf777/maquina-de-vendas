import { NextResponse } from "next/server";

function extractContent(msg: Record<string, unknown>): string {
  const m = msg.message as Record<string, unknown> | undefined;
  if (!m) return "";
  if (typeof m.conversation === "string") return m.conversation;
  const img = m.imageMessage as Record<string, unknown> | undefined;
  if (img?.caption) return img.caption as string;
  if (img) return "[Imagem]";
  if (m.audioMessage) return "[Audio]";
  const doc = m.documentMessage as Record<string, unknown> | undefined;
  if (doc?.fileName) return `[Documento: ${doc.fileName}]`;
  if (m.stickerMessage) return "[Sticker]";
  if (m.videoMessage) return "[Video]";
  return "[Midia]";
}

export async function GET() {
  const baseUrl = process.env.EVOLUTION_API_URL!.replace(/\/+$/, "");
  const instanceName = process.env.EVOLUTION_INSTANCE!;
  const encodedInstance = encodeURIComponent(instanceName);

  try {
    const res = await fetch(
      `${baseUrl}/chat/findChats/${encodedInstance}`,
      {
        method: "POST",
        headers: {
          apikey: process.env.EVOLUTION_API_KEY!,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({}),
      }
    );

    if (!res.ok) {
      const err = await res.text();
      return NextResponse.json({ error: err }, { status: res.status });
    }

    const rawChats = await res.json();

    // Normalize Evolution API response to match our EvolutionChat type
    const chats = (Array.isArray(rawChats) ? rawChats : []).map(
      (chat: Record<string, unknown>) => {
        const lastMsg = chat.lastMessage as Record<string, unknown> | null;
        // Resolve LID-based JIDs: use remoteJidAlt from lastMessage key if available
        let remoteJid = chat.remoteJid as string;
        if (remoteJid.endsWith("@lid") && lastMsg) {
          const key = lastMsg.key as Record<string, unknown> | undefined;
          const alt = key?.remoteJidAlt as string | undefined;
          if (alt) remoteJid = alt;
        }

        return {
          id: chat.id,
          remoteJid,
          pushName: chat.pushName ?? chat.name ?? null,
          profilePicUrl: chat.profilePicUrl ?? null,
          lastMessage: lastMsg
            ? {
                content: extractContent(lastMsg),
                timestamp: (lastMsg.messageTimestamp as number) || 0,
              }
            : null,
          unreadCount: (chat.unreadCount as number) || 0,
        };
      }
    );

    return NextResponse.json(chats);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
