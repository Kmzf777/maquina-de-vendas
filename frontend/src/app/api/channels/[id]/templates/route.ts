import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

// ─── Internal Meta API types ──────────────────────────────────────────────────

interface MetaApiParam {
  param_name: string;
  example: string;
}

interface MetaApiComponent {
  type: string;
  text?: string;
  format?: string;
  example?: {
    body_text?: string[][];
    body_text_named_params?: MetaApiParam[];
    header_url?: string[];
  };
  buttons?: Array<{ type: string; text: string }>;
}

interface MetaApiTemplate {
  name: string;
  status: string;
  language: string;
  category: string;
  components: MetaApiComponent[];
}

// ─── Public types (consumed by frontend components) ───────────────────────────

export interface TemplateParam {
  index: number;      // 1-based
  paramName: string;  // "first_name" (named) | "1" "2" "3" (positional)
  example: string;
}

export interface TemplateHeader {
  type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";
  text?: string;
  example?: string;
}

export interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
  header: TemplateHeader | null;
  footer: string | null;
  buttons: { type: string; text: string }[];
}

// ─── Parsers ──────────────────────────────────────────────────────────────────

function parseParamsAndType(components: MetaApiComponent[]): {
  params: TemplateParam[];
  paramsType: "positional" | "named" | "none";
} {
  const body = components.find((c) => c.type === "BODY");
  if (!body) return { params: [], paramsType: "none" };

  // Named params (newer Meta format)
  if (body.example?.body_text_named_params?.length) {
    return {
      params: body.example.body_text_named_params.map((p, i) => ({
        index: i + 1,
        paramName: p.param_name,
        example: p.example,
      })),
      paramsType: "named",
    };
  }

  // Positional params via body_text examples
  if (body.example?.body_text?.[0]?.length) {
    return {
      params: body.example.body_text[0].map((ex, i) => ({
        index: i + 1,
        paramName: String(i + 1),
        example: ex,
      })),
      paramsType: "positional",
    };
  }

  // Fallback: count {{N}} occurrences in body text
  const matches = [...(body.text ?? "").matchAll(/\{\{(\d+)\}\}/g)];
  if (matches.length) {
    return {
      params: matches.map((m, i) => ({
        index: i + 1,
        paramName: m[1],
        example: "",
      })),
      paramsType: "positional",
    };
  }

  return { params: [], paramsType: "none" };
}

function parseHeader(components: MetaApiComponent[]): TemplateHeader | null {
  const header = components.find((c) => c.type === "HEADER");
  if (!header) return null;
  const fmt = header.format?.toUpperCase();
  if (fmt === "TEXT") return { type: "TEXT", text: header.text ?? "" };
  if (fmt === "IMAGE") return { type: "IMAGE", example: header.example?.header_url?.[0] };
  if (fmt === "VIDEO") return { type: "VIDEO", example: header.example?.header_url?.[0] };
  if (fmt === "DOCUMENT") return { type: "DOCUMENT", example: header.example?.header_url?.[0] };
  return null;
}

function parseBody(components: MetaApiComponent[]): string {
  return components.find((c) => c.type === "BODY")?.text ?? "";
}

function parseFooter(components: MetaApiComponent[]): string | null {
  return components.find((c) => c.type === "FOOTER")?.text ?? null;
}

function parseButtons(components: MetaApiComponent[]): { type: string; text: string }[] {
  return components.find((c) => c.type === "BUTTONS")?.buttons ?? [];
}

// ─── Route handlers ───────────────────────────────────────────────────────────

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
    return NextResponse.json(
      { error: "Canal sem access_token ou waba_id configurado" },
      { status: 400 }
    );
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
  const templates: MetaTemplate[] = (json.data as MetaApiTemplate[])
    .filter((t) => t.status === "APPROVED")
    .map((t) => {
      const { params, paramsType } = parseParamsAndType(t.components ?? []);
      return {
        name: t.name,
        language: t.language,
        category: (t.category ?? "").toLowerCase(),
        body: parseBody(t.components ?? []),
        params,
        paramsType,
        header: parseHeader(t.components ?? []),
        footer: parseFooter(t.components ?? []),
        buttons: parseButtons(t.components ?? []),
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));

  return NextResponse.json(templates);
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
