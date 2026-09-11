"use client";

import { useEffect, useRef, useState } from "react";
import type { StageOption, StagesByPipeline } from "@/lib/deal-rows";

/**
 * Busca os stages de vários funis de uma vez.
 *
 * O painel do lead pode ter deals em funis diferentes, então precisa dos stages
 * de cada um. O cache por pipeline_id sobrevive à troca de conversa: dois leads
 * do mesmo funil não refazem o fetch.
 *
 * Não confundir com usePipelineStages (use-pipelines.ts), que serve UM funil
 * com realtime do Supabase. Este serve N funis por fetch, sem realtime.
 */
export function useStagesByPipeline(pipelineIds: string[]): {
  stagesByPipeline: StagesByPipeline;
  loading: boolean;
} {
  const cacheRef = useRef<StagesByPipeline>({});
  const [stagesByPipeline, setStagesByPipeline] = useState<StagesByPipeline>({});
  const [loading, setLoading] = useState(false);

  // Chave estável: o array de ids é recriado a cada render do pai, então
  // usá-lo direto como dependência dispararia o efeito para sempre.
  const key = [...pipelineIds].sort().join(",");

  useEffect(() => {
    const ids = key ? key.split(",") : [];
    const missing = ids.filter((id) => !cacheRef.current[id]);

    if (missing.length === 0) {
      setStagesByPipeline({ ...cacheRef.current });
      // Também zera aqui: um batch abortado pula o .finally abaixo, e sem este
      // reset o loading ficaria preso em true pelo resto da montagem.
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);

    Promise.all(
      missing.map((id) =>
        fetch(`/api/pipelines/${id}/stages`, { signal: controller.signal })
          // null (e não []) distingue falha de funil legitimamente vazio. Como
          // `missing` filtra por ausência no cache e [] é truthy, cachear a
          // falha deixaria o funil sem stages para sempre — e stageOptions
          // vazio desliga o dropdown de todos os deals dele, em silêncio.
          .then((r) => (r.ok ? r.json() : null))
          .then((data) => [id, Array.isArray(data) ? (data as StageOption[]) : null] as const)
          .catch(() => [id, null] as const)
      )
    )
      .then((entries) => {
        // Sem este guard, um fetch abortado gravaria no cache e o funil
        // ficaria permanentemente sem stages até um reload.
        if (controller.signal.aborted) return;
        for (const [id, stages] of entries) {
          if (stages !== null) cacheRef.current[id] = stages;
        }
        setStagesByPipeline({ ...cacheRef.current });
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [key]);

  return { stagesByPipeline, loading };
}
