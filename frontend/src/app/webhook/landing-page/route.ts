import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = (
  process.env.NEXT_PUBLIC_FASTAPI_URL || "http://api:8000"
).replace(/\/+$/, "");

export async function POST(req: NextRequest) {
  const body = await req.text();
  const res = await fetch(`${FASTAPI_URL}/webhook/landing-page`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const data = await res.json();
  return NextResponse.json(data, { status: 200 });
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 200,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}
