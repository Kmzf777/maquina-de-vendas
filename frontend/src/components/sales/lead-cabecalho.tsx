"use client";

/**
 * Topo do lead na conversa (estilo RD Station, pedido do dono na call de
 * 01/10): telefone com copiar, e-mail e CNPJ/CPF editáveis e "Já é cliente?".
 *
 * E-mail e CNPJ vêm do lead da conversa e gravam pelo mesmo `onSaveField` do
 * Perfil (PATCH com atualização otimista no `contact-detail`). O "Já é
 * cliente?" é lido por id (`useLeadCliente`): o select das conversas não traz
 * essas colunas.
 */
import { useState } from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import { EditableField } from "@/components/conversas/editable-field";
import { docDigits, formatDocument } from "@/lib/documento";
import { JaEraClienteToggle } from "./ja-era-cliente-toggle";
import { salvarJaEraCliente, useLeadCliente, type LeadCliente } from "./lead-cliente";

interface LeadCabecalhoProps {
  lead: { id: string; phone: string | null; email: string | null; cnpj: string | null };
  currentUserEmail?: string;
  onSaveField: (field: string, value: string) => void | Promise<void>;
}

export function LeadCabecalho({ lead, currentUserEmail, onSaveField }: LeadCabecalhoProps) {
  const { lead: cliente, atualizar } = useLeadCliente(lead.id);
  const [copiado, setCopiado] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const telefone = lead.phone && !lead.phone.startsWith("bling-") ? lead.phone : null;

  async function copiar() {
    if (!telefone) return;
    try {
      await navigator.clipboard.writeText(telefone);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1500);
    } catch {
      setErro("Não foi possível copiar o telefone.");
    }
  }

  async function responder(valor: boolean) {
    const anterior: Partial<LeadCliente> = {
      ja_era_cliente: cliente?.ja_era_cliente,
      ja_era_cliente_fonte: cliente?.ja_era_cliente_fonte,
    };
    setSalvando(true);
    setErro(null);
    atualizar({ ja_era_cliente: valor, ja_era_cliente_fonte: "vendedor" });
    try {
      await salvarJaEraCliente(lead.id, valor, currentUserEmail);
    } catch (e) {
      atualizar(anterior);
      setErro(e instanceof Error ? e.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="px-4 py-3 border-b border-[#dedbd6] space-y-2 flex-shrink-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Telefone</span>
        <span className="flex items-center gap-1 min-w-0">
          <span className="text-[13px] text-[#111111] truncate tabular-nums">{telefone ?? "—"}</span>
          {telefone && (
            <button
              type="button"
              onClick={copiar}
              aria-label="Copiar telefone"
              title="Copiar telefone"
              className="w-6 h-6 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 hover:text-[#111111] transition-colors"
            >
              {copiado ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
            </button>
          )}
        </span>
      </div>
      <EditableField
        label="E-mail"
        value={lead.email}
        onSave={(v) => onSaveField("email", v)}
        placeholder="email@exemplo.com"
      />
      <EditableField
        label="CNPJ / CPF"
        value={lead.cnpj ? formatDocument(lead.cnpj) : null}
        // Grava só os dígitos: é a forma que o Bling e o P1 usam para casar
        // o documento (`doc_digits`). Com máscara, a busca nunca achava.
        onSave={(v) => onSaveField("cnpj", docDigits(v) ?? "")}
        placeholder="Digite o CNPJ ou CPF"
      />
      {/* `undefined` = coluna inexistente (migração do P0 não aplicada) ou
          lead ainda carregando: não há o que mostrar nem onde gravar. */}
      {cliente && cliente.ja_era_cliente !== undefined && (
        <JaEraClienteToggle
          valor={cliente.ja_era_cliente}
          fonte={cliente.ja_era_cliente_fonte}
          onEscolher={responder}
          desabilitado={salvando}
        />
      )}
      {erro && <p className="text-[11px] text-[#c41c1c]">{erro}</p>}
    </div>
  );
}
