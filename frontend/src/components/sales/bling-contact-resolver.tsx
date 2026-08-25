"use client";

/**
 * Resolução de identidade do cliente — aparece quando `POST /api/bling/orders`
 * devolve 409.
 *
 * O backend nunca chuta o contato: sem um único match por CPF/CNPJ, quem decide
 * é o vendedor. Aqui ele confirma um candidato (`/api/bling/contacts/link`) ou
 * cadastra o cliente (`/api/bling/contacts`); nos dois casos o modal refaz o
 * pedido em seguida, com tudo que já estava digitado.
 *
 * A montagem e a validação do cadastro moram em `@/lib/bling-contact-form`.
 */

import { useState } from "react";
import { BuildingIcon, UserIcon } from "lucide-react";
import {
  blankContactForm,
  buildContactPayload,
  type ContactForm,
} from "@/lib/bling-contact-form";
import { formatDocument } from "@/lib/documento";

export interface BlingContactCandidate {
  id: number;
  nome: string;
  fantasia?: string | null;
  doc_digits?: string | null;
  email?: string | null;
  telefone_e164?: string | null;
  celular_e164?: string | null;
}

interface BlingContactResolverProps {
  leadId: string;
  status: "ambiguous" | "suggested" | "missing";
  reason?: string;
  candidates: BlingContactCandidate[];
  /** Pré-preenchimento do cadastro com o que o CRM já sabe do lead. */
  defaults?: Partial<ContactForm>;
  /** Contato resolvido — o modal reenvia o pedido. */
  onResolved: () => void;
  onCancel: () => void;
}

const label = "text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1";
const input =
  "w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none focus:ring-0";

const TITULO: Record<string, string> = {
  ambiguous: "Qual é o cliente no Bling?",
  suggested: "Este é o cliente no Bling?",
  missing: "Cadastrar o cliente no Bling",
};

const EXPLICACAO: Record<string, string> = {
  documento_duplicado:
    "Há mais de um contato com este CPF/CNPJ no Bling. Escolha em qual deles a venda deve ser lançada — depois vale a pena limpar a duplicata no ERP.",
  contato_ja_vinculado:
    "O contato encontrado já pertence a outro lead do CRM. Confirme só se for realmente o mesmo cliente.",
  telefone:
    "Encontramos pelo telefone, o que apenas sugere: o telefone do lead costuma ser o do comprador, e o contato do Bling é a empresa. Confirme antes de lançar.",
  email: "Encontramos pelo e-mail. Confirme antes de lançar o pedido.",
  sem_correspondencia:
    "Nenhum contato correspondente no Bling. Cadastre o cliente para lançar o pedido.",
};

export function BlingContactResolver({
  leadId,
  status,
  reason,
  candidates,
  defaults,
  onResolved,
  onCancel,
}: BlingContactResolverProps) {
  const [cadastrando, setCadastrando] = useState(status === "missing");
  const [form, setForm] = useState<ContactForm>(() => blankContactForm(defaults));
  const [tocado, setTocado] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const montado = buildContactPayload(form, leadId);
  const campo = (chave: keyof ContactForm) => (
    e: React.ChangeEvent<HTMLInputElement>,
  ) => setForm((atual) => ({ ...atual, [chave]: e.target.value }));

  async function confirmar(contactId: number) {
    setEnviando(true);
    setErro(null);
    const res = await fetch("/api/bling/contacts/link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lead_id: leadId, contact_id: contactId }),
    }).catch(() => null);

    if (!res || !res.ok) {
      const corpo = await res?.json().catch(() => ({}));
      setErro(
        corpo?.message ??
          corpo?.error ??
          "Não foi possível vincular este contato. Ele pode já pertencer a outro lead.",
      );
      setEnviando(false);
      return;
    }
    setEnviando(false);
    onResolved();
  }

  async function cadastrar() {
    setTocado(true);
    if (!montado.valid) return;
    setEnviando(true);
    setErro(null);
    const res = await fetch("/api/bling/contacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(montado.payload),
    }).catch(() => null);

    if (!res || !res.ok) {
      const corpo = await res?.json().catch(() => ({}));
      // 422/409 do Bling vêm com a mensagem original — é ela que diz o que fazer.
      setErro(
        [corpo?.message, corpo?.detail].filter(Boolean).join(" ") ||
          "Não foi possível cadastrar o cliente no Bling.",
      );
      setEnviando(false);
      return;
    }
    setEnviando(false);
    onResolved();
  }

  const erroNome = tocado ? montado.errors.nome : undefined;
  const erroDoc = tocado ? montado.errors.documento : undefined;
  const erroEmail = tocado ? montado.errors.email : undefined;

  return (
    <div className="space-y-4">
      <div className="border border-[#dedbd6] rounded-[8px] overflow-hidden">
        <div className="bg-[#faf9f6] border-b border-[#dedbd6] px-4 py-3">
          <p className="text-[14px] font-medium text-[#111111]">
            {cadastrando ? TITULO.missing : TITULO[status]}
          </p>
          <p className="mt-1 text-[12px] text-[#7b7b78]">
            {cadastrando
              ? "O pedido só é lançado depois que o cliente existe no Bling."
              : (EXPLICACAO[reason ?? ""] ??
                "Confirme o cliente no Bling para lançar o pedido.")}
          </p>
        </div>

        {!cadastrando && (
          <ul>
            {candidates.map((c) => (
              <li
                key={c.id}
                className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[#dedbd6] last:border-b-0"
              >
                <div className="min-w-0">
                  <p className="flex items-center gap-1.5 text-[14px] text-[#111111] truncate">
                    {(c.doc_digits ?? "").length === 14 ? (
                      <BuildingIcon className="size-3.5 shrink-0 text-[#7b7b78]" />
                    ) : (
                      <UserIcon className="size-3.5 shrink-0 text-[#7b7b78]" />
                    )}
                    <span className="truncate">{c.nome}</span>
                  </p>
                  {c.fantasia && (
                    <p className="text-[12px] text-[#7b7b78] truncate">{c.fantasia}</p>
                  )}
                  <p className="text-[11px] text-[#7b7b78] truncate">
                    {[
                      c.doc_digits ? formatDocument(c.doc_digits) : null,
                      c.celular_e164 ?? c.telefone_e164 ?? null,
                      c.email ?? null,
                    ]
                      .filter(Boolean)
                      .join(" · ") || "sem dados de contato"}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={enviando}
                  onClick={() => confirmar(c.id)}
                  className="shrink-0 px-3 py-1.5 text-[12px] font-medium text-white rounded-[4px] bg-[#1f9d57] hover:bg-[#1b8a4c] disabled:bg-[#7b7b78] transition-colors"
                >
                  É este cliente
                </button>
              </li>
            ))}
            {candidates.length === 0 && (
              <li className="px-4 py-3 text-[13px] text-[#7b7b78]">
                Nenhum candidato para confirmar.
              </li>
            )}
          </ul>
        )}

        {cadastrando && (
          <div className="p-4 space-y-3">
            <div>
              <label className={label}>Nome / Razão social *</label>
              <input
                value={form.nome}
                onChange={campo("nome")}
                placeholder="Nome como deve constar na nota"
                className={input}
              />
              {erroNome && (
                <p className="mt-1 text-[11px] text-[#c41c1c]">{erroNome}</p>
              )}
            </div>

            <div>
              <label className={label}>CPF / CNPJ *</label>
              <input
                value={form.documento}
                onChange={campo("documento")}
                inputMode="numeric"
                placeholder="Somente números"
                className={input}
              />
              <p className="mt-1 text-[11px] text-[#7b7b78]">
                O CPF/CNPJ é o que garante que o cliente não seja duplicado no Bling.
              </p>
              {erroDoc && <p className="mt-1 text-[11px] text-[#c41c1c]">{erroDoc}</p>}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={label}>E-mail *</label>
                {/* Exemplo no lugar de explicação: cabe na coluna estreita e já
                    mostra o formato que a validação espera. */}
                <input
                  value={form.email}
                  onChange={campo("email")}
                  type="email"
                  placeholder="cliente@empresa.com"
                  className={input}
                />
                {erroEmail && (
                  <p className="mt-1 text-[11px] text-[#c41c1c]">{erroEmail}</p>
                )}
              </div>
              <div>
                <label className={label}>Telefone</label>
                <input
                  value={form.telefone}
                  onChange={campo("telefone")}
                  inputMode="tel"
                  className={input}
                />
              </div>
            </div>

            <div className="p-3 bg-[#faf9f6] border border-[#dedbd6] rounded-[4px] space-y-3">
              <span className={label}>Endereço (opcional)</span>
              <div className="grid grid-cols-[110px_minmax(0,1fr)_80px] gap-2">
                <input
                  value={form.cep}
                  onChange={campo("cep")}
                  placeholder="CEP"
                  inputMode="numeric"
                  className={input}
                />
                <input
                  value={form.logradouro}
                  onChange={campo("logradouro")}
                  placeholder="Logradouro"
                  className={input}
                />
                <input
                  value={form.numero}
                  onChange={campo("numero")}
                  placeholder="Nº"
                  className={input}
                />
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_64px] gap-2">
                <input
                  value={form.bairro}
                  onChange={campo("bairro")}
                  placeholder="Bairro"
                  className={input}
                />
                <input
                  value={form.municipio}
                  onChange={campo("municipio")}
                  placeholder="Município"
                  className={input}
                />
                <input
                  value={form.uf}
                  onChange={campo("uf")}
                  placeholder="UF"
                  maxLength={2}
                  className={`${input} uppercase`}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {erro && <p className="text-[12px] text-[#c41c1c]">{erro}</p>}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 min-w-[120px] py-2 text-[13px] text-[#7b7b78] border border-[#dedbd6] rounded-[4px] hover:bg-[#faf9f6] transition-colors"
        >
          Voltar ao pedido
        </button>

        {!cadastrando && status === "suggested" && (
          <button
            type="button"
            onClick={() => {
              setCadastrando(true);
              setErro(null);
            }}
            className="flex-1 min-w-[180px] py-2 text-[13px] text-[#111111] border border-[#dedbd6] rounded-[4px] hover:bg-[#faf9f6] transition-colors"
          >
            Nenhum destes — cadastrar
          </button>
        )}

        {cadastrando && (
          <button
            type="button"
            onClick={cadastrar}
            disabled={enviando}
            className="flex-1 min-w-[180px] py-2 text-[13px] font-medium text-white rounded-[4px] bg-[#1f9d57] hover:bg-[#1b8a4c] disabled:bg-[#7b7b78] transition-colors"
          >
            {enviando ? "Cadastrando..." : "Cadastrar e lançar o pedido"}
          </button>
        )}
      </div>
    </div>
  );
}
