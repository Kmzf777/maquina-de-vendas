import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

// ─── Meta API types ────────────────────────────────────────────────────────────

interface MetaTemplateItem {
  id: string;
  name: string;
  status: string;
  language: string;
  category: string;
  components: unknown[];
}

interface MetaPageResponse {
  data: MetaTemplateItem[];
  paging?: { next?: string };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function fetchAllMetaTemplates(
  wabaId: string,
  accessToken: string,
  version: string
): Promise<MetaTemplateItem[]> {
  const all: MetaTemplateItem[] = [];
  let url: string | null =
    `https://graph.facebook.com/${version}/${wabaId}/message_templates` +
    `?fields=name,status,language,category,components&limit=200`;

  while (url) {
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(`Meta API ${res.status}: ${err}`);
    }
    const json: MetaPageResponse = await res.json();
    all.push(...(json.data ?? []));
    url = json.paging?.next ?? null;
  }

  return all;
}

// ─── Route handler ────────────────────────────────────────────────────────────

export async function POST(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");

  if (!channelId) {
    return NextResponse.json({ error: "channel_id is required" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  // 1. Load and validate channel
  const { data: channel, error: channelError } = await supabase
    .from("channels")
    .select("id, provider, is_active, provider_config")
    .eq("id", channelId)
    .single();

  if (channelError || !channel) {
    return NextResponse.json({ error: "Channel not found" }, { status: 400 });
  }

  if (channel.provider !== "meta_cloud" || !channel.is_active) {
    return NextResponse.json(
      { error: "Channel is not an active meta_cloud channel" },
      { status: 400 }
    );
  }

  const config = channel.provider_config as Record<string, string>;
  const { access_token, waba_id, api_version } = config;

  if (!access_token || !waba_id) {
    return NextResponse.json(
      { error: "Channel missing access_token or waba_id" },
      { status: 400 }
    );
  }

  // 2. Paginated fetch from Meta (abort early on any page failure)
  let metaTemplates: MetaTemplateItem[];
  try {
    metaTemplates = await fetchAllMetaTemplates(
      waba_id,
      access_token,
      api_version || "v20.0"
    );
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Meta API fetch failed" },
      { status: 502 }
    );
  }

  // 3. Load existing local templates for this channel
  const { data: existingRows } = await supabase
    .from("message_templates")
    .select("id, name, language, meta_template_id")
    .eq("channel_id", channelId);

  const existingMap = new Map(
    (existingRows ?? []).map((r) => [`${r.name}::${r.language}`, r])
  );

  // 4. Split: new templates to INSERT vs existing to UPDATE
  const toInsert: Record<string, unknown>[] = [];
  const toUpdate: { id: string; data: Record<string, unknown> }[] = [];

  for (const t of metaTemplates) {
    const key = `${t.name}::${t.language}`;
    const sharedFields = {
      status: t.status.toLowerCase(),
      category: (t.category || "utility").toLowerCase(),
      language: t.language,
      components: t.components ?? [],
      meta_template_id: t.id,
    };

    if (existingMap.has(key)) {
      toUpdate.push({ id: existingMap.get(key)!.id, data: sharedFields });
    } else {
      toInsert.push({
        channel_id: channelId,
        name: t.name,
        requested_category: (t.category || "utility").toLowerCase(),
        ...sharedFields,
      });
    }
  }

  // 5. Insert new templates
  if (toInsert.length > 0) {
    const { error: insertError } = await supabase
      .from("message_templates")
      .insert(toInsert);
    if (insertError) {
      return NextResponse.json({ error: insertError.message }, { status: 500 });
    }
  }

  // 6. Update existing templates (preserves requested_category)
  for (const { id, data } of toUpdate) {
    await supabase.from("message_templates").update(data).eq("id", id);
  }

  // 7. Ghost cleanup: mark as cancelled any local template not returned by Meta
  //    Only runs after a full successful fetch (metaTemplates is complete at this point)
  const fetchedMetaIds = new Set(metaTemplates.map((t) => t.id).filter(Boolean));
  const ghostIds = (existingRows ?? [])
    .filter((r) => r.meta_template_id && !fetchedMetaIds.has(r.meta_template_id))
    .map((r) => r.id);

  if (ghostIds.length > 0) {
    await supabase
      .from("message_templates")
      .update({ status: "cancelled" })
      .in("id", ghostIds);
  }

  return NextResponse.json({ synced: metaTemplates.length });
}
