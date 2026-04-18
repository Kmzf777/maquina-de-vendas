import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

interface MetaParam {
  param_name: string;
  example: string;
}

interface MetaComponent {
  type: string;
  text?: string;
  example?: {
    body_text_named_params?: MetaParam[];
  };
  buttons?: Array<{ type: string; text: string }>;
}

interface MetaTemplate {
  name: string;
  status: string;
  language: string;
  category: string;
  components: MetaComponent[];
}

function extractParams(components: MetaComponent[]): string[] {
  const body = components.find((c) => c.type === "BODY");
  if (!body?.example?.body_text_named_params) return [];
  return body.example.body_text_named_params.map((p) => p.param_name);
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data: channel, error } = await supabase
    .from("channels")
    .select("provider_config")
    .eq("id", id)
    .single();

  if (error || !channel) {
    return NextResponse.json({ error: "Canal não encontrado" }, { status: 404 });
  }

  const config = channel.provider_config as Record<string, string>;
  const { access_token, waba_id, api_version } = config;

  if (!access_token || !waba_id) {
    return NextResponse.json({ error: "Canal sem access_token ou waba_id configurado" }, { status: 400 });
  }

  const version = api_version || "v20.0";
  const url = `https://graph.facebook.com/${version}/${waba_id}/message_templates?fields=name,status,language,category,components&limit=200`;

  const metaRes = await fetch(url, {
    headers: { Authorization: `Bearer ${access_token}` },
  });

  if (!metaRes.ok) {
    const err = await metaRes.text();
    return NextResponse.json({ error: `Meta API error: ${err}` }, { status: metaRes.status });
  }

  const json = await metaRes.json();
  const approved = (json.data as MetaTemplate[])
    .filter((t) => t.status === "APPROVED")
    .map((t) => ({
      name: t.name,
      language: t.language,
      category: (t.category || "").toLowerCase(),
      params: extractParams(t.components || []),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));

  return NextResponse.json(approved);
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");

  const res = await fetch(`${backendUrl}/api/channels/${id}/templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
