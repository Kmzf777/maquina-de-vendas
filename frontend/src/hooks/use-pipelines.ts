"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Pipeline, PipelineStage } from "@/lib/types";

export function usePipelines() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = useMemo(() => createClient(), []);

  const fetchPipelines = useCallback(async () => {
    const { data } = await supabase
      .from("pipelines")
      .select("*")
      .order("order_index", { ascending: true });
    if (data) setPipelines(data);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    fetchPipelines();
    const channel = supabase
      .channel("pipelines-changes")
      .on("postgres_changes", { event: "*", schema: "public", table: "pipelines" }, fetchPipelines)
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchPipelines, supabase]);

  return { pipelines, loading, refetch: fetchPipelines };
}

export function usePipelineStages(pipelineId: string | null) {
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const supabase = useMemo(() => createClient(), []);

  const fetchStages = useCallback(async () => {
    if (!pipelineId) { setStages([]); return; }
    const { data } = await supabase
      .from("pipeline_stages")
      .select("*")
      .eq("pipeline_id", pipelineId)
      .order("order_index", { ascending: true });
    if (data) setStages(data);
  }, [pipelineId, supabase]);

  useEffect(() => {
    fetchStages();
    if (!pipelineId) return;
    const channel = supabase
      .channel(`pipeline-stages-${pipelineId}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "pipeline_stages" }, fetchStages)
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchStages, pipelineId, supabase]);

  return { stages, refetch: fetchStages };
}
