// frontend/src/app/api/conversations/[id]/followup/route.ts
import { NextResponse, type NextRequest } from "next/server";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: conversationId } = await params;
  const body = await request.json();

  const backendUrl = (
    process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000"
  ).replace(/\/+$/, "");

  try {
    const res = await fetch(
      `${backendUrl}/api/conversations/${conversationId}/followup`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: body.enabled }),
        signal: AbortSignal.timeout(10_000),
      }
    );

    if (!res.ok) {
      const text = await res.text();
      return NextResponse.json(
        { error: text },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Request failed";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
