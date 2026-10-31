# Link `/conversas?lead_id=` que não abre a conversa do lead: design

Cartão 70d844a6 (BEEINSIDE CANSTRA CRM).

## Problema

Revisão de 31/10/2026: depois do teste em modo teste, o Rafael pediu mais duas coisas neste mesmo
cartão (escolheu "B: incluir neste cartão"):
- "leads que não possuem conversa, ao clicá-los, ao invés de apenas aparecer que o lead não tem
  conversa, ter um botão de iniciar conversa, com a opção de selecionar o número e a mensagem disparo"
  (seção 3).
- "lead entrou no dia 05/10/2026 e tinha uma venda dele registrada em 27/02/2026 [...] como impedir de
  exibir como ciclo fechado" (seção 4).

Pedido original: nas palavras do Rafael: "vou em /trafego, analiso todos os leads que chegaram e etc, quando vou
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

Os itens 1 e 2 já estão implementados e testados no branch (commits `a4c78c1b`, `e3e62ea5`,
`5817c7ec`). O item 2 muda com a seção 3: o botão deixa de ficar só desabilitado.

### 3. Iniciar conversa com lead sem conversa

Hoje o CRM não inicia conversa do zero: o disparo de modelo (`TemplateDispatchModal` →
`POST /api/conversations/[id]/send-template`) exige uma conversa existente.

- **Rota nova** `POST /api/leads/[id]/iniciar-conversa`
  (`frontend/src/app/api/leads/[id]/iniciar-conversa/route.ts`), corpo
  `{ channel_id, template_name, template_language_code, template_variables, template_body }`.
  Na ordem, antes de qualquer envio:
  1. usuário logado e com acesso ao canal (`getAllowedChannelIds`; admin vê todos), senão 401/403;
  2. canal existe e é `meta_cloud`, senão 400;
  3. lead existe, senão 404; telefone utilizável (só dígitos, de 10 a 13; `bling-…` não serve), senão
     400 "Lead sem telefone";
  4. lead não bloqueado nem com opt-out (`isLeadBlocked`, o mesmo guard do disparo atual), senão 403;
  5. acha a conversa do par lead+canal; se não existir, cria (`stage: 'secretaria'`,
     `status: 'active'`, sem `agent_profile_id`, igual ao `get_or_create_conversation` do backend).
     Conversa do par com `status = 'blocked'` dá 403;
  6. envia o modelo pela Meta e grava a mensagem e o `status: 'template_sent'` com o MESMO código do
     disparo atual, extraído para `frontend/src/lib/meta-template.ts` e usado pelas duas rotas (a rota
     antiga não muda de comportamento);
  7. se a Meta recusar, a conversa **criada nesta requisição** é apagada (só ela, e só se não tiver
     nenhuma mensagem) e a rota devolve 502 com o erro da Meta. Conversa que já existia não é tocada.
  Resposta 200: `{ conversation_id }`.
- **Quem atende a resposta do cliente** (decisão do Rafael, opção A): o mesmo de qualquer conversa
  daquele número. A conversa nasce sem perfil fixo, então vale o agente padrão do canal, com IA se o
  canal tiver IA ligada. Nenhuma regra nova no backend.
- **Tela, /conversas:** o aviso "Este lead não tem conversa no WhatsApp." ganha o botão **"Iniciar
  conversa"**. Ele abre um modal com: (1) escolha do número (canais `meta_cloud` que o usuário vê, de
  `/api/channels`); (2) os modelos aprovados desse número com as variáveis, reaproveitando o seletor
  do `TemplateDispatchModal` (extraído para um componente comum, sem mudar o modal atual); (3)
  "Enviar". Ao dar certo, a conversa nova entra na lista, fica selecionada e o chat abre (no celular
  também). Erro aparece no modal, com o texto da rota.
  Lead sem telefone utilizável: o aviso diz "Este lead não tem telefone para WhatsApp." e não mostra o
  botão (o link da ficha continua).
- **Tela, /trafego (painel do lead):** quando `has_conversation === false`, o botão vira **"Iniciar
  conversa"** (habilitado, estilo contornado) e leva a `/conversas?lead_id=<id>`, onde está o aviso
  com o botão. Sem telefone utilizável: botão desabilitado com o texto "Sem telefone para WhatsApp".
  O critério de telefone fica num helper único (`frontend/src/lib/telefone-whatsapp.ts`), usado pelas
  duas telas e pela rota.

### 4. Trilha do painel: venda de antes de o lead entrar não fecha o ciclo

Causa (Micheli `0376d44a…`): havia duas Michelis com o mesmo CNPJ, uma criada pelo Bling em
21/08/2026 com as compras de fevereiro e junho, e outra que chegou pelo WhatsApp em 05/10/2026. Em
06/10 a mesclagem automática (celular + CNPJ, evento `mesclagem`) manteve a de 05/10 e moveu para ela
as vendas e oportunidades da antiga. A trilha (`buildJourney` em `frontend/src/lib/lead-overview.ts`)
conta qualquer venda como "Comprou". No banco, 499 leads têm venda anterior à entrada (20 nos últimos
30 dias), todos com `ja_era_cliente = true`: a maioria são pedidos antigos importados do Bling, e 84
vêm de mesclagem.

- "Comprou" só conta venda não cancelada com `sold_at` a partir do **dia** de entrada do lead (data
  local de São Paulo de `created_at`; venda do mesmo dia conta).
- Venda anterior não alcança etapa nenhuma da trilha (nem pela regra de monotonicidade) e aparece numa
  linha abaixo dela: **"Já era cliente: N compra(s) antes de entrar, desde dd/mm/aaaa."**
- "Ciclo fechado — o lead comprou." só com venda a partir da entrada. Lead só com compras antigas
  mostra "Parou em …" como qualquer outro.
- A Micheli continua "Comprou 05/10/2026" (pedido pelo CRM no dia em que entrou) e ganha a linha "Já
  era cliente: 4 compras antes de entrar, desde 27/02/2026."
- Cards de Receita e Ticket do painel não mudam (continuam o total do lead).

## Fora do escopo

- Juntar leads duplicados ou mudar a regra de mesclagem (a data de entrada do lead que fica não muda).
- Botão de iniciar conversa para lead que já tem conversa em outro número (o botão só aparece para
  quem não tem nenhuma; a rota aceita qualquer par lead+canal, e o teste usa isso).
- Relatório de tráfego (receita por campanha) e cards de Receita/Ticket: não mudam.
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
- Seções 3 e 4, testes unitários: rota `iniciar-conversa` (sem acesso ao canal, canal não Meta, lead
  sem telefone, lead bloqueado, conversa bloqueada, cria e envia, reaproveita conversa existente, Meta
  recusa e apaga só a conversa criada, não apaga a que já existia); helper de telefone; modal (escolhe
  número, carrega os modelos daquele número, envia o corpo certo, mostra erro); aviso com e sem
  telefone; botão do /trafego nos três estados; `buildJourney` (venda antes da entrada não fecha o
  ciclo, venda no mesmo dia fecha, linha "Já era cliente" com N e data). A rota antiga `send-template`
  mantém o comportamento (testes dela verdes).
- **Envio real (uma mensagem, no modo teste, CRM local):** iniciar conversa do lead **Rafael**
  (`5ee7a58f…`, telefone 5534988861441, do próprio Rafael) no **NUMERO ARTHUR**, onde ele não tem
  conversa, com um modelo aprovado desse número. Pela rota, porque esse lead já tem conversa em outros
  números e não mostra o botão. Conferir: a mensagem chegou no celular do Rafael, a conversa foi criada
  no NUMERO ARTHUR com a mensagem e `status = 'template_sent'`, e ela abre no CRM. Não criar lead de
  teste duplicado (o mesmo telefone seria mesclado automaticamente).
- Tela do lead sem conversa com a Micheli (`0376d44a…`): modal aberto, número escolhido, modelos
  listados, **sem apertar Enviar**. Prints do aviso com o botão (1440 e 390), do modal, do painel do
  /trafego e da trilha da Micheli com a linha "Já era cliente".

## Como publicar

- `git pull origin master` no branch, merge em `master`, `git push origin master`. O GitHub Actions
  (`deploy.yml`, job `deploy-crm`) refaz a imagem `canastra-crm` e atualiza o serviço `crm_crm`.
  Não mexe no backend (`canastra_api`/`canastra_worker`): a rota nova é do Next.
- Voltar atrás: `git revert` do merge + push (o Actions publica de novo), ou na VPS
  `docker service rollback crm_crm`.

## Como testar em produção

- Só leitura: abrir links e ver a tela. Nenhuma mensagem a cliente, venda, pedido, NF ou cobrança.
  O único envio real do cartão é o do modo teste, para o celular do próprio Rafael. Em produção: abrir
  a conversa do Rafael no NUMERO ARTHUR criada no teste, e abrir o modal da Micheli **sem enviar**. A
  conversa de teste no NUMERO ARTHUR fica (é do Rafael e é real).
- Conferir a trilha da Micheli no painel do /trafego (linha "Já era cliente").
- Rodar o teste em massa de novo (clique real no /trafego, 1366 px e 390 px) com a mesma amostra,
  mais Micheli e Eduardo Inácio. Esperado: todos com conversa abrem no PC e no celular; os dois sem
  conversa mostram o aviso, e no /trafego o botão aparece desabilitado.
- Conferir `docker service ps crm_crm` e os logs do serviço sem erro novo.
