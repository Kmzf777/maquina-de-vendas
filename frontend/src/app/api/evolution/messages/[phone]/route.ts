import { NextResponse, type NextRequest } from "next/server";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ phone: string }> }
) {
  const { phone } = await params;
  const baseUrl = process.env.EVOLUTION_API_URL!.replace(/\/+$/, "");
  const instanceName = process.env.EVOLUTION_INSTANCE!;
  const encodedInstance = encodeURIComponent(instanceName);

  try {
    // Fetch messages (up to 5 pages / ~250 most recent messages)
    const MAX_PAGES = 5;
    let allRecords: unknown[] = [];
    let currentPage = 1;
    let totalPages = 1;

    do {
      const res = await fetch(
        `${baseUrl}/chat/findMessages/${encodedInstance}`,
        {
          method: "POST",
          headers: {
            apikey: process.env.EVOLUTION_API_KEY!,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            where: {
              key: {
                remoteJid: `${phone}@s.whatsapp.net`,
              },
            },
            page: currentPage,
          }),
        }
      );

      if (!res.ok) {
        const err = await res.text();
        return NextResponse.json({ error: err }, { status: res.status });
      }

      const data = await res.json();

      // Evolution API v2 returns { messages: { total, pages, currentPage, records: [...] } }
      if (data?.messages?.records) {
        allRecords = allRecords.concat(data.messages.records);
        totalPages = data.messages.pages || 1;
      } else if (Array.isArray(data)) {
        // Fallback: direct array
        allRecords = data;
        break;
      } else {
        break;
      }

      currentPage++;
    } while (currentPage <= totalPages && currentPage <= MAX_PAGES);

    return NextResponse.json(allRecords);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
