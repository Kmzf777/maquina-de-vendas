# Iniciar conversa com lead sem conversa + trilha sem venda de antes da entrada: plano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** seções 3 e 4 da spec `docs/superpowers/specs/2026-10-30-deep-link-conversa-lead-design.md`: botão "Iniciar conversa" (escolhe número + modelo, cria a conversa e envia) para lead sem conversa, e a trilha do painel do /trafego só fecha o ciclo com venda feita a partir da entrada do lead.

**Architecture:** tudo no Next (`frontend/`), sem backend. Rota nova `/api/leads/[id]/iniciar-conversa` (GET devolve lead + números disponíveis; POST cria a conversa e envia o modelo). O envio pela Meta e a gravação da mensagem saem da rota `send-template` para `lib/meta-template.ts`, usado pelas duas rotas. O seletor de modelo sai do `TemplateDispatchModal` para `TemplatePicker`, usado pelo modal antigo e pelo novo `IniciarConversaModal`. A trilha ganha `jaEraCliente` em `buildJourney`.

**Tech Stack:** Next.js App Router, React 19, Supabase JS (service key), Vitest + Testing Library.

Comandos em `frontend/` do worktree `C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\.claude\worktrees\agente-70d844a6`. Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

Ordem: **Task A** primeiro (contrato da rota e helper de telefone). Depois **Task B** e **Task C** em paralelo (arquivos diferentes). **Task D** é a verificação.

---

### Task A: helper de telefone, envio Meta compartilhado e rota iniciar-conversa

**Files:**
- Create: `frontend/src/lib/telefone-whatsapp.ts`, `frontend/src/lib/telefone-whatsapp.test.ts`
- Create: `frontend/src/lib/meta-template.ts`
- Modify: `frontend/src/app/api/conversations/[id]/send-template/route.ts` (passa a usar `meta-template.ts`; comportamento igual)
- Create: `frontend/src/app/api/leads/[id]/iniciar-conversa/route.ts`, `.../route.test.ts`

- [ ] **Step 1: helper de telefone (TDD)**

Teste `telefone-whatsapp.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { telefoneWhatsapp } from "./telefone-whatsapp";

describe("telefoneWhatsapp", () => {
  it("aceita número com DDI, com ou sem o 9", () => {
    expect(telefoneWhatsapp("5534988861441")).toBe("5534988861441");
    expect(telefoneWhatsapp("554991505316")).toBe("554991505316");
  });
  it("limpa máscara", () => {
    expect(telefoneWhatsapp("+55 (34) 98886-1441")).toBe("5534988861441");
  });
  it("recusa placeholder do Bling, vazio e curto/longo demais", () => {
    expect(telefoneWhatsapp("bling-18479369687")).toBeNull();
    expect(telefoneWhatsapp("")).toBeNull();
    expect(telefoneWhatsapp(null)).toBeNull();
    expect(telefoneWhatsapp("123456789")).toBeNull();
    expect(telefoneWhatsapp("55349888614411")).toBeNull();
  });
});
```

Implementação `telefone-whatsapp.ts`:

```ts
/**
 * Telefone utilizável para iniciar conversa no WhatsApp (cartão 70d844a6), ou null.
 * Lead importado do Bling sem celular vem como `bling-<id>`: isso não é telefone.
 * Critério único das telas (/conversas, /trafego) e da rota iniciar-conversa.
 */
export function telefoneWhatsapp(phone: string | null | undefined): string | null {
  if (!phone || /^bling-/i.test(phone.trim())) return null;
  const digitos = phone.replace(/\D/g, "");
  return digitos.length >= 10 && digitos.length <= 13 ? digitos : null;
}
```

Run `npx vitest run src/lib/telefone-whatsapp.test.ts`: falha antes, passa depois.

- [ ] **Step 2: extrair o envio Meta**

Criar `frontend/src/lib/meta-template.ts` movendo da rota `send-template`, SEM mudar comportamento:
- `sendTemplateViaMeta(config, to, templateName, languageCode, variables)`, igual ao de hoje;
- `registrarTemplateEnviado(supabase, { conversationId, leadId, stage, templateName, templateLanguageCode, templateBody, sentWamid })`: o bloco atual que resolve o `content` (corpo enviado pelo cliente, depois `message_templates`, depois Meta), insere a mensagem com os mesmos campos (`role`, `sent_by`, `metadata: { template: true, template_name }`, `wamid`, `delivery_status: "accepted"` só com wamid) e faz o update `status: "template_sent", last_msg_at`.
A rota `send-template` passa a chamar as duas funções. Rodar `npx vitest run "src/app/api/conversations/[id]/send-template/"`: os testes existentes continuam verdes sem alteração.

- [ ] **Step 3: testes da rota nova (falham)**

`frontend/src/app/api/leads/[id]/iniciar-conversa/route.test.ts`, no estilo do teste de `send-template` (mock de `@/lib/supabase/api`, `@/lib/supabase/lead-blocked`, `@/lib/supabase/channel-access` e `@/lib/meta-template`). Um Supabase falso por tabela (`leads`, `channels`, `conversations`, `messages`) que registra inserts e deletes. Casos, cada um um `it`:

GET:
1. devolve `{ lead: { id, name, phone, company }, telefone: "5534..." | null, canais: [{ id, name }] }`, só canais `meta_cloud` e, para não admin, só os de `getAllowedChannelIds`;
2. lead inexistente → 404; `ChannelAccessError` → 401.

POST (corpo `{ channel_id, template_name, template_language_code, template_variables, template_body }`):
3. sem `channel_id` ou `template_name` → 400;
4. canal fora dos permitidos → 403, sem enviar;
5. canal não `meta_cloud` → 400, sem enviar;
6. lead sem telefone (`bling-123`) → 400 com `"Lead sem telefone"`, sem enviar;
7. `isLeadBlocked` true → 403 com `MENSAGEM_LEAD_BLOQUEADO`, sem enviar;
8. conversa do par já existe com `status: "blocked"` → 403, sem enviar;
9. sem conversa do par → cria com `{ lead_id, channel_id, stage: "secretaria", status: "active" }`, chama `sendTemplateViaMeta` com o telefone limpo e `registrarTemplateEnviado` com a conversa criada; 200 `{ conversation_id }`;
10. conversa do par já existe (não bloqueada) → não cria, envia nela, 200 com o id dela;
11. Meta lança erro com conversa CRIADA nesta requisição → apaga essa conversa (delete por id, condicionado a não ter mensagens) e devolve 502 com a mensagem;
12. Meta lança erro com conversa que JÁ existia → não apaga nada, 502.

Run `npx vitest run "src/app/api/leads/[id]/iniciar-conversa/"` → FAIL (rota não existe).

- [ ] **Step 4: implementar a rota**

`frontend/src/app/api/leads/[id]/iniciar-conversa/route.ts`:

```ts
// Iniciar conversa com lead sem conversa (cartão 70d844a6). Cria a conversa do par
// lead+número e manda um modelo aprovado. Mesmos guards do disparo de modelo
// (send-template), e mais: acesso ao número e telefone utilizável. Se a Meta recusar,
// a conversa criada AQUI é desfeita — nunca a que já existia.
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { isLeadBlocked, MENSAGEM_LEAD_BLOQUEADO } from "@/lib/supabase/lead-blocked";
import { sendTemplateViaMeta, registrarTemplateEnviado } from "@/lib/meta-template";
import { telefoneWhatsapp } from "@/lib/telefone-whatsapp";
```

GET: `getAllowedChannelIds` (erro → 401); lead `select("id, name, phone, company")` por id (`maybeSingle`; null → 404); canais `select("id, name, provider").eq("provider", "meta_cloud")` filtrados pelos permitidos (null = todos), ordenados por nome; responde `{ lead, telefone: telefoneWhatsapp(lead.phone), canais: [{ id, name }] }`.

POST, nesta ordem: corpo (400); permitidos (401); canal `select("id, name, provider, provider_config")` (`maybeSingle`; ausente ou fora dos permitidos → 403; provider ≠ meta_cloud → 400); lead `select("id, phone, opt_out")` (404); `telefoneWhatsapp` null → 400 `{ error: "Lead sem telefone" }`; `isLeadBlocked(sb, lead.id, lead.opt_out)` → 403; conversa do par `select("id, status, stage").eq("lead_id").eq("channel_id").limit(1).maybeSingle()`: `blocked` → 403 `MENSAGEM_LEAD_BLOQUEADO`; inexistente → `insert({ lead_id, channel_id, stage: "secretaria", status: "active" }).select("id, stage").single()` e `criada = true`; `sendTemplateViaMeta(channel.provider_config, telefone, ...)` em try: no catch, se `criada`, apagar a conversa só se não houver mensagem dela (`messages` count head por `conversation_id` = 0 → `conversations.delete().eq("id", id)`), e devolver 502 `{ error }`; depois `registrarTemplateEnviado(...)` e 200 `{ conversation_id }`.

Run os testes da rota → 12 passed. Rodar também `send-template` e `telefone-whatsapp`.

- [ ] **Step 5: lint, tipos e commit**

`npx eslint <arquivos tocados> && npx tsc --noEmit -p .` e commit:
`feat(conversas): rota para iniciar conversa com lead sem conversa (envio de modelo compartilhado)`.

---

### Task B: tela /conversas — aviso com "Iniciar conversa" e o modal

**Files:**
- Create: `frontend/src/components/conversas/template-picker.tsx` (+ `.test.tsx`)
- Modify: `frontend/src/components/conversas/template-dispatch-modal.tsx` (usa o picker; comportamento igual)
- Create: `frontend/src/components/conversas/iniciar-conversa-modal.tsx` (+ `.test.tsx`)
- Modify: `frontend/src/components/conversas/lead-sem-conversa-aviso.tsx`
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx` e `page.deeplink.test.tsx`

Contrato da rota (Task A): `GET /api/leads/<id>/iniciar-conversa` → `{ lead: {id,name,phone,company}, telefone: string|null, canais: {id,name}[] }`; `POST` mesmo caminho, corpo `{ channel_id, template_name, template_language_code, template_variables, template_body }` → 200 `{ conversation_id }` ou `{ error }` com 4xx/5xx.

- [ ] **Step 1: `TemplatePicker` (TDD)**

Extrair do `TemplateDispatchModal` a lista de modelos + variáveis + prévia:

```ts
export interface TemplateEscolhido {
  template_name: string;
  template_language_code: string;
  template_variables: Record<string, string> | null;
  template_body: string;
}
export function TemplatePicker(props: {
  channelId: string;
  lead: { name?: string | null; phone?: string; company?: string | null };
  onChange: (t: TemplateEscolhido | null) => void;
}): JSX.Element
```

Busca `/api/channels/<channelId>/templates` (de novo quando `channelId` muda), mostra "Buscando templates...", erro, "Nenhum template aprovado encontrado.", e a lista com inputs e prévia exatamente como hoje. `onChange` recebe o payload pronto (mesma montagem de `template_variables` e `template_body` do `handleSend` atual) a cada mudança de seleção ou input; `null` sem seleção. O `TemplateDispatchModal` passa a ser cabeçalho + `<TemplatePicker>` + rodapé, com o mesmo envio para `send-template`.
Testes do picker: lista os modelos do canal; selecionar chama `onChange` com nome, idioma e corpo resolvido; variável manual entra em `template_variables`; trocar `channelId` busca de novo.

- [ ] **Step 2: `IniciarConversaModal` (TDD)**

```ts
export function IniciarConversaModal(props: {
  leadId: string;
  onClose: () => void;
  onIniciada: (conversationId: string) => void;
}): JSX.Element
```

Ao abrir faz o GET; mostra "Carregando…"; título "Iniciar conversa", subtítulo com nome e telefone do lead. Campo "Número" (`<select>` com `canais`; se houver um só, já vem escolhido). Abaixo, `<TemplatePicker key={canal} channelId={canal} lead={lead} onChange=...>`. "Enviar" desabilitado sem número ou modelo. Envia o POST; 200 chama `onIniciada(conversation_id)`; erro mostra o `error` da rota no rodapé, em vermelho, e mantém o modal aberto. Sem canais: "Você não tem número do WhatsApp para iniciar conversa." Mesmo visual do `TemplateDispatchModal` (overlay, cartão `bg-[#faf9f6]`, botões).
Testes: carrega e lista números; escolher número busca modelos daquele número; enviar manda o corpo certo para `/api/leads/L1/iniciar-conversa` e chama `onIniciada("conv-novo")`; erro 403 aparece no modal; sem canais mostra a mensagem.

- [ ] **Step 3: aviso com botão (TDD)**

`LeadSemConversaAviso` passa a receber `{ leadId, onIniciar }`. Faz o GET da rota (só para saber o telefone). Com `telefone`: texto "Este lead não tem conversa no WhatsApp.", botão **"Iniciar conversa"** (estilo do botão preto do CRM) que chama `onIniciar`, e o link "Abrir ficha do lead". Sem telefone: "Este lead não tem telefone para WhatsApp." + link da ficha, sem botão. Enquanto carrega ou se o GET falhar: o texto de hoje + link, sem botão. Mantém `data-testid="lead-sem-conversa"`.

- [ ] **Step 4: ligar na página**

Em `page.tsx`: estado `iniciarLeadId: string | null`; o aviso (as duas instâncias, celular e PC) recebe `onIniciar={() => setIniciarLeadId(avisoSemConversa)}`; renderiza `<IniciarConversaModal>` quando `iniciarLeadId`. `onIniciada(convId)`: `fetchConversationById(convId)` → se vier, `ensureInList(conv)`, `setSelectedId(conv.id)`, `setMobileView("chat")`, `dispensarAvisoSemConversa()`, fecha o modal.
Em `page.deeplink.test.tsx`, novo caso: lead sem conversa + GET com telefone → botão "Iniciar conversa" → modal abre (dublê do modal chamando `onIniciada("conv-novo")`) → `fetchConversationById` chamado com `conv-novo` e o chat do celular fica visível. Ajustar o mock do fetch dos casos existentes para responder o GET da rota.

- [ ] **Step 5: verificação e commit**

`npx vitest run src/components/conversas/ "src/app/(authenticated)/conversas/"`, eslint dos arquivos tocados, `npx tsc --noEmit -p .`. Commit: `feat(conversas): iniciar conversa com lead sem conversa, escolhendo numero e modelo`.

---

### Task C: painel do /trafego — trilha e botão

**Files:**
- Modify: `frontend/src/lib/lead-overview.ts` (`Journey`, `buildJourney`), `frontend/src/lib/lead-overview.test.ts`
- Modify: `frontend/src/components/trafego/campaign-lead-panel.tsx` (`JourneyRail` e botão), `campaign-lead-panel.test.tsx`

- [ ] **Step 1: testes da trilha (falham)** em `lead-overview.test.ts`, usando a fábrica de overview do próprio arquivo:
  - lead criado em `2026-10-05T13:45:25Z` com vendas em `2026-02-27T12:00:00Z` e `2026-06-01T12:00:00Z` e nada depois → `comprou.reached === false`, `stalledAt !== null`, `jaEraCliente = { compras: 2, desde: "2026-02-27T12:00:00Z" }`, e as vendas antigas não alcançam "oportunidade" pela monotonicidade (sem deal → `oportunidade.reached === false`);
  - mesma lead com venda em `2026-10-05T10:00:00Z` (mesmo dia em São Paulo, antes da hora de criação) → `comprou.reached === true`, `comprou.at === "2026-10-05T10:00:00Z"`, `jaEraCliente.compras === 2`;
  - venda em `2026-10-05T02:00:00Z` (= 04/10 23:00 em São Paulo) com lead criado `2026-10-05T13:45:25Z` → conta como antes da entrada;
  - venda cancelada antes da entrada não conta em `jaEraCliente`;
  - sem venda anterior → `jaEraCliente === null`.
- [ ] **Step 2: implementar.** `Journey` ganha `jaEraCliente: { compras: number; desde: string } | null`. Em `buildJourney`: dia local de entrada = data `YYYY-MM-DD` de `o.lead.created_at` em `America/Sao_Paulo` (`Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" })`); venda válida (não cancelada) é "depois" se o dia local de `sold_at` ≥ dia de entrada. "comprou" usa só as de depois; as de antes vão para `jaEraCliente` (contagem e a mais antiga). Comentário curto citando a mesclagem (cartão 70d844a6).
- [ ] **Step 3: painel.** Em `JourneyRail`, abaixo da linha "Ciclo fechado"/"Parou em", quando `journey.jaEraCliente`: `<div className="mt-1 text-[12px] text-[#7b7b78]">Já era cliente: {n} compra{n>1?"s":""} antes de entrar, desde {fmtDate(desde)}.</div>`.
- [ ] **Step 4: botão do painel.** Hoje (commit e3e62ea5) `has_conversation === false` desabilita com "Sem conversa no WhatsApp". Passa a ser: `has_conversation === false` e `telefoneWhatsapp(data.lead.phone)` → botão **"Iniciar conversa"** habilitado, estilo contornado (`border border-[#111111] text-[#111111] bg-white hover:bg-[#f0eee9]`), que faz `go("/conversas?lead_id=<id>")`; `has_conversation === false` sem telefone → desabilitado, texto **"Sem telefone para WhatsApp"**, estilo cinza atual; demais casos → "Abrir conversa" como hoje. Atualizar os 3 testes do botão em `campaign-lead-panel.test.tsx` (o de "Sem conversa no WhatsApp" vira dois: com telefone → "Iniciar conversa" habilitado; com `phone: "bling-1"` → "Sem telefone para WhatsApp" desabilitado) e somar um teste da linha "Já era cliente" no painel.
- [ ] **Step 5:** `npx vitest run src/lib/lead-overview.test.ts src/components/trafego/`, eslint, `tsc`. Commit: `fix(trafego): trilha nao fecha ciclo com venda de antes da entrada; botao iniciar conversa`.

---

### Task D: verificação (modo teste)

- [ ] `npx vitest run` (suíte inteira), `npx tsc --noEmit -p .`, `npm run build`.
- [ ] CRM local (`next start -p 3100`, `.env.local` copiado do `.env.build` da VPS, apagado no fim).
- [ ] Envio real único: lead Rafael `5ee7a58f-8c8e-4bcc-8963-9022eeaf67c7` no NUMERO ARTHUR `a4cba780-5cb1-4f0a-a4bf-a4dee9203044`, logado no CRM local, via `fetch` do POST da rota com um modelo aprovado do NUMERO ARTHUR. Conferir no banco a conversa nova, a mensagem e `status = 'template_sent'`; abrir `/conversas?lead_id=5ee7a58f…` e ver a conversa do NUMERO ARTHUR.
- [ ] Micheli `0376d44a…`: aviso com botão (1440 e 390), modal com número escolhido e modelos, **sem enviar**; painel do /trafego com "Iniciar conversa" e a linha "Já era cliente: 4 compras antes de entrar, desde 27/02/2026."
- [ ] Repetir os testes em massa do link (local.mjs, dentro.mjs).
