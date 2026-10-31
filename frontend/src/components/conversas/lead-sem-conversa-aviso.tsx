import Link from "next/link";

/**
 * Aviso do deep-link /conversas?lead_id= quando o lead não tem conversa visível
 * (ex.: cliente importado do Bling que nunca falou no WhatsApp). Texto visível,
 * não tooltip: quem abre o link precisa saber na hora por que nada abriu.
 */
export function LeadSemConversaAviso({ leadId }: { leadId: string }) {
  return (
    <div
      role="status"
      data-testid="lead-sem-conversa"
      className="mx-3 my-2 rounded-[4px] border border-[#dedbd6] bg-white px-4 py-3 text-left"
    >
      <p className="text-[14px] font-medium text-[#111111]">Este lead não tem conversa no WhatsApp.</p>
      <Link
        href={`/leads?lead_id=${leadId}`}
        className="mt-1 inline-block text-[13px] text-[#111111] underline underline-offset-2"
      >
        Abrir ficha do lead
      </Link>
    </div>
  );
}
