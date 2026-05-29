import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = (
  process.env.NEXT_PUBLIC_FASTAPI_URL || "http://api:8000"
).replace(/\/+$/, "");

export async function GET() {
  const res = await fetch(`${FASTAPI_URL}/api/lp-webhook/settings`);
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function PUT(req: NextRequest) {
  const body = await req.text();
  const res = await fetch(`${FASTAPI_URL}/api/lp-webhook/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
