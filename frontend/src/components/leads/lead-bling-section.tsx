"use client";

/**
 * Vínculo do lead com o contato no Bling — prima de
 * `@/components/sales/bling-contact-resolver.tsx` (mesmo vocabulário visual),
 * mas vive na tela de leads em vez de aparecer só quando uma venda esbarra em
 * um 409.
 *
 * Vinculado: mostra os dados do contato (buscados no espelho local) e um botão
 * para desvincular. Não vinculado: busca com debounce no espelho e um botão
 * "Vincular" por resultado.
 *
 * `GET /api/bling/contacts/search` só filtra por nome/fantasia/doc_digits — não
 * existe filtro por id. Para achar os dados do contato já vinculado, a busca é
 * feita pelo CNPJ do lead (quando o CRM tem um) e o resultado é filtrado pelo
 * id no cliente, como o espelho permite. Sem CNPJ no lead (vínculo feito por
 * telefone/e-mail/confirmação manual), não há como recuperar os dados — mostra
 * só o id com o link para o Bling. Um `GET /api/bling/contacts/{id}` (ou um
 * filtro por id no `/search` existente) resolveria isso de vez; ver relatório.
 */

import { useEffect, useState } from "react";
import { debounce } from "@/lib/debounce";
import { formatDocument } from "@/lib/documento";
import { blingContactUrl, formatBlingAddress, type BlingAddress } from "@/lib/bling-contact-display";

export interface BlingContactSummary {
  id: number;
  nome: string;
  fantasia?: string | null;
  doc_digits?: string | null;
  telefone_e164?: string | null;
  celular_e164?: string | null;
  email?: string | null;
  situacao?: string | null;
  endereco?: BlingAddress | string | null;
}

interface LeadBlingSectionProps {
  leadId: string;
  blingContactId: number | null;
  /** CNPJ/CPF do lead, quando existir — usado só para achar os dados do
   *  contato já vinculado (ver nota acima). Nunca envolvido no fluxo de
   *  vincular/desvincular em si. */
  leadDocument?: string | null;
  onChanged: () => void;
}

const sectionLabel = "text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-3";
const input =
  "w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none";
const btnGhost =
  "bg-white border border-[#dedbd6] text-[#111111] px-3 py-1.5 rounded-[4px] text-[12px] hover:bg-[#f4f2ee] transition-colors disabled:opacity-40 disabled:cursor-not-allowed";

async function searchContacts(q: string): Promise<BlingContactSummary[]> {
  const res = await fetch(`/api/bling/contacts/search?q=${encodeURIComponent(q)}&limit=20`, {
    cache: "no-store",
  });
  const body = await res.json().catch(() => ({}));
  return (body?.data ?? []) as BlingContactSummary[];
}

export function LeadBlingSection({ leadId, blingContactId, leadDocument, onChanged }: LeadBlingSectionProps) {
  // --- Contato já vinculado ------------------------------------------------
  const [contact, setContact] = useState<BlingContactSummary | null>(null);
  const [loadingContact, setLoadingContact] = useState(false);
  const [contactNotFound, setContactNotFound] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    setContact(null);
    setContactNotFound(false);
    setActionError(null);
    if (!blingContactId) return;

    let cancelled = false;
    setLoadingContact(true);
    const termo = (leadDocument || "").replace(/\D/g, "");
    searchContacts(termo)
      .then((results) => {
        if (cancelled) return;
        const found = results.find((c) => c.id === blingContactId);
        if (found) setContact(found);
        else setContactNotFound(true);
      })
      .catch(() => {
        if (!cancelled) setContactNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setLoadingContact(false);
      });
    return () => {
      cancelled = true;
    };
  }, [blingContactId, leadDocument]);

  async function handleUnlink() {
    setUnlinking(true);
    setActionError(null);
    try {
      const res = await fetch("/api/bling/contacts/unlink", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lead_id: leadId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionError(body?.error ?? "Não foi possível desvincular este contato.");
        return;
      }
      onChanged();
    } catch {
      setActionError("Backend inacessível.");
    } finally {
      setUnlinking(false);
    }
  }

  // --- Busca para vincular --------------------------------------------------
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<BlingContactSummary[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [linkingId, setLinkingId] = useState<number | null>(null);

  useEffect(() => {
    if (blingContactId) return;
    const termo = query.trim();
    if (termo.length < 2) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    setSearchError(null);
    const buscar = debounce(() => {
      searchContacts(termo)
        .then((data) => setResults(data))
        .catch(() => setSearchError("Backend inacessível."))
        .finally(() => setSearching(false));
    }, 300);
    buscar();
    return () => buscar.cancel();
  }, [query, blingContactId]);

  async function handleLink(contactId: number) {
    setLinkingId(contactId);
    setActionError(null);
    try {
      const res = await fetch("/api/bling/contacts/link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lead_id: leadId, contact_id: contactId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionError(body?.message ?? body?.error ?? "Não foi possível vincular este contato.");
        return;
      }
      setQuery("");
      setResults([]);
      onChanged();
    } catch {
      setActionError("Backend inacessível.");
    } finally {
      setLinkingId(null);
    }
  }

  // --- Render ----------------------------------------------------------------

  if (blingContactId) {
    const endereco = contact ? formatBlingAddress(contact.endereco) : "";
    const telefone = contact?.celular_e164 ?? contact?.telefone_e164 ?? null;
    return (
      <div>
        <div className="flex items-center justify-between mb-3">
          <p className={sectionLabel + " mb-0"}>Contato no Bling</p>
          <span
            className="text-[10px] font-semibold px-2 py-0.5 rounded-[4px]"
            style={{ background: "#d1fae5", color: "#059669" }}
          >
            VINCULADO
          </span>
        </div>

        {loadingContact && (
          <p className="text-[13px] text-[#7b7b78]">Carregando dados do contato…</p>
        )}

        {!loadingContact && contact && (
          <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] p-3 space-y-1.5">
            <p className="text-[14px] font-medium text-[#111111]">{contact.nome}</p>
            {contact.fantasia && <p className="text-[13px] text-[#7b7b78]">{contact.fantasia}</p>}
            <p className="text-[12px] text-[#7b7b78]">
              {[
                contact.doc_digits ? formatDocument(contact.doc_digits) : null,
                telefone,
                contact.email,
              ]
                .filter(Boolean)
                .join(" · ") || "sem dados de contato"}
            </p>
            {endereco && <p className="text-[12px] text-[#7b7b78]">{endereco}</p>}
          </div>
        )}

        {!loadingContact && !contact && contactNotFound && (
          <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] p-3">
            <p className="text-[13px] text-[#111111]">Contato #{blingContactId}</p>
            <p className="text-[12px] text-[#7b7b78] mt-1">
              Não foi possível carregar os dados deste contato pela busca do espelho. Confira
              diretamente no Bling.
            </p>
          </div>
        )}

        <div className="flex items-center justify-between mt-3">
          <a
            href={blingContactUrl(blingContactId)}
            target="_blank"
            rel="noreferrer"
            className="text-[12px] text-[#111111] hover:underline"
          >
            Abrir no Bling ↗
          </a>
          <button type="button" onClick={handleUnlink} disabled={unlinking} className={btnGhost}>
            {unlinking ? "Desvinculando…" : "Desvincular"}
          </button>
        </div>

        {actionError && <p className="text-[12px] text-red-600 mt-2">{actionError}</p>}
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className={sectionLabel + " mb-0"}>Contato no Bling</p>
        <span className="text-[10px] font-medium px-2 py-0.5 rounded-[4px] border border-[#dedbd6] text-[#7b7b78]">
          NÃO VINCULADO
        </span>
      </div>

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Buscar por nome, fantasia ou CNPJ/CPF…"
        className={input}
      />

      {searchError && <p className="text-[12px] text-red-600 mt-2">{searchError}</p>}
      {actionError && <p className="text-[12px] text-red-600 mt-2">{actionError}</p>}

      {searching && <p className="text-[12px] text-[#7b7b78] mt-2">Buscando…</p>}

      {!searching && query.trim().length >= 2 && results.length === 0 && !searchError && (
        <p className="text-[12px] text-[#7b7b78] mt-2">Nenhum contato encontrado no espelho.</p>
      )}

      {results.length > 0 && (
        <ul className="mt-2 border border-[#dedbd6] rounded-[6px] overflow-hidden">
          {results.map((c) => (
            <li
              key={c.id}
              className="flex items-center justify-between gap-3 px-3 py-2.5 border-b border-[#dedbd6] last:border-b-0 bg-white"
            >
              <div className="min-w-0">
                <p className="text-[13px] text-[#111111] truncate">{c.nome}</p>
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
                disabled={linkingId !== null}
                onClick={() => handleLink(c.id)}
                className={btnGhost + " shrink-0"}
              >
                {linkingId === c.id ? "Vinculando…" : "Vincular"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
