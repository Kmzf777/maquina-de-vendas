import { NextRequest } from "next/server";

const FASTAPI_URL = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://api:8000").replace(/\/+$/, "");

type Params = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const { searchParams } = new URL(request.url);
  const phone = searchParams.get("phone") ?? "";
  const skipDelays = searchParams.get("skip_delays") ?? "true";

  const backendUrl = `${FASTAPI_URL}/api/automation/campaigns/${id}/test?phone=${encodeURIComponent(phone)}&skip_delays=${skipDelays}`;

  const response = await fetch(backendUrl, {
    headers: { Accept: "text/event-stream" },
  });

  if (!response.ok) {
    return new Response(
      JSON.stringify({ error: `Backend returned ${response.status}` }),
      { status: response.status, headers: { "Content-Type": "application/json" } }
    );
  }

  if (!response.body) {
    return new Response(JSON.stringify({ error: "Backend SSE stream unavailable" }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(response.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
