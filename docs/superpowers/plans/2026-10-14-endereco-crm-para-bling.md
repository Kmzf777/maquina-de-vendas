# Endereço do CRM vai para o Bling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Endereço estruturado na ficha do lead que, ao ser salvo completo, atualiza o endereço do(s) contato(s) vinculado(s) no Bling; o modal de venda/orçamento vem com esse endereço.

**Architecture:** Colunas novas em `leads` (cep, logradouro, numero, complemento, bairro, municipio, uf). O PATCH `/api/leads/[id]` (Next) grava, regrava `leads.endereco` formatado e, se mudou endereço e está completo, chama o backend `POST /api/bling/contacts/address`, que para cada vínculo em `lead_bling_contacts` faz GET+PUT no Bling trocando só `endereco.geral` (reaproveita `_corpo_do_put`). Resultado volta por conta na resposta do PATCH e a ficha mostra a mensagem.

**Tech Stack:** FastAPI + supabase-py (pytest), Next.js App Router (vitest), Supabase Postgres.

**Spec:** `docs/superpowers/specs/2026-10-14-endereco-crm-para-bling-design.md`

**Nota sobre a master atual:** o furo 3 da spec (contato existente no `create_contact` descartava o endereço) JÁ foi corrigido em `df163c28`/`3ab7d674` (`_atualizar_existente`). Não reimplementar; a Task 2 só garante que continua coberto.

**Comandos:**
- Backend (em `backend/`): `python -m pytest -q -m "not integration" -p no:cacheprovider` (usar o venv/python disponível; se faltar dependência, `pip install -r requirements-dev.txt` num venv local do worktree).
- Frontend (em `frontend/`): `npm ci` (uma vez), `npx vitest run <arquivo>`, `npm run type-check`, `npm run test`, `npm run build`.

---

### Task 1: Migração aditiva das colunas de endereço

**Files:**
- Create: `supabase/migrations/20261014_leads_endereco_estruturado.sql`

- [ ] **Step 1: Escrever a migração**

```sql
-- Endereço estruturado do lead (cartão b3788533). Aditiva: nada é apagado.
-- `leads.endereco` (texto livre, legado) continua e passa a ser regravado
-- formatado pelo PATCH /api/leads/[id] quando estes campos mudam.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS cep text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS logradouro text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS numero text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS complemento text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS bairro text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS municipio text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS uf text;
NOTIFY pgrst, 'reload schema';
```

- [ ] **Step 2: Commit** — `git add supabase/migrations/20261014_leads_endereco_estruturado.sql && git commit -m "feat(leads): colunas de endereço estruturado"`

(Não aplicar em produção neste turno; é passo do turno de publicação.)

---

### Task 2: Backend — `sync_lead_address` e endpoint

**Files:**
- Modify: `backend/app/bling/contacts.py` (novas funções depois de `_atualizar_existente`)
- Modify: `backend/app/bling/router.py` (novo endpoint depois de `create_contact_endpoint`)
- Test: `backend/tests/test_bling_contact_address.py` (novo), `backend/tests/test_bling_router.py`

Comportamento:
- `endereco_do_lead(lead: dict) -> dict | None`: monta `geral` = `{endereco: logradouro, numero, complemento, bairro, cep (só dígitos), municipio, uf (maiúscula)}` com strings aparadas; devolve `None` se faltar cep de 8 dígitos, logradouro, numero, municipio ou uf.
- `async atualizar_endereco(client, contact_id, geral) -> dict`: `GET /contatos/{id}`; se `data` vazio/não-dict levanta `BlingValidationError("contato não encontrado no Bling", status=404)`; `corpo = _corpo_do_put(atual, {"endereco": {"geral": geral}})`; se `corpo` igual ao atual sem `id` (mesma comparação de `_atualizar_existente`) não faz PUT; senão `PUT /contatos/{id}`. Devolve `{**corpo, "id": contact_id}`. Erros propagam.
- `async sync_lead_address(lead_id, client_factory=None) -> dict`: lê o lead (`leads` select `id, cep, logradouro, numero, complemento, bairro, municipio, uf`); sem lead → `{"status": "lead_not_found"}`; `geral is None` → `{"status": "incomplete"}`; lê vínculos `lead_bling_contacts` (`account, bling_contact_id`) do lead; nenhum → `{"status": "not_linked"}`. Para cada vínculo: `async with client_factory(account) as client` (default: `BlingClient(account=account)`), `atualizar_endereco`, `_upsert_mirror(resultado, account)` em `asyncio.to_thread`; resultado `{"account", "contact_id", "status": "updated"}`; qualquer `BlingError`/`Exception` vira `{"status": "error", "message": str(exc)}` e loga warning — uma conta falhar não impede a outra. Retorno `{"status": "updated" se todas updated, "partial" se algumas, "error" se nenhuma, "contas": [...]}`.
- Router: `class AddressSyncIn(BaseModel): lead_id: str` e `@router.post("/contacts/address")` → `await contacts.sync_lead_address(body.lead_id)`; `lead_not_found` → 404; senão 200 com o dict.

- [ ] **Step 1: Testes que falham** em `backend/tests/test_bling_contact_address.py`. Reusar `FakeSupabase` e `_CONTATO_BLING` importando de `tests.test_bling_contacts` (ou copiar o mínimo se o import não funcionar com o `pytest.ini`). Casos:

```python
import asyncio
import app.bling.contacts as ct
from app.bling.errors import BlingServerError

LEAD = {"id": "L1", "cep": "38400-100", "logradouro": " Av. Rondon Pacheco ", "numero": "100",
        "complemento": "", "bairro": "Centro", "municipio": "Uberlândia", "uf": "mg"}

def test_endereco_do_lead_completo_normaliza():
    g = ct.endereco_do_lead(LEAD)
    assert g == {"endereco": "Av. Rondon Pacheco", "numero": "100", "complemento": "",
                 "bairro": "Centro", "cep": "38400100", "municipio": "Uberlândia", "uf": "MG"}

def test_endereco_do_lead_incompleto_devolve_none():
    for falta in ("cep", "logradouro", "numero", "municipio", "uf"):
        assert ct.endereco_do_lead({**LEAD, falta: ""}) is None
    assert ct.endereco_do_lead({**LEAD, "cep": "3840"}) is None

class Cliente:
    def __init__(self, contato, erro=None):
        self.contato, self.erro, self.puts = contato, erro, []
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, path, params=None):
        if self.erro: raise self.erro
        return {"data": dict(self.contato)}
    async def put(self, path, json=None):
        self.puts.append((path, json)); return {}

def test_atualizar_endereco_troca_so_o_endereco():
    contato = {"id": 9, "nome": "X", "numeroDocumento": "1", "email": "a@b.c",
               "endereco": {"geral": {"endereco": "Velha", "numero": "1", "cep": "1"},
                            "cobranca": {"endereco": "Cob"}}}
    c = Cliente(contato)
    out = asyncio.run(ct.atualizar_endereco(c, 9, ct.endereco_do_lead(LEAD)))
    path, corpo = c.puts[0]
    assert path == "/contatos/9" and "id" not in corpo
    assert corpo["nome"] == "X" and corpo["email"] == "a@b.c"
    assert corpo["endereco"]["geral"]["endereco"] == "Av. Rondon Pacheco"
    assert corpo["endereco"]["cobranca"] == {"endereco": "Cob"}
    assert out["id"] == 9
```

Mais testes de `sync_lead_address` com `FakeSupabase` devolvendo o lead e dois vínculos (`default`, `secundaria`) e `client_factory` que devolve um `Cliente` por conta:
  - incompleto → `{"status": "incomplete"}` e nenhum cliente criado;
  - sem vínculo → `not_linked`;
  - duas contas → dois PUTs, dois upserts em `bling_contacts` com `account` certo, `status == "updated"`;
  - conta `default` com `erro=BlingServerError(...)` → `default` error, `secundaria` updated, `status == "partial"`.
  E em `test_bling_router.py`: endpoint chama `contacts.sync_lead_address` (monkeypatch) e devolve o dict; `lead_not_found` → `JSONResponse` 404.

- [ ] **Step 2:** rodar `python -m pytest -q tests/test_bling_contact_address.py` → FAIL (atributos inexistentes).
- [ ] **Step 3:** implementar as três funções em `contacts.py` e o endpoint em `router.py` conforme o comportamento acima, no estilo do arquivo (docstrings em pt sem acento, `asyncio.to_thread` para supabase, logger `[BLING]`; não logar dado do cliente além de ids).
- [ ] **Step 4:** testes novos PASS; suíte do backend inteira verde (inclui os testes `test_existente_*` do furo 3).
- [ ] **Step 5: Commit** — `feat(bling): endereço do lead atualiza o contato vinculado no Bling`

---

### Task 3: Frontend — `lib/lead-address.ts`

**Files:**
- Create: `frontend/src/lib/lead-address.ts`, `frontend/src/lib/lead-address.test.ts`

```ts
import { UFS, cepDigits } from "@/lib/bling-contact-form";

export const ADDRESS_FIELDS = ["cep", "logradouro", "numero", "complemento", "bairro", "municipio", "uf"] as const;
export type AddressField = (typeof ADDRESS_FIELDS)[number];
export type LeadAddress = Partial<Record<AddressField, string | null>>;

const t = (v: string | null | undefined) => (v ?? "").trim();

export function isAddressComplete(a: LeadAddress): boolean {
  return cepDigits(a.cep).length === 8 && !!t(a.logradouro) && !!t(a.numero)
    && !!t(a.municipio) && (UFS as readonly string[]).includes(t(a.uf).toUpperCase());
}

export function hasAddressChange(body: Record<string, unknown>): boolean {
  return ADDRESS_FIELDS.some((f) => f in body);
}

/** "Rua X, 123, Sala 2 - Bairro - Cidade/UF 38400-100" (vazios somem). */
export function formatAddress(a: LeadAddress): string | null {
  const cep = cepDigits(a.cep);
  const rua = [t(a.logradouro), t(a.numero), t(a.complemento)].filter(Boolean).join(", ");
  const cidade = [t(a.municipio), t(a.uf).toUpperCase()].filter(Boolean).join("/");
  const cepFmt = cep.length === 8 ? `${cep.slice(0, 5)}-${cep.slice(5)}` : cep;
  const s = [rua, t(a.bairro), [cidade, cepFmt].filter(Boolean).join(" ")].filter(Boolean).join(" - ");
  return s || null;
}

/** Resposta do ViaCEP → campos do lead; `null` se erro/CEP inexistente. */
export function fromViaCep(json: unknown): LeadAddress | null {
  if (!json || typeof json !== "object" || (json as { erro?: unknown }).erro) return null;
  const j = json as Record<string, string>;
  return { logradouro: j.logradouro || "", bairro: j.bairro || "", municipio: j.localidade || "", uf: j.uf || "" };
}

/** Preenche só os campos vazios (não pisa no que o vendedor digitou). */
export function mergeViaCep(atual: LeadAddress, via: LeadAddress): LeadAddress {
  const out = { ...atual };
  for (const [k, v] of Object.entries(via) as [AddressField, string][]) if (!t(out[k]) && v) out[k] = v;
  return out;
}
```

- [ ] **Step 1:** testes (vitest) cobrindo: completo/incompleto (cada campo obrigatório faltando, CEP com 7 dígitos, UF inválida "XX"), `formatAddress` com e sem complemento/bairro e vazio → `null`, `fromViaCep({erro: true})` → null, mapeamento `localidade→municipio`, `mergeViaCep` não sobrescreve campo preenchido, `hasAddressChange`.
- [ ] **Step 2:** FAIL. **Step 3:** criar o arquivo acima. **Step 4:** PASS. **Step 5: Commit** — `feat(leads): utilitários de endereço estruturado`

---

### Task 4: Frontend — PATCH `/api/leads/[id]` sincroniza com o Bling

**Files:**
- Modify: `frontend/src/app/api/leads/[id]/route.ts`
- Test: `frontend/src/app/api/leads/[id]/route.address.test.ts` (novo; copiar o helper `instalar` de `route.phone.test.ts`)

Comportamento (depois do `update` bem-sucedido, `data` = lead atualizado):
- Antes do update: se `hasAddressChange(body)`, normalizar `body.cep = cepDigits(body.cep) || null` quando presente e `body.uf = uf.toUpperCase()` quando presente.
- Depois do update, se `hasAddressChange(body)`:
  - `endereco = formatAddress(data)`; se diferente de `data.endereco` e houver algum campo estruturado preenchido, `update({endereco})` no lead e refletir em `data.endereco`.
  - se `!isAddressComplete(data)` → `bling_endereco = { status: "incomplete" }`.
  - senão `fetch(\`${backend}/api/bling/contacts/address\`, {method: "POST", body: JSON.stringify({lead_id: id}), signal: AbortSignal.timeout(20000)})`; resposta ok → `bling_endereco = await resp.json()`; falha de rede/timeout/!ok → `{ status: "error", message: "Bling indisponível — tente salvar de novo" }`.
  - Responder `NextResponse.json({ ...data, bling_endereco })`.
- Sem campo de endereço no body: comportamento idêntico ao atual (nenhum fetch novo).

- [ ] **Step 1:** testes: (a) body só com `name` → nenhum `fetch` ao backend; (b) endereço completo → `fetch` em `/api/bling/contacts/address` com `{lead_id}` e resposta contém `bling_endereco` do backend e `update` com `endereco` formatado; (c) incompleto → sem fetch, `bling_endereco.status === "incomplete"`; (d) backend rejeita/lança → `status: "error"` e o PATCH continua 200. Mockar `global.fetch` com `vi.fn`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS + `route.phone.test.ts` continua verde. **Step 5: Commit** — `feat(leads): salvar endereço completo atualiza o contato no Bling`

---

### Task 5: Frontend — bloco de endereço na ficha do lead

**Files:**
- Create: `frontend/src/components/leads/lead-address-fields.tsx`
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx`, `frontend/src/app/(authenticated)/leads/page.tsx`, `frontend/src/lib/types.ts`
- Modify: `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`
- Test: `frontend/src/components/leads/lead-detail-modal.test.tsx` (ajustar/estender)

- `types.ts`: `Lead` ganha `cep, logradouro, numero, complemento, bairro, municipio, uf?: string | null` (opcionais).
- `LeadAddressFields` props: `{ value: LeadAddress; legado?: string | null; onChange: (patch: LeadAddress) => void }`. Grade: CEP (mostra "Buscando…" enquanto consulta), Rua, Número, Complemento, Bairro, Cidade, UF (maxLength 2). Ao CEP atingir 8 dígitos: `fetch("https://viacep.com.br/ws/<cep>/json/")` → `fromViaCep` → `onChange(mergeViaCep(value, via))`; erro de rede ignorado. Se nenhum campo estruturado preenchido e `legado`, mostra abaixo: `Endereço antigo: <legado>` (texto cinza). Mesmas classes de input do modal (`bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] ...`).
- `lead-detail-modal.tsx`: remover `{ label: "Endereco", field: "endereco" }` da lista B2B; renderizar logo abaixo um bloco "Endereço" com `LeadAddressFields` ligado ao `form` (via `updateField` para cada chave). `onSave` passa a ser `Promise<unknown>`; `handleSave` lê `res?.bling_endereco` e mostra uma linha de status ao lado do botão: `updated` → "Endereço atualizado no Bling"; `partial` → "Endereço atualizado em parte do Bling: <mensagens>"; `error` → "Falha ao atualizar no Bling: <message ou mensagens>"; `incomplete` → "Endereço incompleto — não enviado ao Bling"; `not_linked` → "Lead sem contato no Bling — endereço salvo só no CRM".
- `leads/page.tsx` `handleSaveLead`: `const r = await fetch(...); return r.json().catch(() => null);`.
- `crm-perfil-tab.tsx`: trocar o `EditableField` "Endereco" por sete `EditableField` (CEP, Rua, Número, Complemento, Bairro, Cidade, UF) salvando cada campo com `onSaveField` (o PATCH sincroniza quando completar). Ajustar o tipo usado ali, se necessário.

- [ ] **Step 1:** teste no `lead-detail-modal.test.tsx`: renderiza campos CEP/Rua/...; ao salvar com `onSave` resolvendo `{bling_endereco: {status: "updated"}}` aparece "Endereço atualizado no Bling"; com `legado` e campos vazios aparece "Endereço antigo:". Ver o padrão de render já usado no arquivo.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS, `crm-perfil-tab.p4.test.tsx` verde, `npm run type-check` limpo. **Step 5: Commit** — `feat(leads): ficha com endereço estruturado e busca por CEP`

---

### Task 6: Frontend — modal de venda/orçamento vem com o endereço

**Files:**
- Modify: `frontend/src/components/sales/lead-cliente.ts`, `frontend/src/components/sales/lead-cliente.test.ts`
- Modify: `frontend/src/lib/bling-contact-form.ts`, `frontend/src/lib/bling-contact-form.test.ts`
- Modify: `frontend/src/components/sales/bling-contact-resolver.tsx` (campo Complemento)

- `DadosDeContato` ganha os 7 campos de endereço. Nova const `COLUNAS_ENDERECO = "cep, logradouro, numero, complemento, bairro, municipio, uf"`; `COLUNAS_CLIENTE` passa a incluir `COLUNAS_ENDERECO`; o fallback de coluna inexistente continua com `COLUNAS_BASE` (sem migração, endereço só não vem).
- `defaultsDoContato` acrescenta `cep: cepDigits(lead.cep)`, `logradouro`, `numero`, `complemento`, `bairro`, `municipio`, `uf` (trim, uf maiúscula, `""` quando nulo).
- `ContactForm`/`blankContactForm`/`ContactAddress` ganham `complemento`; `buildContactPayload` envia `complemento` em `geral` (não obrigatório, não entra nas validações).
- Resolver: input "Complemento" ao lado de "Número", mesmo padrão dos outros.

- [ ] **Step 1:** testes: `defaultsDoContato` com lead com endereço preenche todos os campos; sem endereço → strings vazias; `buildContactPayload` leva `complemento`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS. **Step 5: Commit** — `feat(vendas): cadastro do contato no Bling vem com o endereço do lead`

---

### Task 7: Verificação final em modo teste

- [ ] Backend: suíte inteira verde (`python -m pytest -q -m "not integration" -p no:cacheprovider`).
- [ ] Frontend: `npm run type-check`, `npm run test`, `npm run build` verdes.
- [ ] Rodar o frontend local no worktree (`npm run dev`) e tirar prints com o script do central-claude: ficha de um lead com o bloco de endereço (CEP digitado e campos preenchidos pelo ViaCEP, sem salvar) e o modal de venda com o endereço. Não salvar nada (banco de produção sem as colunas ainda; nenhum PUT no Bling).
