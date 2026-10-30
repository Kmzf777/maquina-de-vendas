# Link `/conversas?lead_id=` que não abre a conversa do lead: design

Cartão 70d844a6 (BEEINSIDE CANSTRA CRM).

## Problema

Nas palavras do Rafael: "vou em /trafego, analiso todos os leads que chegaram e etc, quando vou
clicar em ver conversa, isso acontece". "Isso" é o CRM abrir só a lista de conversas, sem nenhuma
selecionada. O agente de consulta usa o mesmo link nos relatórios.

## O que o teste em massa mostrou (produção, 28 a 30/10/2026, conta do Rafael)

- PC, clique real em /trafego → campanha → lead → "Ver conversa": 43 de 45 leads abriram a conversa
  certa (Google, Meta, Sem rastreio). Em outros 25 leads, a URL colada direto abriu em todos.
- As 2 falhas (Micheli `0376d44a…`, Eduardo Inácio `92a08e4a…`, ambos em "Sem rastreio") são
  **leads sem nenhuma conversa** no banco. Nos últimos 30 dias são 39 leads assim, quase todos
  `origem_cadastro = bling_import` (comprou pelo Bling ou pela loja e nunca falou no WhatsApp).
- Celular (390 px): o link nunca abre o chat. A conversa fica marcada na lista, mas a tela continua na
  lista.

## Causas

1. **Lead sem conversa:** `/api/conversations?lead_id=` volta vazio e o deep-link desiste calado
   (`if (!conv) return;`), sem avisar nada.
2. **Celular:** o efeito do deep-link faz `setSelectedId`, mas não faz `setMobileView("chat")`, ao
   contrário do clique manual (`handleSelectConversation`).
3. **Link aberto já dentro de /conversas** (popup de SLA, notificação): `deepLinkApplied` é um ref
   que fica `true` para sempre depois do primeiro link, então o segundo é ignorado e continua a
   conversa anterior. Isso vem da leitura do código; o teste automático não confirmou com certeza.

## O que muda

Decisão do Rafael: "pode fazer o que for melhor". Prática de mercado: não esconder a ação, mostrar
desabilitada com o motivo em **texto visível**, não só em tooltip (Smashing Magazine, "Hidden vs. Disabled In UX").

1. **/conversas, deep-link** (`frontend/src/app/(authenticated)/conversas/page.tsx`):
   - Ao achar a conversa (na lista ou pelo fetch), seleciona **e** faz `setMobileView("chat")`.
   - O deep-link passa a valer por `lead_id` e não só uma vez: guarda o último `lead_id` aplicado em
     vez do booleano. Um link novo (outro lead) dentro de /conversas é aplicado de novo.
   - Lead sem conversa visível (nenhuma, só bloqueada ou de canal sem acesso; a API não distingue e
     não precisa): aviso na tela, no lugar do "Selecione uma conversa" no PC e no topo da lista no
     celular, com o texto: **"Este lead não tem conversa no WhatsApp."** e o link **"Abrir ficha do
     lead"** (`/leads?lead_id=<id>`). O aviso some quando o usuário seleciona outra conversa.
   - Falha de rede no fetch continua sem aviso de "sem conversa" (não dá para afirmar que não existe).
2. **/trafego, painel do lead** (`frontend/src/components/trafego/campaign-lead-panel.tsx`):
   - O botão "Ver conversa" fica desabilitado, com o texto visível "Sem conversa no WhatsApp", quando o
     overview diz que o lead não tem conversa visível. Enquanto o overview carrega, o botão segue
     habilitado (o /conversas cobre o caso com o aviso).
   - `GET /api/leads/[id]/overview` ganha o campo `has_conversation: boolean` (existe conversa do lead
     com `status <> 'blocked'` nos canais que o usuário pode ver, mesma regra do
     `/api/conversations`).

Os outros pontos que usam o link (vendas, orçamentos, busca, SLA, notificação, follow-up, dashboard)
não mudam: passam a receber o aviso do /conversas de graça.

## Fora do escopo

- Juntar leads duplicados ou criar conversa para lead do Bling.
- A lentidão ocasional do primeiro "Carregando conversas..." (vista 2 vezes no teste, >30 s).
- Mudar os relatórios do agente de consulta.

## Como testar em modo teste

- Worktree/branch `agente/70d844a6`. Testes unitários (vitest) no `frontend/`:
  - deep-link com conversa → seleciona e, no celular, mostra o chat (`mobileView = chat`);
  - deep-link de lead sem conversa → aviso "Este lead não tem conversa no WhatsApp." com link para a ficha;
  - segundo deep-link com outro `lead_id` na mesma montagem → troca a seleção;
  - falha de rede → sem aviso de "sem conversa";
  - painel do /trafego: `has_conversation: false` → botão desabilitado com o texto; `true` → habilitado;
  - rota overview: `has_conversation` respeita bloqueio e canais permitidos.
- `npm run build` e `npm test` do frontend verdes.
- CRM local (`next dev`) apontando para o Supabase de produção, usado só para leitura. As variáveis
  vêm do `.env.build` do CRM na VPS, copiadas para `frontend/.env.local` do worktree (fora do git,
  nunca impressas). Sem esse acesso, o modo teste fica nos testes unitários e no build, e os prints
  saem da produção depois da liberação. Prints em 1440 px e 390 px de: lead com conversa (Queijo da família
  `1a80f7a4…`), lead sem conversa (Micheli `0376d44a…`) e o painel do /trafego desse lead.
- Rodar o script de teste em massa (`clique.mjs`/`massa.mjs`) contra o local com a mesma amostra.

## Como publicar

- `git pull origin master` no branch, merge em `master`, `git push origin master`. O GitHub Actions
  (`deploy.yml`, job `deploy-crm`) refaz a imagem `canastra-crm` e atualiza o serviço `crm_crm`.
  Não mexe no backend (`canastra_api`/`canastra_worker`).
- Voltar atrás: `git revert` do merge + push (o Actions publica de novo), ou na VPS
  `docker service rollback crm_crm`.

## Como testar em produção

- Só leitura: abrir links e ver a tela. Nenhuma mensagem a cliente, venda, pedido, NF ou cobrança.
- Rodar o teste em massa de novo (clique real no /trafego, 1366 px e 390 px) com a mesma amostra,
  mais Micheli e Eduardo Inácio. Esperado: todos com conversa abrem no PC e no celular; os dois sem
  conversa mostram o aviso, e no /trafego o botão aparece desabilitado.
- Conferir `docker service ps crm_crm` e os logs do serviço sem erro novo.
