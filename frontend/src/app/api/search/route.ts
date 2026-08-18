import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { getAllowedPipelineIds, PipelineAccessError } from "@/lib/supabase/pipeline-access";
import { parseSearchParams, limitForTab, offsetFor, startOfDayIso, endOfDayIso } from "@/lib/universal-search";

const MIN_QUERY_LEN = 2;
const EMPTY_RESULT = { data: [] as unknown[], count: 0 };
const EMPTY_RESPONSE = {
  leads: EMPTY_RESULT, deals: EMPTY_RESULT, sales: EMPTY_RESULT, conversations: EMPTY_RESULT,
};

interface RpcResult {
  data: Array<Record<string, unknown>> | null;
  error: { message: string } | null;
}

function shape(res: RpcResult) {
  const rows = res.data ?? [];
  const count = rows.length > 0 ? Number(rows[0].total_count ?? rows.length) : 0;
  return { data: rows, count };
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const params = parseSearchParams(searchParams);

  if (params.q.length < MIN_QUERY_LEN) {
    return NextResponse.json(EMPTY_RESPONSE);
  }

  const supabase = await getServiceSupabase();

  let allowedPipelineIds: string[] | null;
  try {
    allowedPipelineIds = await getAllowedPipelineIds(supabase);
  } catch (err) {
    if (err instanceof PipelineAccessError) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    throw err;
  }

  let allowedChannelIds: string[] | null;
  try {
    allowedChannelIds = await getAllowedChannelIds(supabase);
  } catch (err) {
    if (err instanceof ChannelAccessError) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    throw err;
  }

  const limit = limitForTab(params.tab);
  const offset = offsetFor(params.page, limit);
  const wantsAll = params.tab === "all";
  const dateAfter = params.dateFrom ? startOfDayIso(params.dateFrom) : null;
  const dateBefore = params.dateTo ? endOfDayIso(params.dateTo) : null;

  const noop: RpcResult = { data: [], error: null };

  const [leadsRes, dealsRes, salesRes, conversationsRes]: RpcResult[] = await Promise.all([
    wantsAll || params.tab === "leads"
      ? supabase.rpc("search_leads", {
          search_query: params.q,
          p_stage: params.leadStage,
          p_created_after: dateAfter,
          p_created_before: dateBefore,
          max_results: limit,
          p_offset: offset,
        })
      : Promise.resolve(noop),
    wantsAll || params.tab === "deals"
      ? supabase.rpc("search_deals", {
          search_query: params.q,
          pipeline_ids: allowedPipelineIds,
          p_pipeline_id: params.pipelineId,
          p_stage_id: params.stageId,
          p_created_after: dateAfter,
          p_created_before: dateBefore,
          max_results: limit,
          p_offset: offset,
        })
      : Promise.resolve(noop),
    wantsAll || params.tab === "sales"
      ? supabase.rpc("search_sales", {
          search_query: params.q,
          p_sold_after: dateAfter,
          p_sold_before: dateBefore,
          max_results: limit,
          p_offset: offset,
        })
      : Promise.resolve(noop),
    wantsAll || params.tab === "conversations"
      ? supabase.rpc("search_customer_messages", {
          search_query: params.q,
          channel_ids: allowedChannelIds,
          max_results: limit,
          docs_only: params.docsOnly,
          p_offset: offset,
        })
      : Promise.resolve(noop),
  ]);

  for (const res of [leadsRes, dealsRes, salesRes, conversationsRes]) {
    if (res.error) return NextResponse.json({ error: res.error.message }, { status: 500 });
  }

  return NextResponse.json({
    leads: shape(leadsRes),
    deals: shape(dealsRes),
    sales: shape(salesRes),
    conversations: shape(conversationsRes),
  });
}
