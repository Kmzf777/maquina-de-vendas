"use client";

// Atribuição manual de campanha (call de 01/10, P2). Um admin diz de qual campanha o lead veio
// quando o rastreio não diz (lead CTWA de antes de 21/08, indicação, Google sem gclid) — e o
// /trafego passa a contá-lo lá, acima do anúncio e das UTMs. <select> nativo com <optgroup> por
// canal: o Radix Select não roda no jsdom e ~30 campanhas não pedem busca.

import { useEffect, useState } from "react";

export type CanalCampanha = "meta" | "google";

export type CampanhaComGasto = {
  canal: CanalCampanha;
  campanha_id: string;
  campanha_nome: string;
  investimento: number;
};

export type AtribuicaoManual = {
  atribuicao_manual: boolean;
  campanha_manual_canal: CanalCampanha | null;
  campanha_manual_id: string | null;
  campanha_manual_nome: string | null;
};

export const CANAL_LABEL: Record<CanalCampanha, string> = { meta: "Meta Ads", google: "Google Ads" };
const CANAIS: CanalCampanha[] = ["meta", "google"];

const valorDe = (canal: string | null, id: string | null) => (canal && id ? `${canal}:${id}` : "");

type Resposta = Partial<AtribuicaoManual> & { detail?: unknown };

export function CampaignAttribution({
  leadId,
  atual,
  onChange,
}: {
  leadId: string;
  atual: AtribuicaoManual;
  onChange?: (a: AtribuicaoManual) => void;
}) {
  const [campanhas, setCampanhas] = useState<CampanhaComGasto[] | null>(null);
  const [erroLista, setErroLista] = useState<string | null>(null);
  const [escolha, setEscolha] = useState(valorDe(atual.campanha_manual_canal, atual.campanha_manual_id));
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/traffic/campanhas", { signal: ctrl.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error("failed");
        return (await r.json()) as { campanhas?: CampanhaComGasto[] };
      })
      .then((d) => setCampanhas(d.campanhas ?? []))
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setErroLista("Não foi possível carregar as campanhas.");
      });
    return () => ctrl.abort();
  }, []);

  const salvar = async (body: Record<string, unknown>) => {
    setSalvando(true);
    setErro(null);
    try {
      const r = await fetch(`/api/traffic/leads/${leadId}/campanha`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = (await r.json().catch(() => ({}))) as Resposta;
      if (!r.ok) {
        throw new Error(typeof d.detail === "string" ? d.detail : "Não foi possível salvar a atribuição.");
      }
      const nova: AtribuicaoManual = {
        atribuicao_manual: Boolean(d.atribuicao_manual),
        campanha_manual_canal: d.campanha_manual_canal ?? null,
        campanha_manual_id: d.campanha_manual_id ?? null,
        campanha_manual_nome: d.campanha_manual_nome ?? null,
      };
      setEscolha(valorDe(nova.campanha_manual_canal, nova.campanha_manual_id));
      onChange?.(nova);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar a atribuição.");
    } finally {
      setSalvando(false);
    }
  };

  const atribuir = () => {
    const c = campanhas?.find((x) => valorDe(x.canal, x.campanha_id) === escolha);
    if (c) void salvar({ canal: c.canal, campanha_id: c.campanha_id, campanha_nome: c.campanha_nome });
  };

  const valorAtual = valorDe(atual.campanha_manual_canal, atual.campanha_manual_id);
  const lista = campanhas ?? [];
  const grupos = CANAIS.map((canal) => ({ canal, itens: lista.filter((c) => c.canal === canal) }))
    .filter((g) => g.itens.length > 0);
  // Campanha atribuída que saiu da janela de 120 dias continua aparecendo no select.
  const atualForaDaLista =
    atual.atribuicao_manual && valorAtual !== "" && !lista.some((c) => valorDe(c.canal, c.campanha_id) === valorAtual);

  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Campanha de origem</div>
        {atual.atribuicao_manual && (
          <span className="inline-flex items-center text-[10px] font-medium uppercase tracking-[0.4px] px-1.5 py-px rounded-[3px] border bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]">
            manual
          </span>
        )}
      </div>

      {atual.atribuicao_manual && atual.campanha_manual_canal && (
        <div className="text-[13px] text-[#111111] mb-2.5">
          {CANAL_LABEL[atual.campanha_manual_canal]} · {atual.campanha_manual_nome ?? atual.campanha_manual_id}
        </div>
      )}

      {erroLista ? (
        <div className="text-[12px] text-[#c41c1c]">{erroLista}</div>
      ) : (
        <div className="flex items-center gap-2">
          <select
            aria-label="Campanha"
            value={escolha}
            onChange={(e) => setEscolha(e.target.value)}
            disabled={campanhas === null || salvando}
            className="flex-1 min-w-0 text-[13px] text-[#111111] bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1.5 focus:outline-none focus-visible:ring-1 focus-visible:ring-[#111111]"
          >
            <option value="">{campanhas === null ? "Carregando campanhas…" : "Escolher campanha…"}</option>
            {atualForaDaLista && (
              <option value={valorAtual}>{atual.campanha_manual_nome ?? atual.campanha_manual_id}</option>
            )}
            {grupos.map((g) => (
              <optgroup key={g.canal} label={CANAL_LABEL[g.canal]}>
                {g.itens.map((c) => (
                  <option key={valorDe(c.canal, c.campanha_id)} value={valorDe(c.canal, c.campanha_id)}>
                    {c.campanha_nome}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <button
            type="button"
            onClick={atribuir}
            disabled={!escolha || escolha === valorAtual || salvando}
            className="text-[13px] text-white bg-[#111111] hover:bg-[#000000] disabled:opacity-40 px-3 py-1.5 rounded-[4px] transition-colors whitespace-nowrap"
          >
            Atribuir
          </button>
        </div>
      )}

      {atual.atribuicao_manual && (
        <button
          type="button"
          onClick={() => void salvar({ remover: true })}
          disabled={salvando}
          className="mt-2 text-[12px] text-[#7b7b78] hover:text-[#c41c1c] disabled:opacity-40 transition-colors"
        >
          Remover atribuição
        </button>
      )}

      {erro && <div className="mt-2 text-[12px] text-[#c41c1c]">{erro}</div>}

      <p className="mt-2 text-[11px] text-[#7b7b78] leading-snug">
        Vale acima do anúncio e das UTMs. O relatório recalcula ao recarregar a página.
      </p>
    </div>
  );
}
