# P4 — Tela de venda e cabeçalho do lead — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Nesta sessão: execução inline com superpowers:test-driven-development, **sem subagentes**.

**Goal:** O vendedor registra venda/orçamento pela conversa sem abrir outra aba: o cadastro do
Bling nasce preenchido, o painel não esconde o chat, o topo do lead mostra telefone/e-mail/CNPJ e
"Já é cliente?", a venda exige essa resposta quando o sistema não sabe, os kits aparecem no topo do
catálogo e o seletor de lead busca no servidor.

**Architecture:** Toda lógica nova mora em arquivos pequenos e testáveis em
`frontend/src/components/sales/` (pasta do P4): `lead-cliente.ts` (busca do lead por id + regras
do "Já é cliente?"), `kits.ts`, `lead-picker.tsx`, `painel-lateral.tsx`,
`ja-era-cliente-toggle.tsx`, `lead-cabecalho.tsx`. Os modais e o `contact-detail.tsx` só passam a
usá-los. A leitura do lead por id é feita pelo client Supabase do browser (RLS
`leads_select_authenticated`, padrão de `use-realtime-leads`/`lead-selector`), porque não existe
`GET /api/leads/[id]` e a rota não é do P4. A gravação vai pelo `PATCH /api/leads/{id}` existente.

**Tech Stack:** Next.js 16 App Router (client components), Radix (`radix-ui`) via shadcn
(`Sheet`, `Popover`), vitest 2 + @testing-library/react (jsdom por docblock), Supabase JS.

---

## Regras (do plano mestre — obrigatórias)

- Todo comando pesado com `flock /root/crm-wt/_heavy.lock`. Sem `next build`, sem `tsc` do projeto,
  sem suíte completa. Só os arquivos de teste deste pacote + os testes existentes dos componentes
  alterados.
- Produção: só leitura. Sem push, sem `git stash`.
- Só editar arquivos do P4. `components/ui/dialog.tsx` **não** é editado.

Comandos (sempre a partir de `/root/crm-wt/cs-p4/frontend`):

```bash
flock /root/crm-wt/_heavy.lock npx vitest run <arquivos>
flock /root/crm-wt/_heavy.lock npx eslint <arquivos>
```

## Descobertas que moldam o plano (código real lido em 06/10)

1. `PATCH /api/leads/[id]` (`frontend/src/app/api/leads/[id]/route.ts:4-40`) **não tem
   whitelist**: faz `supabase.from("leads").update(body)` com o corpo inteiro (só sanitiza
   `phone`). Logo `ja_era_cliente`, `ja_era_cliente_fonte`, `ja_era_cliente_por`,
   `ja_era_cliente_em` já são aceitos — nada a mudar fora do P4.
2. Não existe `GET /api/leads/[id]`. `overview` é admin-only; `origin` só devolve colunas de
   origem. Solução no P4: client Supabase do browser (RLS de select liberada para
   `authenticated`, conferida em produção: `leads_select_authenticated`, `qual = true`).
3. O lead que chega no `contact-detail` vem de `conversation.leads`, cujo select é
   `LEAD_FIELDS` em `frontend/src/lib/supabase/conversation-enrichment.ts:8` — já inclui
   `email, cnpj, razao_social`, mas **não** `ja_era_cliente*`. Por isso o "Já é cliente?" é lido
   por id (item 2), não do objeto da conversa.
4. Os modais pré-preenchiam o cadastro com `leads.find(...)` sobre a lista de `pickLead` — vazia
   quando abertos pela conversa (`sale-create-modal.tsx:663,1069-1072`,
   `quote-create-modal.tsx:418,812-815`).
5. `Sheet` (`components/ui/sheet.tsx`) sempre renderiza `SheetOverlay`, mas o Radix devolve
   `null` no overlay quando `modal={false}` (`@radix-ui/react-dialog`: `context.modal ? … :
   null`). Painel não-modal = `Sheet modal={false}` + `onInteractOutside` com
   `preventDefault()` (senão clicar no chat fecharia o painel).
6. Catálogo: `GET /api/bling/products?q=` faz `ilike` em nome/código (`bling/router.py:160-167`);
   `q=kit degust` casa "KIT DEGUSTAÇÃO 1°", "Kit Degustação 2" etc. (conferido no espelho de
   produção, contas `default` e `secundaria`). A carga inicial é `limit=100` por nome — os kits
   podem nem estar nela; por isso uma busca própria dos kits.
7. `search-contacts` devolve **conversas** (com `leads(LEAD_FIELDS)` embutido), escopadas aos
   canais do usuário, mínimo de 2 caracteres (`CONTACT_SEARCH_MIN_LEN`).

## Arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `frontend/src/components/sales/lead-cliente.ts` | criar | busca do lead por id, defaults do contato Bling, corpo/gravação do "Já é cliente?", hook `useLeadCliente` |
| `frontend/src/components/sales/lead-cliente.test.ts` | criar | testes do acima |
| `frontend/src/components/sales/painel-lateral.tsx` | criar | casca não-modal à direita (Sheet `modal={false}`) |
| `frontend/src/components/sales/painel-lateral.test.tsx` | criar | sem overlay, clique fora não fecha |
| `frontend/src/components/sales/ja-era-cliente-toggle.tsx` | criar | Sim/Não + selo "auto" |
| `frontend/src/components/sales/lead-cabecalho.tsx` | criar | topo do lead na conversa |
| `frontend/src/components/sales/lead-cabecalho.test.tsx` | criar | copiar telefone, CNPJ, Sim/Não grava |
| `frontend/src/components/sales/kits.ts` | criar | `ehKitDegustacao`, `kitsPrimeiro`, `comKitsNoTopo` |
| `frontend/src/components/sales/kits.test.ts` | criar | testes do acima |
| `frontend/src/components/sales/bling-order-form.kits.test.tsx` | criar | grupo "Kits" no topo do seletor |
| `frontend/src/components/sales/lead-picker.tsx` | criar | seletor de lead via `search-contacts` com debounce |
| `frontend/src/components/sales/lead-picker.test.tsx` | criar | debounce, mínimo de 2, dedupe |
| `frontend/src/components/sales/sale-create-modal.p4.test.tsx` | criar | pré-preenchimento e "Já é cliente?" obrigatório |
| `frontend/src/components/quotes/quote-create-modal.p4.test.tsx` | criar | pré-preenchimento no orçamento |
| `frontend/src/components/sales/sale-create-modal.tsx` | modificar | usa tudo acima |
| `frontend/src/components/quotes/quote-create-modal.tsx` | modificar | idem (sem o "Já é cliente?") |
| `frontend/src/components/sales/bling-order-form.tsx` | modificar | grupo "Kits" |
| `frontend/src/components/conversas/contact-detail.tsx` | modificar | cabeçalho + aba Linha do tempo |

---

### Task 1 (base de 4.1/4.3/4.4): `lead-cliente.ts`

**Files:**
- Create: `frontend/src/components/sales/lead-cliente.ts`
- Test: `frontend/src/components/sales/lead-cliente.test.ts`

- [ ] **Step 1: teste falhando**

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

const { maybeSingle, colunas } = vi.hoisted(() => ({
  maybeSingle: vi.fn(),
  colunas: [] as string[],
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({
      select: (cols: string) => {
        colunas.push(cols);
        return { eq: () => ({ maybeSingle }) };
      },
    }),
  }),
}));

import {
  buscarLeadCliente,
  corpoJaEraCliente,
  defaultsDoContato,
  precisaPerguntarJaEraCliente,
} from "./lead-cliente";

beforeEach(() => {
  maybeSingle.mockReset();
  colunas.length = 0;
});

describe("buscarLeadCliente", () => {
  it("busca por id com as colunas do 'já era cliente'", async () => {
    maybeSingle.mockResolvedValueOnce({
      data: { id: "l1", name: "Iago", ja_era_cliente: null, ja_era_cliente_fonte: null },
      error: null,
    });
    const lead = await buscarLeadCliente("l1");
    expect(colunas[0]).toContain("ja_era_cliente");
    expect(colunas[0]).toContain("razao_social");
    expect(lead?.ja_era_cliente).toBeNull();
  });

  it("sem a migração do P0, cai para o cadastro e não trava a venda", async () => {
    maybeSingle
      .mockResolvedValueOnce({ data: null, error: { message: "column leads.ja_era_cliente does not exist" } })
      .mockResolvedValueOnce({ data: { id: "l1", name: "Iago" }, error: null });
    const lead = await buscarLeadCliente("l1");
    expect(colunas[1]).not.toContain("ja_era_cliente");
    expect(lead?.name).toBe("Iago");
    expect(lead?.ja_era_cliente).toBeUndefined();
    expect(precisaPerguntarJaEraCliente(lead)).toBe(false);
  });

  it("erro nas duas leituras devolve null", async () => {
    maybeSingle.mockResolvedValue({ data: null, error: { message: "x" } });
    expect(await buscarLeadCliente("l1")).toBeNull();
  });
});

describe("defaultsDoContato", () => {
  it("caso Vida Natural: razão social, CNPJ só dígitos, e-mail e telefone", () => {
    expect(
      defaultsDoContato({
        name: "Iago",
        razao_social: "VIDA NATURAL LTDA",
        cnpj: "12.345.678/0001-90",
        email: " compras@vidanatural.com ",
        phone: "5531999998888",
      }),
    ).toEqual({
      nome: "VIDA NATURAL LTDA",
      documento: "12345678000190",
      email: "compras@vidanatural.com",
      telefone: "5531999998888",
    });
  });

  it("sem razão social usa o nome; telefone sintético do Bling não entra", () => {
    expect(defaultsDoContato({ name: "Serginho", phone: "bling-123", cnpj: null })).toEqual({
      nome: "Serginho",
      documento: "",
      email: "",
      telefone: "",
    });
  });

  it("lead ausente não pré-preenche nada", () => {
    expect(defaultsDoContato(null)).toEqual({});
  });
});

describe("corpoJaEraCliente", () => {
  it("grava fonte vendedor, quem e quando", () => {
    expect(corpoJaEraCliente(false, "joao@cafecanastra.com", new Date("2026-10-06T12:00:00Z"))).toEqual({
      ja_era_cliente: false,
      ja_era_cliente_fonte: "vendedor",
      ja_era_cliente_por: "joao@cafecanastra.com",
      ja_era_cliente_em: "2026-10-06T12:00:00.000Z",
    });
  });

  it("sem e-mail do vendedor grava por = null", () => {
    expect(corpoJaEraCliente(true, "").ja_era_cliente_por).toBeNull();
  });
});

describe("precisaPerguntarJaEraCliente", () => {
  it("só pergunta quando o banco diz que não sabe (null)", () => {
    expect(precisaPerguntarJaEraCliente({ id: "l", ja_era_cliente: null })).toBe(true);
    expect(precisaPerguntarJaEraCliente({ id: "l", ja_era_cliente: true })).toBe(false);
    expect(precisaPerguntarJaEraCliente({ id: "l", ja_era_cliente: false })).toBe(false);
    expect(precisaPerguntarJaEraCliente({ id: "l" })).toBe(false);
    expect(precisaPerguntarJaEraCliente(null)).toBe(false);
  });
});
```

- [ ] **Step 2: rodar e ver falhar** — `flock /root/crm-wt/_heavy.lock npx vitest run src/components/sales/lead-cliente.test.ts` → FAIL (módulo `./lead-cliente` não existe).

- [ ] **Step 3: implementar**

```ts
/**
 * Dados do lead de que a venda e o topo da conversa precisam (P4 da call de
 * 01/10): o cadastro para pré-preencher o contato do Bling e o "Já é cliente?".
 *
 * A busca é POR ID, direto no Supabase do browser (RLS
 * `leads_select_authenticated`, o mesmo caminho de `use-realtime-leads` e
 * `lead-selector`): não existe `GET /api/leads/[id]`, e a lista `/api/leads`
 * inteira bate no teto de 1.000 linhas do PostgREST. Era por depender dessa
 * lista que o modal aberto pela conversa nascia com o cadastro vazio.
 */
import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { ContactForm } from "@/lib/bling-contact-form";
import { docDigits } from "@/lib/documento";

export type FonteJaEraCliente = "auto" | "vendedor";

/** O que o cadastro do contato no Bling aproveita do lead. */
export interface DadosDeContato {
  name?: string | null;
  phone?: string | null;
  email?: string | null;
  cnpj?: string | null;
  razao_social?: string | null;
}

export interface LeadCliente extends DadosDeContato {
  id: string;
  /**
   * `null` = o sistema não sabe — o vendedor precisa responder.
   * `undefined` = a coluna ainda não existe no banco (migração 20261006 não
   * aplicada): nada é bloqueado por causa dela.
   */
  ja_era_cliente?: boolean | null;
  ja_era_cliente_fonte?: FonteJaEraCliente | null;
}

const COLUNAS_BASE = "id, name, phone, email, cnpj, razao_social";
const COLUNAS_CLIENTE = `${COLUNAS_BASE}, ja_era_cliente, ja_era_cliente_fonte`;

export async function buscarLeadCliente(leadId: string): Promise<LeadCliente | null> {
  const sb = createClient();
  const completo = await sb
    .from("leads")
    .select(COLUNAS_CLIENTE)
    .eq("id", leadId)
    .maybeSingle();
  if (!completo.error) return (completo.data as unknown as LeadCliente | null) ?? null;

  // Sem a migração do P0 as colunas novas não existem e o select inteiro
  // falha. O cadastro continua valendo para o pré-preenchimento; só o "Já é
  // cliente?" fica indisponível (undefined) em vez de travar a venda.
  const base = await sb.from("leads").select(COLUNAS_BASE).eq("id", leadId).maybeSingle();
  if (base.error) return null;
  return (base.data as unknown as LeadCliente | null) ?? null;
}

/** Pré-preenchimento do cadastro do contato no Bling (resolvedor do 409). */
export function defaultsDoContato(
  lead: DadosDeContato | null | undefined,
): Partial<ContactForm> {
  if (!lead) return {};
  const telefone = (lead.phone ?? "").trim();
  return {
    // O cadastro do Bling pede "Nome / Razão social" como deve sair na nota:
    // para empresa é a razão social; sem ela (pessoa física), o nome.
    nome: (lead.razao_social || lead.name || "").trim(),
    documento: docDigits(lead.cnpj) ?? "",
    email: (lead.email ?? "").trim(),
    // `bling-<id>` é o telefone sintético dos leads criados pelo webhook do
    // Bling — não é número de ninguém.
    telefone: telefone.startsWith("bling-") ? "" : telefone,
  };
}

/** Corpo do PATCH em `/api/leads/{id}` quando o vendedor responde. */
export function corpoJaEraCliente(
  valor: boolean,
  por: string | null | undefined,
  agora: Date = new Date(),
) {
  return {
    ja_era_cliente: valor,
    ja_era_cliente_fonte: "vendedor" as const,
    ja_era_cliente_por: por || null,
    ja_era_cliente_em: agora.toISOString(),
  };
}

export async function salvarJaEraCliente(
  leadId: string,
  valor: boolean,
  por: string | null | undefined,
): Promise<void> {
  const res = await fetch(`/api/leads/${leadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpoJaEraCliente(valor, por)),
  }).catch(() => null);
  if (!res || !res.ok) {
    const corpo = res ? await res.json().catch(() => ({})) : {};
    throw new Error(
      (corpo as { error?: string }).error ??
        "Não foi possível salvar a resposta de “Já é cliente?”.",
    );
  }
}

/**
 * A venda só exige a resposta quando o banco diz que não sabe (`null`). O
 * sistema nunca marca "não" sozinho (decisão de 06/10) — por isso `false`
 * também não pergunta: foi um humano que respondeu.
 */
export function precisaPerguntarJaEraCliente(
  lead: LeadCliente | null | undefined,
): boolean {
  return !!lead && lead.ja_era_cliente === null;
}

/**
 * Lead por id, recarregado quando o id muda. `atualizar` aplica uma mudança
 * local (ex.: depois de gravar o "Já é cliente?") sem nova ida ao banco.
 */
export function useLeadCliente(leadId: string | null | undefined) {
  const [estado, setEstado] = useState<{ id: string; lead: LeadCliente | null } | null>(
    null,
  );

  useEffect(() => {
    if (!leadId) return;
    let vivo = true;
    buscarLeadCliente(leadId)
      .catch(() => null)
      .then((lead) => {
        if (vivo) setEstado({ id: leadId, lead });
      });
    return () => {
      vivo = false;
    };
  }, [leadId]);

  const atualizar = useCallback((patch: Partial<LeadCliente>) => {
    setEstado((atual) =>
      atual?.lead ? { ...atual, lead: { ...atual.lead, ...patch } } : atual,
    );
  }, []);

  const lead = leadId && estado?.id === leadId ? estado.lead : null;
  const carregando = !!leadId && estado?.id !== leadId;
  return { lead, carregando, atualizar };
}
```

- [ ] **Step 4: rodar e ver passar** — mesmo comando → PASS (10 testes).
- [ ] **Step 5: commit** — `git add frontend/src/components/sales/lead-cliente.ts frontend/src/components/sales/lead-cliente.test.ts && git commit -m "feat(vendas): busca do lead por id e regras do 'já era cliente' (P4)"`

---

### Task 2 (4.1): pré-preenchimento na venda e no orçamento

**Files:**
- Modify: `frontend/src/components/sales/sale-create-modal.tsx` (imports; `leadSelecionado` :660-663; `defaults` :1069-1072)
- Modify: `frontend/src/components/quotes/quote-create-modal.tsx` (imports; :418; `defaults` :812-815)
- Test: `frontend/src/components/sales/sale-create-modal.p4.test.tsx`, `frontend/src/components/quotes/quote-create-modal.p4.test.tsx`

- [ ] **Step 1: teste falhando da venda** (`sale-create-modal.p4.test.tsx`)

```tsx
/**
 * @vitest-environment jsdom
 *
 * P4 da call de 01/10 — o modal de venda aberto pela conversa (só `leadId`,
 * sem `pickLead`) precisa: pré-preencher o cadastro do Bling com o lead e
 * exigir "Já é cliente?" quando o banco não sabe.
 *
 * `BlingOrderForm` é trocado por um dublê que publica um pedido válido: o que
 * se testa aqui é o modal, não o catálogo (coberto em bling-order-form*.test).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const h = vi.hoisted(() => ({
  maybeSingle: vi.fn(),
  status: { enabled: true, accounts: [], loading: false, error: null as string | null },
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({ select: () => ({ eq: () => ({ maybeSingle: h.maybeSingle }) }) }),
  }),
}));

vi.mock("@/hooks/use-bling-status", () => ({ useBlingStatus: () => h.status }));

vi.mock("@/components/sales/bling-order-form", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  return {
    BlingOrderForm: ({
      onChange,
      meta,
    }: {
      onChange: (r: unknown) => void;
      meta: { leadId: string };
    }) => {
      React.useEffect(() => {
        onChange({
          valid: true,
          total: 60,
          installments: [{ valor: 60, dataVencimento: "2026-10-06" }],
          payload: {
            lead_id: meta.leadId,
            deal_id: null,
            sold_at: "2026-10-06",
            sold_by: null,
            notes: "",
            items: [
              {
                bling_product_id: 16536419853,
                codigo: null,
                descricao: "Kit Degustação",
                unidade: "UN",
                quantidade: 1,
                valor_unitario: 60,
                desconto_percentual: 0,
              },
            ],
            payment: { method_id: 1, terms: [0] },
          },
        });
      }, [onChange, meta.leadId]);
      return null;
    },
  };
});

import { SaleCreateModal } from "./sale-create-modal";

const LEAD_VIDA = {
  id: "lead-1",
  name: "Iago",
  phone: "5531999998888",
  email: "compras@vidanatural.com",
  cnpj: "12345678000190",
  razao_social: "VIDA NATURAL LTDA",
  ja_era_cliente: true,
  ja_era_cliente_fonte: "auto",
};

type Chamada = { url: string; method: string; body: unknown };
let chamadas: Chamada[] = [];

function mockFetch() {
  chamadas = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    chamadas.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const json = (status: number, corpo: unknown) =>
      ({ ok: status < 300, status, headers: new Headers({ "content-type": "application/json" }), json: async () => corpo }) as Response;
    if (url === "/api/bling/orders" && method === "POST")
      return json(409, { status: "missing", reason: "sem_correspondencia", candidates: [] });
    if (url.startsWith("/api/leads/") && method === "PATCH") return json(200, {});
    if (url === "/api/sales" && method === "POST") return json(201, {});
    return json(200, []);
  }) as unknown as typeof fetch;
}

function abrir(extra: Partial<React.ComponentProps<typeof SaleCreateModal>> = {}) {
  const onSaved = vi.fn();
  render(
    <SaleCreateModal
      leadId="lead-1"
      lockedDealId="deal-1"
      lockedDealTitle="Kit degustação"
      conversationId="conv-1"
      currentUserEmail="joao@cafecanastra.com"
      onClose={vi.fn()}
      onSaved={onSaved}
      {...extra}
    />,
  );
  return { onSaved };
}

beforeEach(() => {
  h.maybeSingle.mockReset();
  mockFetch();
});

afterEach(() => {
  cleanup();
});

describe("SaleCreateModal — pré-preenchimento (P4.1)", () => {
  it("aberto pela conversa, o cadastro do Bling nasce com os dados do lead", async () => {
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    abrir();
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalled());
    const enviar = await screen.findByRole("button", { name: "Lançar pedido no Bling" });
    await waitFor(() => expect((enviar as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(enviar);

    expect(await screen.findByDisplayValue("VIDA NATURAL LTDA")).toBeTruthy();
    expect(screen.getByDisplayValue("12345678000190")).toBeTruthy();
    expect(screen.getByDisplayValue("compras@vidanatural.com")).toBeTruthy();
    expect(screen.getByDisplayValue("5531999998888")).toBeTruthy();
    // Nada de lista inteira de leads quando o modal vem da conversa.
    expect(chamadas.some((c) => c.url === "/api/leads")).toBe(false);
  });
});
```

- [ ] **Step 2: teste falhando do orçamento** (`quote-create-modal.p4.test.tsx`) — mesmo cabeçalho de mocks (supabase, `use-bling-status`, dublê do `BlingOrderForm`, `mockFetch`) com estas diferenças: o 409 sai de `POST /api/quotes` (`{ error: "contact_unresolved", status: "missing", candidates: [] }`); o componente é `QuoteCreateModal` (`import { QuoteCreateModal } from "./quote-create-modal"`); o botão é "Gerar orçamento".

```tsx
describe("QuoteCreateModal — pré-preenchimento (P4.1)", () => {
  it("aberto pela conversa, o cadastro do Bling nasce com os dados do lead", async () => {
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    render(
      <QuoteCreateModal
        leadId="lead-1"
        lockedDealId="deal-1"
        conversationId="conv-1"
        currentUserEmail="joao@cafecanastra.com"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalled());
    const enviar = await screen.findByRole("button", { name: "Gerar orçamento" });
    await waitFor(() => expect((enviar as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(enviar);

    expect(await screen.findByDisplayValue("VIDA NATURAL LTDA")).toBeTruthy();
    expect(screen.getByDisplayValue("12345678000190")).toBeTruthy();
    expect(screen.getByDisplayValue("compras@vidanatural.com")).toBeTruthy();
    expect(chamadas.some((c) => c.url === "/api/leads")).toBe(false);
  });
});
```

(O arquivo inteiro é escrito sem "ver acima": copia o bloco de mocks da venda trocando as três
diferenças.)

- [ ] **Step 3: rodar e ver falhar** — `flock /root/crm-wt/_heavy.lock npx vitest run src/components/sales/sale-create-modal.p4.test.tsx src/components/quotes/quote-create-modal.p4.test.tsx` → FAIL (`findByDisplayValue("VIDA NATURAL LTDA")` não encontra: o nome nasce vazio).

- [ ] **Step 4: implementar na venda** — em `sale-create-modal.tsx`:

```tsx
import { defaultsDoContato, useLeadCliente } from "@/components/sales/lead-cliente";
```

logo depois de `const resolvedLeadId = …` (bloco "helpers"), trocar o `leadSelecionado` por:

```tsx
  // Cadastro do lead POR ID — vale para qualquer porta de entrada (conversa,
  // card, painel de vendas). Antes vinha da lista do `pickLead`, vazia quando
  // o modal era aberto pela conversa, e o vendedor redigitava tudo.
  const { lead: leadCliente } = useLeadCliente(isEditing ? null : resolvedLeadId);
```

(o hook precisa ficar acima de qualquer `return` — o componente não tem return antecipado, então
basta ficar no corpo, antes do JSX). E no resolvedor:

```tsx
              defaults={defaultsDoContato(leadCliente)}
```

- [ ] **Step 5: implementar no orçamento** — em `quote-create-modal.tsx`, mesmo import; trocar
`const leadSelecionado = leads.find(...)` por

```tsx
  const { lead: leadCliente } = useLeadCliente(resolvedLeadId || null);
```

e `defaults={defaultsDoContato(leadCliente)}`. O orçamento busca também na edição (o PUT também
pode devolver 409 de contato). O rótulo do lead no seletor (`leadSelecionado?.name`) passa a usar
`leadCliente?.name ?? leadCliente?.phone`.

- [ ] **Step 6: rodar e ver passar** — mesmo comando → PASS.
- [ ] **Step 7: commit** — `feat(vendas): venda e orçamento pela conversa já abrem com o cadastro do lead (P4.1)`

---

### Task 3 (4.2): painel lateral sem overlay

**Files:**
- Create: `frontend/src/components/sales/painel-lateral.tsx`
- Test: `frontend/src/components/sales/painel-lateral.test.tsx`
- Modify: `sale-create-modal.tsx` (Dialog → PainelLateral), `quote-create-modal.tsx` (idem)

- [ ] **Step 1: teste falhando**

```tsx
/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PainelLateral } from "./painel-lateral";

afterEach(cleanup);

const espera = () => new Promise((r) => setTimeout(r, 20));

describe("PainelLateral", () => {
  it("não cobre a conversa: sem overlay e sem travar o resto da página", async () => {
    render(
      <PainelLateral titulo="Registrar Venda" onFechar={vi.fn()}>
        <p>corpo</p>
      </PainelLateral>,
    );
    await espera();
    expect(screen.getByText("corpo")).toBeTruthy();
    expect(document.querySelector('[data-slot="sheet-overlay"]')).toBeNull();
    expect(document.body.style.pointerEvents).not.toBe("none");
  });

  it("clicar fora (no chat) não fecha o painel", async () => {
    const onFechar = vi.fn();
    const fora = document.createElement("div");
    document.body.appendChild(fora);
    render(
      <PainelLateral titulo="Registrar Venda" onFechar={onFechar}>
        <p>corpo</p>
      </PainelLateral>,
    );
    await espera();
    fireEvent.pointerDown(fora);
    fireEvent.focusIn(fora);
    await espera();
    expect(onFechar).not.toHaveBeenCalled();
    fora.remove();
  });

  it("o X fecha", () => {
    const onFechar = vi.fn();
    render(
      <PainelLateral titulo="Registrar Venda" onFechar={onFechar}>
        <p>corpo</p>
      </PainelLateral>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
    expect(onFechar).toHaveBeenCalledTimes(1);
  });

  it("mostra o título", () => {
    render(
      <PainelLateral titulo="Novo Orçamento" onFechar={vi.fn()}>
        <p>corpo</p>
      </PainelLateral>,
    );
    expect(screen.getByText("Novo Orçamento")).toBeTruthy();
  });
});
```

- [ ] **Step 2: ver falhar** (`painel-lateral` não existe).

- [ ] **Step 3: implementar**

```tsx
"use client";

/**
 * Casca dos formulários de venda e orçamento: painel à direita SEM overlay.
 *
 * O `Dialog` borrava e bloqueava o chat — o vendedor fechava o modal para
 * copiar um dado da conversa e perdia o pedido (call de 01/10). Aqui o painel
 * é não-modal: a conversa continua visível, clicável e selecionável.
 *
 * `Sheet` com `modal={false}`: o Radix não renderiza o overlay nesse modo, não
 * trava o foco nem o `pointer-events` do body. Clicar fora fecharia o painel
 * por padrão — e "fora" é justamente o chat —, por isso `onInteractOutside`
 * cancela o fechamento. Fecha pelo X, por "Cancelar" ou pelo Esc.
 *
 * `components/ui/dialog.tsx` não é tocado: é compartilhado pelo CRM inteiro.
 */
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

const LARGURA = {
  md: "data-[side=right]:sm:max-w-md",
  lg: "data-[side=right]:sm:max-w-2xl",
  xl: "data-[side=right]:sm:max-w-4xl",
} as const;

interface PainelLateralProps {
  titulo: string;
  largura?: keyof typeof LARGURA;
  onFechar: () => void;
  children: React.ReactNode;
}

export function PainelLateral({
  titulo,
  largura = "lg",
  onFechar,
  children,
}: PainelLateralProps) {
  return (
    <Sheet
      open
      modal={false}
      onOpenChange={(aberto) => {
        if (!aberto) onFechar();
      }}
    >
      <SheetContent
        side="right"
        showCloseButton={false}
        aria-describedby={undefined}
        onInteractOutside={(e) => e.preventDefault()}
        className={`bg-white border-l border-[#dedbd6] p-0 gap-0 flex flex-col data-[side=right]:w-full ${LARGURA[largura]}`}
      >
        <div className="shrink-0 flex items-center justify-between px-5 py-4 border-b border-[#dedbd6]">
          <SheetTitle className="text-[15px] font-medium text-[#111111]">{titulo}</SheetTitle>
          <button
            type="button"
            onClick={onFechar}
            aria-label="Fechar"
            className="w-7 h-7 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="min-h-0 flex-1 flex flex-col">{children}</div>
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 4: venda** — trocar `<Dialog …><DialogContent …><DialogHeader>…</DialogHeader>` e o
fechamento `</DialogContent></Dialog>` por
`<PainelLateral titulo={isEditing ? "Editar Venda" : "Registrar Venda"} largura={blingLayout ? "lg" : "md"} onFechar={fecharModal}> … </PainelLateral>`;
remover o import de `@/components/ui/dialog`; o `<form>` ganha `flex-1` (`"flex min-h-0 flex-1 flex-col"`) e o corpo
rolável `flex-1` (`"min-h-0 flex-1 overflow-y-auto p-5 space-y-4"`) para as ações ficarem no rodapé do painel.

- [ ] **Step 5: orçamento** — mesmo troca com `titulo={isEditing ? "Editar Orçamento" : "Novo Orçamento"}`,
`largura="xl"`; todo o conteúdo (form + painéis de 409/convertido/sucesso) dentro de
`<div className="min-h-0 flex-1 overflow-y-auto"> … </div>` (o `DialogContent` antigo é que rolava).

- [ ] **Step 6: rodar** `painel-lateral.test.tsx`, `sale-create-modal.p4.test.tsx`, `quote-create-modal.p4.test.tsx`, `sale-create-modal.test.ts`, `quote-create-modal.test.ts` → PASS.
- [ ] **Step 7: commit** — `feat(vendas): venda e orçamento em painel lateral sem cobrir a conversa (P4.2)`

---

### Task 4 (4.3): cabeçalho do lead na conversa

**Files:**
- Create: `frontend/src/components/sales/ja-era-cliente-toggle.tsx`, `frontend/src/components/sales/lead-cabecalho.tsx`
- Test: `frontend/src/components/sales/lead-cabecalho.test.tsx`
- Modify: `frontend/src/components/conversas/contact-detail.tsx` (depois do bloco avatar/nome, antes das abas)

- [ ] **Step 1: teste falhando**

```tsx
/**
 * @vitest-environment jsdom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const h = vi.hoisted(() => ({ maybeSingle: vi.fn() }));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({ select: () => ({ eq: () => ({ maybeSingle: h.maybeSingle }) }) }),
  }),
}));

import { LeadCabecalho } from "./lead-cabecalho";

const LEAD = {
  id: "lead-1",
  phone: "5531999998888",
  email: "compras@vidanatural.com",
  cnpj: "12345678000190",
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  h.maybeSingle.mockReset();
  fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }) as Response);
  global.fetch = fetchMock as unknown as typeof fetch;
});
afterEach(cleanup);

function abrir(onSaveField = vi.fn()) {
  render(
    <LeadCabecalho lead={LEAD} currentUserEmail="joao@cafecanastra.com" onSaveField={onSaveField} />,
  );
  return { onSaveField };
}

describe("LeadCabecalho", () => {
  it("mostra telefone, e-mail e CNPJ formatado", async () => {
    h.maybeSingle.mockResolvedValue({ data: { id: "lead-1", ja_era_cliente: null }, error: null });
    abrir();
    expect(screen.getByText("5531999998888")).toBeTruthy();
    expect(screen.getByText("compras@vidanatural.com")).toBeTruthy();
    expect(screen.getByText("12.345.678/0001-90")).toBeTruthy();
  });

  it("copia o telefone", async () => {
    h.maybeSingle.mockResolvedValue({ data: { id: "lead-1", ja_era_cliente: null }, error: null });
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    abrir();
    fireEvent.click(screen.getByRole("button", { name: "Copiar telefone" }));
    expect(writeText).toHaveBeenCalledWith("5531999998888");
  });

  it("selo 'auto' quando o sistema marcou", async () => {
    h.maybeSingle.mockResolvedValue({
      data: { id: "lead-1", ja_era_cliente: true, ja_era_cliente_fonte: "auto" },
      error: null,
    });
    abrir();
    expect(await screen.findByText("auto")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sim" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("o vendedor sobrescreve: Não grava fonte vendedor, por e em", async () => {
    h.maybeSingle.mockResolvedValue({
      data: { id: "lead-1", ja_era_cliente: true, ja_era_cliente_fonte: "auto" },
      error: null,
    });
    abrir();
    await screen.findByText("auto");
    fireEvent.click(screen.getByRole("button", { name: "Não" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/leads/lead-1");
    expect(init.method).toBe("PATCH");
    const corpo = JSON.parse(String(init.body));
    expect(corpo).toMatchObject({
      ja_era_cliente: false,
      ja_era_cliente_fonte: "vendedor",
      ja_era_cliente_por: "joao@cafecanastra.com",
    });
    expect(typeof corpo.ja_era_cliente_em).toBe("string");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Não" }).getAttribute("aria-pressed")).toBe("true"),
    );
    expect(screen.queryByText("auto")).toBeNull();
  });

  it("falha ao gravar volta ao valor anterior e avisa", async () => {
    h.maybeSingle.mockResolvedValue({ data: { id: "lead-1", ja_era_cliente: null }, error: null });
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({ error: "boom" }) } as Response);
    abrir();
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Sim" }));
    expect(await screen.findByText("boom")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sim" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("CNPJ digitado com máscara é gravado só com dígitos", async () => {
    h.maybeSingle.mockResolvedValue({ data: { id: "lead-1", ja_era_cliente: null }, error: null });
    const { onSaveField } = abrir();
    fireEvent.click(screen.getByText("12.345.678/0001-90"));
    const campo = screen.getByDisplayValue("12.345.678/0001-90");
    fireEvent.change(campo, { target: { value: "11.222.333/0001-81" } });
    fireEvent.keyDown(campo, { key: "Enter" });
    expect(onSaveField).toHaveBeenCalledWith("cnpj", "11222333000181");
  });
});
```

- [ ] **Step 2: ver falhar.**

- [ ] **Step 3: `ja-era-cliente-toggle.tsx`**

```tsx
"use client";

import type { FonteJaEraCliente } from "./lead-cliente";

interface JaEraClienteToggleProps {
  /** `null`/`undefined` = sem resposta: nenhum botão marcado. */
  valor: boolean | null | undefined;
  fonte?: FonteJaEraCliente | null;
  onEscolher: (valor: boolean) => void;
  desabilitado?: boolean;
  obrigatorio?: boolean;
  rotulo?: string;
}

/**
 * Sim/Não do "Já é cliente?". Dois botões sempre visíveis (não um select): a
 * pergunta é binária e o vendedor responde com um clique, no estilo do RD.
 * Selo "auto" quando quem marcou foi a regra do banco (venda anterior à
 * entrada do lead) — o vendedor vê de onde veio e pode sobrescrever.
 */
export function JaEraClienteToggle({
  valor,
  fonte,
  onEscolher,
  desabilitado,
  obrigatorio,
  rotulo = "Já é cliente?",
}: JaEraClienteToggleProps) {
  return (
    <div role="group" aria-label={rotulo} className="flex items-center gap-2 flex-wrap">
      <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
        {rotulo}
        {obrigatorio ? " *" : ""}
      </span>
      <div className="flex">
        {[true, false].map((opcao) => (
          <button
            key={String(opcao)}
            type="button"
            aria-pressed={valor === opcao}
            disabled={desabilitado}
            onClick={() => onEscolher(opcao)}
            className={`h-[26px] px-3 -ml-px first:ml-0 first:rounded-l-[4px] last:rounded-r-[4px] text-[12px] border transition-colors disabled:opacity-60 ${
              valor === opcao
                ? "bg-[#111111] border-[#111111] text-white"
                : "bg-white border-[#dedbd6] text-[#7b7b78] hover:text-[#111111]"
            }`}
          >
            {opcao ? "Sim" : "Não"}
          </button>
        ))}
      </div>
      {fonte === "auto" && (
        <span
          title="Marcado pelo sistema: há venda anterior à entrada do lead"
          className="px-1.5 py-0.5 rounded-[4px] text-[10px] uppercase tracking-[0.4px] bg-[#dedbd6]/60 text-[#7b7b78]"
        >
          auto
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 4: `lead-cabecalho.tsx`**

```tsx
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
      <JaEraClienteToggle
        valor={cliente?.ja_era_cliente}
        fonte={cliente?.ja_era_cliente_fonte}
        onEscolher={responder}
        desabilitado={salvando}
      />
      {erro && <p className="text-[11px] text-[#c41c1c]">{erro}</p>}
    </div>
  );
}
```

- [ ] **Step 5: montar no `contact-detail.tsx`** — import
`import { LeadCabecalho } from "@/components/sales/lead-cabecalho";` e, logo depois do `</div>` do
bloco avatar/nome (antes da barra de abas):

```tsx
      {lead && (
        <LeadCabecalho
          lead={lead}
          currentUserEmail={currentUserEmail}
          onSaveField={updateLeadField}
        />
      )}
```

- [ ] **Step 6: rodar** `lead-cabecalho.test.tsx` → PASS.
- [ ] **Step 7: commit** — `feat(conversas): topo do lead com telefone, e-mail, CNPJ e 'já é cliente?' (P4.3)`

---

### Task 5 (4.4): "Já é cliente?" obrigatório na venda quando o sistema não sabe

**Files:**
- Modify: `frontend/src/components/sales/sale-create-modal.tsx`
- Test: `frontend/src/components/sales/sale-create-modal.p4.test.tsx` (novo `describe`)

- [ ] **Step 1: testes falhando** (acrescentar ao arquivo da Task 2)

```tsx
describe("SaleCreateModal — 'Já é cliente?' obrigatório (P4.4)", () => {
  it("lead com ja_era_cliente nulo: pergunta e só libera Salvar com resposta", async () => {
    h.maybeSingle.mockResolvedValue({ data: { ...LEAD_VIDA, ja_era_cliente: null, ja_era_cliente_fonte: null }, error: null });
    const { onSaved } = abrir({ blingEnabled: false });
    expect(await screen.findByRole("group", { name: "Já é cliente?" })).toBeTruthy();
    const salvar = screen.getByRole("button", { name: "Registrar Venda" }) as HTMLButtonElement;
    expect(salvar.disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Não" }));
    expect(salvar.disabled).toBe(false);

    fireEvent.change(screen.getByPlaceholderText("Ex: Café especial 5kg"), { target: { value: "Kit degustação" } });
    fireEvent.change(screen.getByPlaceholderText("0,00"), { target: { value: "60" } });
    fireEvent.click(salvar);

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const patch = chamadas.findIndex((c) => c.url === "/api/leads/lead-1" && c.method === "PATCH");
    const venda = chamadas.findIndex((c) => c.url === "/api/sales" && c.method === "POST");
    expect(patch).toBeGreaterThanOrEqual(0);
    expect(patch).toBeLessThan(venda);
    expect(chamadas[patch].body).toMatchObject({
      ja_era_cliente: false,
      ja_era_cliente_fonte: "vendedor",
      ja_era_cliente_por: "joao@cafecanastra.com",
    });
  });

  it("lead que o sistema já sabe: não pergunta nem grava", async () => {
    h.maybeSingle.mockResolvedValue({ data: LEAD_VIDA, error: null });
    const { onSaved } = abrir({ blingEnabled: false });
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalled());
    expect(screen.queryByRole("group", { name: "Já é cliente?" })).toBeNull();
    fireEvent.change(screen.getByPlaceholderText("Ex: Café especial 5kg"), { target: { value: "Kit" } });
    fireEvent.change(screen.getByPlaceholderText("0,00"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar Venda" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(chamadas.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("banco sem a coluna (P0 não aplicado): não trava a venda", async () => {
    h.maybeSingle
      .mockResolvedValueOnce({ data: null, error: { message: "column does not exist" } })
      .mockResolvedValueOnce({ data: { id: "lead-1", name: "Iago" }, error: null });
    abrir({ blingEnabled: false });
    await waitFor(() => expect(h.maybeSingle).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("group", { name: "Já é cliente?" })).toBeNull();
  });

  it("falha ao gravar a resposta: não registra a venda e mostra o erro", async () => {
    h.maybeSingle.mockResolvedValue({ data: { ...LEAD_VIDA, ja_era_cliente: null }, error: null });
    const original = global.fetch;
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH")
        return { ok: false, status: 500, json: async () => ({ error: "falhou o PATCH" }) } as Response;
      return original(input, init);
    }) as unknown as typeof fetch;
    abrir({ blingEnabled: false });
    await screen.findByRole("group", { name: "Já é cliente?" });
    fireEvent.click(screen.getByRole("button", { name: "Sim" }));
    fireEvent.change(screen.getByPlaceholderText("Ex: Café especial 5kg"), { target: { value: "Kit" } });
    fireEvent.change(screen.getByPlaceholderText("0,00"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Registrar Venda" }));
    expect(await screen.findByText("falhou o PATCH")).toBeTruthy();
    expect(chamadas.some((c) => c.url === "/api/sales")).toBe(false);
  });
});
```

- [ ] **Step 2: ver falhar** (não há grupo "Já é cliente?").

- [ ] **Step 3: implementar** em `sale-create-modal.tsx`:

imports:

```tsx
import { JaEraClienteToggle } from "@/components/sales/ja-era-cliente-toggle";
import {
  defaultsDoContato,
  precisaPerguntarJaEraCliente,
  salvarJaEraCliente,
  useLeadCliente,
} from "@/components/sales/lead-cliente";
```

estado (junto dos outros `useState`): `const [respostaCliente, setRespostaCliente] = useState<boolean | null>(null);`

O hook `useLeadCliente` sobe para antes do `handleSubmit` (precisa existir antes dele) e passa a
expor `atualizar`:

```tsx
  const leadAlvo = selectedLeadId || leadId || "";
  const { lead: leadCliente, atualizar: atualizarLeadCliente } = useLeadCliente(
    isEditing ? null : leadAlvo,
  );
  // "Já é cliente?" é obrigatório só quando o banco não sabe (decisão de 06/10:
  // automático quando há evidência, vendedor só na dúvida). Edição não pergunta.
  const perguntarCliente = !isEditing && precisaPerguntarJaEraCliente(leadCliente);
  const faltaRespostaCliente = perguntarCliente && respostaCliente === null;

  /** Grava a resposta no lead antes da venda. `false` = falhou, não seguir. */
  async function gravarRespostaCliente(): Promise<boolean> {
    if (!perguntarCliente) return true;
    if (respostaCliente === null) {
      setError("Responda “Já é cliente?” para registrar a venda");
      return false;
    }
    setSaving(true);
    setError(null);
    try {
      await salvarJaEraCliente(leadAlvo, respostaCliente, currentUserEmail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao salvar “Já é cliente?”");
      setSaving(false);
      return false;
    }
    atualizarLeadCliente({ ja_era_cliente: respostaCliente, ja_era_cliente_fonte: "vendedor" });
    return true;
  }
```

No `handleSubmit`, ramo Bling da criação, logo depois do `if (!orderResult?.valid) {…}`:
`if (!(await gravarRespostaCliente())) return;` — e no ramo legado, antes de
`setSaving(true); setError(null); const payload = …`: a mesma linha.

JSX, logo depois do bloco do seletor de lead:

```tsx
            {perguntarCliente && (
              <div className="p-3 bg-[#faf9f6] border border-[#dedbd6] rounded-[4px] space-y-1">
                <JaEraClienteToggle
                  obrigatorio
                  valor={respostaCliente}
                  onEscolher={setRespostaCliente}
                />
                <p className="text-[11px] text-[#7b7b78]">
                  O sistema não sabe se este lead já comprava antes de chegar. A
                  resposta fica gravada no lead.
                </p>
              </div>
            )}
```

Botão salvar: `disabled={saving || !gate.canSubmit || (blingMode && !orderResult?.valid) || faltaRespostaCliente}`;
dica no rodapé: `{faltaRespostaCliente && !error && (<p className="text-[11px] text-[#7b7b78]">Responda “Já é cliente?” para registrar a venda.</p>)}`.

- [ ] **Step 4: rodar** `sale-create-modal.p4.test.tsx` + `sale-create-modal.test.ts` → PASS.
- [ ] **Step 5: commit** — `feat(vendas): 'já é cliente?' obrigatório na venda quando o sistema não sabe (P4.4)`

---

### Task 6 (4.5): kits no topo do seletor de produtos

**Files:**
- Create: `frontend/src/components/sales/kits.ts`; Test: `kits.test.ts`, `bling-order-form.kits.test.tsx`
- Modify: `frontend/src/components/sales/bling-order-form.tsx` (estado + efeito de kits; lista do popover :487-527)

- [ ] **Step 1: `kits.test.ts` falhando**

```ts
import { describe, expect, it } from "vitest";
import { comKitsNoTopo, ehKitDegustacao, kitsPrimeiro } from "./kits";

const p = (id: number, nome: string) => ({ id, nome });

describe("ehKitDegustacao", () => {
  it("casa os nomes reais do catálogo, sem caixa nem acento", () => {
    for (const nome of ["Kit Degustação", "KIT DEGUSTAÇÃO", "KIT DEGUSTAÇÃO 1°", "Kit Degustação 2", "kit degustacao"]) {
      expect(ehKitDegustacao(nome)).toBe(true);
    }
  });
  it("outros kits e cafés não entram", () => {
    for (const nome of ["Kit Promo 1 - Cápsula Clássico", "Kit Amostra de Cafés", "Café Clássico Moído 250g", "", null, undefined]) {
      expect(ehKitDegustacao(nome)).toBe(false);
    }
  });
});

describe("kitsPrimeiro", () => {
  it("move os kits para o topo preservando a ordem relativa", () => {
    const lista = [p(1, "Café A"), p(2, "Kit Degustação 2"), p(3, "Café B"), p(4, "KIT DEGUSTAÇÃO 1°")];
    expect(kitsPrimeiro(lista).map((x) => x.id)).toEqual([2, 4, 1, 3]);
  });
  it("sem kits devolve a mesma lista", () => {
    const lista = [p(1, "Café A")];
    expect(kitsPrimeiro(lista)).toBe(lista);
  });
});

describe("comKitsNoTopo", () => {
  it("une os kits buscados à parte com a página, sem duplicar", () => {
    const kits = [p(9, "Kit Degustação"), p(2, "Kit Degustação 2")];
    const pagina = [p(1, "Café A"), p(2, "Kit Degustação 2")];
    expect(comKitsNoTopo(kits, pagina).map((x) => x.id)).toEqual([9, 2, 1]);
  });
  it("ignora o que a busca de kits trouxe e não é kit de degustação", () => {
    expect(comKitsNoTopo([p(5, "Kit Promo 1")], [p(1, "Café")]).map((x) => x.id)).toEqual([1]);
  });
});
```

- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: `kits.ts`**

```ts
/**
 * Kits de degustação no topo do seletor de produtos (call de 01/10): o kit é
 * venda direta, a mais comum da conversa, e se perdia no meio do catálogo por
 * ordem alfabética — às vezes nem vinha na primeira página.
 *
 * Critério por nome ("kit degust", sem caixa nem acento), o mesmo do P3/P6
 * para `sale_items.descricao`. Os SKUs mudam entre as duas contas Bling; o nome
 * é o que as duas têm em comum.
 */
import { foldText } from "@/lib/search";

export const TERMO_KIT = "kit degust";

export function ehKitDegustacao(nome: string | null | undefined): boolean {
  return !!nome && foldText(nome).includes(TERMO_KIT);
}

/** Kits primeiro, o resto depois — ordem relativa preservada nos dois grupos. */
export function kitsPrimeiro<T extends { nome: string }>(lista: T[]): T[] {
  const kits = lista.filter((p) => ehKitDegustacao(p.nome));
  if (kits.length === 0) return lista;
  return [...kits, ...lista.filter((p) => !ehKitDegustacao(p.nome))];
}

/** Kits buscados à parte + página do catálogo, sem repetir produto. */
export function comKitsNoTopo<T extends { id: number; nome: string }>(
  kits: T[],
  pagina: T[],
): T[] {
  const vistos = new Set<number>();
  const out: T[] = [];
  for (const p of [...kits.filter((k) => ehKitDegustacao(k.nome)), ...kitsPrimeiro(pagina)]) {
    if (vistos.has(p.id)) continue;
    vistos.add(p.id);
    out.push(p);
  }
  return out;
}
```

- [ ] **Step 4: rodar `kits.test.ts`** → PASS.

- [ ] **Step 5: `bling-order-form.kits.test.tsx` falhando**

```tsx
/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { BlingOrderForm } from "./bling-order-form";

const META = { leadId: "lead-1", dealId: null, soldAt: "2026-10-06", soldBy: null, notes: "" };
const produto = (id: number, nome: string, preco = 10) => ({
  id, nome, codigo: null, preco, unidade: "UN", saldo_virtual: null, imagem_url: null,
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockCatalogo() {
  const urls: string[] = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    urls.push(url);
    let data: unknown[] = [];
    if (url.includes("q=kit%20degust")) data = [produto(3, "KIT DEGUSTAÇÃO 1°", 80)];
    else if (url.startsWith("/api/bling/products"))
      data = [produto(1, "Café Clássico Moído 250g", 28.7), produto(2, "Kit Degustação", 60)];
    return { ok: true, json: async () => ({ data }) } as Response;
  }) as unknown as typeof fetch;
  return urls;
}

describe("BlingOrderForm — kits no topo (P4.5)", () => {
  it("abre o seletor com o grupo Kits antes dos demais produtos", async () => {
    const urls = mockCatalogo();
    render(<BlingOrderForm meta={META} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Selecione o produto/ }));
    expect(await screen.findByText("Kits")).toBeTruthy();
    await screen.findByText("Café Clássico Moído 250g");
    const nomes = screen
      .getAllByRole("button")
      .map((b) => b.textContent ?? "")
      .filter((t) => /KIT|Kit|Café/.test(t));
    const iKit1 = nomes.findIndex((t) => t.includes("KIT DEGUSTAÇÃO 1°"));
    const iKit = nomes.findIndex((t) => t.startsWith("Kit Degustação"));
    const iCafe = nomes.findIndex((t) => t.includes("Café Clássico"));
    expect(iKit1).toBeGreaterThanOrEqual(0);
    expect(iKit).toBeGreaterThanOrEqual(0);
    expect(iKit1).toBeLessThan(iCafe);
    expect(iKit).toBeLessThan(iCafe);
    expect(urls.some((u) => u.includes("q=kit%20degust"))).toBe(true);
  });

  it("escolher um kit que só veio pela busca de kits preenche a linha", async () => {
    mockCatalogo();
    render(<BlingOrderForm meta={META} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Selecione o produto/ }));
    const kit = await screen.findByText("KIT DEGUSTAÇÃO 1°");
    fireEvent.click(kit.closest("button")!);
    const linha = screen.getByRole("button", { name: /KIT DEGUSTAÇÃO 1°/ });
    expect(within(linha).getByText("KIT DEGUSTAÇÃO 1°")).toBeTruthy();
  });
});
```

- [ ] **Step 6: ver falhar** (sem grupo "Kits").

- [ ] **Step 7: implementar em `bling-order-form.tsx`**

import: `import { TERMO_KIT, comKitsNoTopo, ehKitDegustacao, kitsPrimeiro } from "@/components/sales/kits";`

estado: `const [kits, setKits] = useState<BlingProduct[]>([]);`

efeito (depois do de formas de pagamento):

```tsx
  // Kits de degustação buscados à parte: a página inicial (100 por nome) pode
  // nem trazê-los, e eles precisam estar no topo sem o vendedor digitar nada.
  useEffect(() => {
    if (!contaResolvida) return;
    let vivo = true;
    const contaQs = contaAtual ? `&account=${encodeURIComponent(contaAtual)}` : "";
    fetch(`/api/bling/products?limit=20&q=${encodeURIComponent(TERMO_KIT)}${contaQs}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("http"))))
      .then((d) => {
        if (!vivo) return;
        const lista: BlingProduct[] = (Array.isArray(d?.data) ? d.data : []).filter(
          (p: BlingProduct) => ehKitDegustacao(p.nome),
        );
        setKits(lista);
        setConhecidos((antes) => {
          const mapa = { ...antes };
          for (const p of lista) mapa[p.id] = p;
          return mapa;
        });
      })
      .catch(() => undefined);
    return () => {
      vivo = false;
    };
  }, [contaResolvida, contaAtual]);

  // Com busca digitada, só reordena o que a busca trouxe; sem busca, os kits
  // buscados à parte entram no topo da página inicial.
  const visiveis = busca.trim() ? kitsPrimeiro(resultados) : comKitsNoTopo(kits, resultados);
  const grupoKits = visiveis.filter((p) => ehKitDegustacao(p.nome));
  const demais = visiveis.filter((p) => !ehKitDegustacao(p.nome));
```

No `aoTrocarConta`, junto de `setResultados([])`: `setKits([]);`.

No popover: "Nenhum produto encontrado" passa a usar `visiveis.length === 0`; a lista vira

```tsx
                      {grupoKits.length > 0 && (
                        <div className="px-2 pt-1.5 pb-1 text-[10px] uppercase tracking-[0.6px] text-[#7b7b78]">
                          Kits
                        </div>
                      )}
                      {grupoKits.map((p) => renderOpcao(p))}
                      {grupoKits.length > 0 && demais.length > 0 && (
                        <div className="px-2 pt-2 pb-1 text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] border-t border-[#eee] mt-1">
                          Produtos
                        </div>
                      )}
                      {demais.map((p) => renderOpcao(p))}
```

com `renderOpcao` uma função local dentro do `linhas.map` (mesmo botão de hoje), e
`applyProduct(atuais, i, p.id, visiveis)` (a lista que contém o kit da busca própria).

- [ ] **Step 8: rodar** `kits.test.ts`, `bling-order-form.kits.test.tsx`, `bling-order-form.test.tsx` → PASS.
- [ ] **Step 9: commit** — `feat(vendas): kits de degustação no topo do seletor de produtos (P4.5)`

---

### Task 7 (4.6): seletor de lead via `search-contacts`

**Files:**
- Create: `frontend/src/components/sales/lead-picker.tsx`; Test: `lead-picker.test.tsx`
- Modify: `sale-create-modal.tsx` (remove `fetch("/api/leads")` :249-256, `leads`/`leadQuery`/`leadPickerOpen`, combobox :728-788), `quote-create-modal.tsx` (:245-251, :463-521)

- [ ] **Step 1: teste falhando**

```tsx
/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LeadPicker, leadsDaBusca } from "./lead-picker";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const conversa = (leadId: string, name: string, extra: Record<string, unknown> = {}) => ({
  id: `conv-${leadId}-${Math.random()}`,
  leads: { id: leadId, name, phone: "5531999990000", email: null, cnpj: null, razao_social: null, ...extra },
});

describe("leadsDaBusca", () => {
  it("um lead por id, mesmo com duas conversas", () => {
    const out = leadsDaBusca([conversa("a", "Vida"), conversa("a", "Vida"), conversa("b", "Iago"), { id: "x", leads: null }]);
    expect(out.map((l) => l.id)).toEqual(["a", "b"]);
  });
  it("resposta que não é lista vira vazio", () => {
    expect(leadsDaBusca({ error: "x" })).toEqual([]);
  });
});

describe("LeadPicker", () => {
  it("busca no servidor com debounce, só a partir de 2 caracteres, e devolve o lead", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => [conversa("lead-9", "Vida Natural", { cnpj: "12345678000190" })],
    }) as Response);
    global.fetch = fetchMock as unknown as typeof fetch;
    const onEscolher = vi.fn();
    render(<LeadPicker selecionado={null} onEscolher={onEscolher} />);

    fireEvent.click(screen.getByRole("button", { name: /Selecione o lead/ }));
    const campo = screen.getByPlaceholderText("Buscar por nome, telefone, e-mail ou CNPJ...");

    fireEvent.change(campo, { target: { value: "v" } });
    await act(async () => { vi.advanceTimersByTime(500); });
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.change(campo, { target: { value: "vi" } });
    fireEvent.change(campo, { target: { value: "vida" } });
    await act(async () => { vi.advanceTimersByTime(299); });
    expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/conversations/search-contacts?q=vida");

    vi.useRealTimers();
    const opcao = await screen.findByText("Vida Natural");
    fireEvent.click(opcao.closest("button")!);
    expect(onEscolher).toHaveBeenCalledWith(expect.objectContaining({ id: "lead-9", cnpj: "12345678000190" }));
  });

  it("mostra o lead escolhido no gatilho", () => {
    render(
      <LeadPicker selecionado={{ id: "l", name: "Iago", phone: "553199" }} onEscolher={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /Iago/ })).toBeTruthy();
  });

  it("erro do servidor aparece em vez de 'nenhum lead'", async () => {
    global.fetch = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) }) as Response) as unknown as typeof fetch;
    render(<LeadPicker selecionado={null} onEscolher={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Selecione o lead/ }));
    fireEvent.change(screen.getByPlaceholderText("Buscar por nome, telefone, e-mail ou CNPJ..."), { target: { value: "vida" } });
    expect(await screen.findByText("Não foi possível buscar. Tente de novo.")).toBeTruthy();
  });
});
```

- [ ] **Step 2: ver falhar.**

- [ ] **Step 3: `lead-picker.tsx`**

```tsx
"use client";

/**
 * Seletor de lead dos modais de venda e orçamento (modo `pickLead`).
 *
 * Antes carregava `/api/leads` inteiro e filtrava no browser — o PostgREST
 * corta em 1.000 linhas, então quem estava fora das 1.000 mais recentes não
 * existia para o seletor. Agora cada busca vai ao servidor
 * (`/api/conversations/search-contacts`, a mesma da lista de conversas), com
 * respiro entre as teclas.
 *
 * Limite conhecido: a busca é sobre conversas, dentro dos canais do usuário —
 * lead sem conversa não aparece. Para venda isso é o esperado (o vendedor
 * vende para quem conversou).
 */
import { useEffect, useState } from "react";
import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { CONTACT_SEARCH_MIN_LEN } from "@/lib/contact-search";
import type { DadosDeContato } from "./lead-cliente";

export interface LeadEscolhido extends DadosDeContato {
  id: string;
}

export const ATRASO_BUSCA_MS = 300;

/** Conversas de `search-contacts` → um lead por id, na ordem recebida. */
export function leadsDaBusca(linhas: unknown): LeadEscolhido[] {
  if (!Array.isArray(linhas)) return [];
  const vistos = new Set<string>();
  const out: LeadEscolhido[] = [];
  for (const linha of linhas) {
    const l = (linha as { leads?: LeadEscolhido | null } | null)?.leads;
    if (!l?.id || vistos.has(l.id)) continue;
    vistos.add(l.id);
    out.push({
      id: l.id,
      name: l.name ?? null,
      phone: l.phone ?? null,
      email: l.email ?? null,
      cnpj: l.cnpj ?? null,
      razao_social: l.razao_social ?? null,
    });
  }
  return out;
}

interface LeadPickerProps {
  selecionado: LeadEscolhido | null;
  onEscolher: (lead: LeadEscolhido) => void;
}

export function LeadPicker({ selecionado, onEscolher }: LeadPickerProps) {
  const [aberto, setAberto] = useState(false);
  const [termo, setTermo] = useState("");
  const [resultado, setResultado] = useState<{
    termo: string;
    leads: LeadEscolhido[];
    erro: boolean;
  } | null>(null);

  const q = termo.trim();
  const curto = q.length < CONTACT_SEARCH_MIN_LEN;

  useEffect(() => {
    if (curto) return;
    let vivo = true;
    const timer = setTimeout(() => {
      fetch(`/api/conversations/search-contacts?q=${encodeURIComponent(q)}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
        .then((d) => {
          if (vivo) setResultado({ termo: q, leads: leadsDaBusca(d), erro: false });
        })
        .catch(() => {
          if (vivo) setResultado({ termo: q, leads: [], erro: true });
        });
    }, ATRASO_BUSCA_MS);
    return () => {
      vivo = false;
      clearTimeout(timer);
    };
  }, [q, curto]);

  const atual = !curto && resultado?.termo === q ? resultado : null;
  const buscando = !curto && !atual;

  return (
    <Popover open={aberto} onOpenChange={setAberto}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex w-full h-[37px] items-center justify-between bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
        >
          <span className={selecionado ? "truncate" : "text-[#8a8a8a]"}>
            {selecionado
              ? (selecionado.name ?? selecionado.phone ?? "Lead selecionado")
              : "Selecione o lead"}
          </span>
          <ChevronDownIcon className="size-4 shrink-0 text-[#8a8a8a]" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="p-0" portal={false}>
        <div className="p-2 border-b border-[#eee]">
          <Input
            autoFocus
            value={termo}
            onChange={(e) => setTermo(e.target.value)}
            placeholder="Buscar por nome, telefone, e-mail ou CNPJ..."
            className="h-8 text-[14px]"
          />
        </div>
        <div className="max-h-64 overflow-y-auto p-1">
          {curto && (
            <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">
              Digite ao menos {CONTACT_SEARCH_MIN_LEN} letras para buscar.
            </div>
          )}
          {buscando && <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">Buscando...</div>}
          {atual?.erro && (
            <div className="px-2 py-3 text-[13px] text-[#c41c1c]">
              Não foi possível buscar. Tente de novo.
            </div>
          )}
          {atual && !atual.erro && atual.leads.length === 0 && (
            <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">Nenhum lead encontrado.</div>
          )}
          {atual?.leads.map((l) => (
            <button
              key={l.id}
              type="button"
              onClick={() => {
                onEscolher(l);
                setAberto(false);
                setTermo("");
              }}
              className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[14px] hover:bg-[#f4f2ee]"
            >
              <span className="min-w-0">
                <span className="block truncate">{l.name ?? l.phone}</span>
                {l.name && l.phone && (
                  <span className="block text-[11px] text-[#7b7b78] truncate">{l.phone}</span>
                )}
              </span>
              {selecionado?.id === l.id && <CheckIcon className="size-4 shrink-0" />}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
```

- [ ] **Step 4: venda** — remover `leads`, `leadPickerOpen`, `leadQuery`, o `fetch("/api/leads")`,
os imports de `Popover`, `Input`?(fica — usado no formulário), `leadMatchesSearch`,
`ChevronDownIcon`; `interface LeadOption` sai. Novo estado
`const [leadEscolhido, setLeadEscolhido] = useState<LeadEscolhido | null>(null);`. O bloco
"Lead selector" vira:

```tsx
            {pickLead && !isEditing && (
              <div>
                <label className={fieldLabel}>Lead *</label>
                <LeadPicker
                  selecionado={leadEscolhido}
                  onEscolher={(l) => {
                    setSelectedLeadId(l.id);
                    setLeadEscolhido(l);
                    setRespostaCliente(null);
                    setDealId("");
                    setCreatingDeal(false);
                    setNewDealTitle("");
                    setNewDealPipeline("");
                  }}
                />
              </div>
            )}
```

e o pré-preenchimento usa o lead buscado por id, com o escolhido como reserva:
`defaults={defaultsDoContato(leadCliente ?? leadEscolhido)}`.

- [ ] **Step 5: orçamento** — mesma troca (estado `leadEscolhido`, `LeadPicker`, `onEscolher`
faz `setSelectedLeadId`, `setLeadEscolhido`, `setDealId("")`), remove `leads`/`leadQuery`/
`leadPickerOpen`/`fetch("/api/leads")`/`leadMatchesSearch`/`ChevronDownIcon`/`Popover`.
`defaults={defaultsDoContato(leadCliente ?? leadEscolhido)}`.

- [ ] **Step 6: rodar** `lead-picker.test.tsx` e os quatro testes dos modais → PASS.
- [ ] **Step 7: commit** — `feat(vendas): seletor de lead busca no servidor em vez da lista inteira (P4.6)`

---

### Task 8 (4.7): aba "Linha do tempo" no `contact-detail.tsx`

**Files:** Modify `frontend/src/components/conversas/contact-detail.tsx`

`LeadTimeline` é criado em paralelo pelo P3 (`frontend/src/components/leads/lead-timeline.tsx`,
`export function LeadTimeline({ leadId }: { leadId: string })`). Neste worktree o arquivo **não
existe** — o import fica pendente até a integração (plano mestre, Task 4.7). Por isso não há
vitest do `contact-detail` aqui: ele não resolveria o módulo. O componente é coberto pelos testes
do P3.

- [ ] **Step 1:** `type TabKey = "perfil" | "notas" | "campanhas" | "metricas" | "timeline";`
  e em `TABS` acrescentar `{ key: "timeline", label: "Histórico" }` (rótulo curto: cinco abas
  em 320 px; `title="Linha do tempo"` no botão).
- [ ] **Step 2:** `import { LeadTimeline } from "@/components/leads/lead-timeline";` e no corpo:
  `{activeTab === "timeline" && <LeadTimeline leadId={lead.id} />}`.
- [ ] **Step 3:** eslint no arquivo (com flock).
- [ ] **Step 4: commit** — `feat(conversas): aba linha do tempo do lead na conversa (P4.7)`

---

### Verificação final (superpowers:verification-before-completion)

```bash
cd /root/crm-wt/cs-p4/frontend
flock /root/crm-wt/_heavy.lock npx vitest run \
  src/components/sales src/components/quotes src/components/conversas/chat-view.test.tsx
flock /root/crm-wt/_heavy.lock npx eslint \
  src/components/sales src/components/quotes src/components/conversas/contact-detail.tsx
```

Esperado: todos os testes de `sales/` e `quotes/` passando (18 existentes + os novos), eslint sem
erros nos arquivos alterados.

## Fora do P4 (para o relatório)

- `frontend/src/lib/supabase/conversation-enrichment.ts:8` (`LEAD_FIELDS`): não precisa mudar
  para o P4 funcionar (lemos por id), mas incluir `ja_era_cliente, ja_era_cliente_fonte` ali
  deixaria o dado disponível para P5/lista sem nova consulta. Opcional.
- `GET /api/leads/[id]` não existe; o P4 usa o client Supabase do browser. Se a integração
  preferir rota, é um GET no `app/api/leads/[id]/route.ts` (fora do P4).
- `lead-detail-modal.tsx` (P3) e `deal-detail-sidebar.tsx` também abrem o `SaleCreateModal`:
  herdam o pré-preenchimento, o painel lateral e o "Já é cliente?" sem mudança.
