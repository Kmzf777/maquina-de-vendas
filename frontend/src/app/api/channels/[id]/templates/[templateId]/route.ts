import { NextResponse } from "next/server";

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string; templateId: string }> }
) {
  const { id, templateId } = await params;
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

  const res = await fetch(`${backendUrl}/api/channels/${id}/templates/${templateId}`, {
    method: "DELETE",
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
