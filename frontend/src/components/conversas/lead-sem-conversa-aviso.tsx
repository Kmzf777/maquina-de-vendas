"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

/**
 * Aviso do deep-link /conversas?lead_id= quando o lead não tem conversa visível
 * (ex.: cliente importado do Bling que nunca falou no WhatsApp). Texto visível,
 * não tooltip: quem abre o link precisa saber na hora por que nada abriu.
 * Com telefone utilizável oferece "Iniciar conversa" (cartão 70d844a6); o critério
 * de telefone é o da rota iniciar-conversa, então o aviso pergunta a ela.
 */
export function LeadSemConversaAviso({ leadId, onIniciar }: { leadId: string; onIniciar: () => void }) {
  // undefined = carregando ou GET falhou (sem botão); null = sem telefone.
  const [telefone, setTelefone] = useState<{ leadId: string; valor: string | null } | undefined>(undefined);

  useEffect(() => {
    let ativo = true;
    fetch(`/api/leads/${leadId}/iniciar-conversa`)
      .then(async (r) => {
        if (!r.ok) return;
        const d = await r.json();
        // Resposta sem o campo não afirma nada sobre o telefone: fica sem botão.
        if (!ativo || !d || typeof d !== "object" || !("telefone" in d)) return;
        setTelefone({ leadId, valor: typeof d.telefone === "string" && d.telefone ? d.telefone : null });
      })
      .catch(() => {});
    return () => {
      ativo = false;
    };
  }, [leadId]);

  const atual = telefone?.leadId === leadId ? telefone : undefined;
  const semTelefone = atual?.valor === null;

  return (
    <div
      role="status"
      data-testid="lead-sem-conversa"
      className="mx-3 my-2 rounded-[4px] border border-[#dedbd6] bg-white px-4 py-3 text-left"
    >
      <p className="text-[14px] font-medium text-[#111111]">
        {semTelefone ? "Este lead não tem telefone para WhatsApp." : "Este lead não tem conversa no WhatsApp."}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {atual?.valor && (
          <button
            type="button"
            onClick={onIniciar}
            className="bg-[#111111] text-white text-[13px] px-4 py-2 rounded-[4px] transition-transform hover:scale-110 active:scale-[0.85]"
          >
            Iniciar conversa
          </button>
        )}
        <Link
          href={`/leads?lead_id=${leadId}`}
          className="inline-block text-[13px] text-[#111111] underline underline-offset-2"
        >
          Abrir ficha do lead
        </Link>
      </div>
    </div>
  );
}
