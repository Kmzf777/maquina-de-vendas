# ValerIA Recuperação — estado da entrega e runbook de teste

**Branch:** `feat/valeria-recuperacao-botoes` (base `origin/master = 537e0519`) · **NÃO pushed**
**Spec:** `docs/superpowers/specs/2026-09-09-valeria-recuperacao-botoes-design.md`
**Suíte:** `3956 passed, 3 skipped, 0 failed` (baseline antes deste trabalho: 3472)

---

## 1. O que está pronto

| Camada | Onde | Estado |
|---|---|---|
| Fluxo declarativo (trilhas, rótulos, textos, tags) | `backend/app/button_flow/flows.py` | ✅ |
| Motor de decisão puro | `backend/app/button_flow/engine.py` | ✅ |
| Detector de autoresponder | `backend/app/button_flow/autoreply.py` | ✅ |
| Classificador LLM estreito (6 classes, ~300 tok) | `backend/app/button_flow/classifier.py` | ✅ |
| Efeitos no CRM (tags, opt-out, handoff, recontato, move de card) | `backend/app/button_flow/effects.py` | ✅ |
| Runner (todo o I/O) | `backend/app/button_flow/runner.py` | ✅ |
| Gate no pipeline de inbound | `backend/app/buffer/processor.py:1448` | ✅ |
| `send_interactive_buttons` nos 3 providers | `backend/app/whatsapp/` | ✅ |
| Payload custom por botão no disparo | `backend/app/broadcast/worker.py` | ✅ |
| Preflight dos rótulos | `backend/app/templates/preflight.py` | ✅ |
| Erro 131049 (cap de marketing) → requeue +24h | `backend/app/broadcast/worker.py` | ✅ |
| Frontend: seletor de agente em canal humano, chip de clique no chat | `frontend/src/` | ✅ |

**Aplicado em produção nesta madrugada:**

- Migrations `20260820_button_flow_agent.sql` e `20260909_recuperacao_stages_optout.sql`.
  Confere: `agent_profiles.kind` ✓ · `conversations.flow_state` ✓ · `leads.opt_out_at/_channel/_evidence` ✓ ·
  8 tags `Recuperação: …` ✓ · 3 etapas de desfecho no funil (order_index 8/9/10) ✓
- Agente **Bot Reativação** — `agent_profile_id = e3aa4422-f5ff-4eb6-a1a3-fb83c607a136`, `kind='button_flow'`.
- **4 templates criados e APROVADOS** na WABA, e registrados em `message_templates` no canal do João:

| Template | Categoria (real) | Botões |
|---|---|---|
| `recuperacao_pedido_v1` | **marketing** ⚠️ pedi utility, a Meta reclassificou | Retomar o pedido · Quero outro item · Parar mensagens |
| `recuperacao_estoque_v1` | marketing | Preciso repor · Ainda tenho estoque · Parar mensagens |
| `recuperacao_cadastro_v1` | **utility** (sobreviveu) | Manter cadastro · Atualizar dados · Parar mensagens |
| `recuperacao_lembrete_v1` | marketing | Preciso repor · Ainda tenho estoque · Parar mensagens |

> A reclassificação do `pedido_v1` é a 29ª desta conta e confirma ao vivo a decisão D3 da spec:
> **orçar como marketing.** Custo do disparo completo continua irrisório (~R$ 315).

---

## 2. Como testar de manhã

O kill switch está **desligado por padrão**. Nada roda até você ligar.

### Passo 1 — subir o backend dev com a feature ligada

```powershell
# backend/.env.local
RECUPERACAO_ENABLED=on
```
Depois: task `Run All Dev (CRM & Backend)` (ou `scripts/start-backend.ps1`).

### Passo 2 — garantir que seu número está no Dev Router

O número de teste é **5534988861441**. Ele precisa estar na whitelist Redis de produção para o
webhook ser desviado para o dev, senão a produção processa:

```
POST /api/dev/whitelist/5534988861441   →  dev_url = https://dev.canastrainteligencia.com
```
(nunca `172.18.0.1:8001` nem `127.0.0.1:8001` — CLAUDE.md §4.)

### Passo 3 — apontar a conversa para o agente de botões

O gate só dispara quando a **conversa** aponta para o perfil `button_flow`. É isso que o disparo faz
em produção; para o teste manual, faça à mão:

```sql
UPDATE conversations
   SET agent_profile_id = 'e3aa4422-f5ff-4eb6-a1a3-fb83c607a136',
       flow_state = NULL
 WHERE lead_id = (SELECT id FROM leads WHERE phone = '5534988861441')
   AND channel_id = 'a3a607b1-6bff-4370-8609-b275eef270dd';   -- canal do João
```

### Passo 4 — disparar o template

Pelo CRM: **/campanhas → novo disparo → canal NUMERO JOÃO → agente "Bot Reativação" →
template `recuperacao_estoque_v1`**.
O seletor de agente agora aparece em canal humano e lista **só** perfis `button_flow`.

Variáveis do `recuperacao_estoque_v1`: `{{1}}` primeiro nome · `{{2}}` razão social ·
`{{3}}` mês/ano da última compra · `{{4}}` produto.

### Passo 5 — o roteiro de teste

| Você faz | Esperado |
|---|---|
| toca **Preciso repor** | 1 bolha: `perfeito, <nome> / você levava <produto> — hoje ele está <preço> a unidade / já chamei o João aqui`. Tag `Recuperação: Quente`, handoff registrado, card → **Quer repor**, `ai_enabled=false` |
| toca **Ainda tenho estoque** | `Beleza! Quando faz sentido eu te chamar de novo?` + botões **Em 30 / 60 / 90 dias** |
| toca **Em 60 dias** | `combinado, em 60 dias…`, `metadata.recontatar_em` = hoje+60d, card → **Recontato agendado** |
| toca **Parar mensagens** | `entendido, não te mando mais nada por aqui.` · `opt_out=true` + `opt_out_at` + `opt_out_channel='whatsapp_button'` + `opt_out_evidence` · card → **Descadastrado** |
| digita texto qualquer (1ª vez) | reoferece os 3 botões (mensagem interativa) |
| digita texto de novo | silêncio + tag `Recuperação: Atendimento humano` + IA desligada |
| digita **"me tira da lista"** | opt-out imediato, **mesmo com o Gemini fora** (curto-circuito determinístico antes do LLM) |
| digita **"não fiz nenhum pedido"** | pede desculpa, oferece o botão de saída, marca `pretexto_contestado` |

Conferência rápida:
```sql
SELECT flow_state FROM conversations WHERE lead_id = (SELECT id FROM leads WHERE phone='5534988861441');
SELECT opt_out, opt_out_at, opt_out_channel, opt_out_evidence FROM leads WHERE phone='5534988861441';
SELECT message_type, content, metadata FROM messages WHERE lead_id=(SELECT id FROM leads WHERE phone='5534988861441') ORDER BY created_at DESC LIMIT 10;
```

Para resetar entre rodadas: `UPDATE conversations SET flow_state=NULL …` e
`UPDATE leads SET opt_out=false, ai_enabled=true, opt_out_at=NULL … WHERE phone='5534988861441'`.

---

## 3. O que falta antes de disparar para valer

Ordenado por bloqueio.

### 3.1 Bloqueante — decisão sua

| # | O quê | Por quê |
|---|---|---|
| 1 | **Rotacionar o `META_ACCESS_TOKEN`** | Ele estava em texto puro em `scripts/create_utility_templates.py:12`, num arquivo untracked que o `.gitignore` **não** cobre (`*.env*` não casa com `.py`). Tirei do arquivo; não foi commitado em momento nenhum. Mas eu o li, e ele esteve no disco em claro — trate como exposto. |
| 2 | **Honrar os opt-outs pendentes** | `scripts/recuperacao/honrar_optouts_pendentes.sql` está pronto e **não executado**. Medido e reconferido em 09/09: **53 cliques no botão de saída em 48 leads distintos** que seguem com `opt_out=false`. São pessoas que já pediram para parar e hoje entrariam na campanha. Rodar **antes** de qualquer disparo. |
| 3 | **Rodar o backfill de metadata** | `scripts/recuperacao/backfill_metadata.py` (dry-run por padrão). **Verifiquei: `produto_top1` está vazio nos 1.208 leads.** Sem ele o template T-B perde `{{4}}` e a bolha do clique positivo perde produto e preço — que é a maior alavanca medida do desenho. |

### 3.2 Não bloqueante, mas eu recomendo

- `scripts/recuperacao/corrigir_deals_reposicao.sql` — realoca os deals que foram parar no funil
  errado por causa do bug de nome em `leads/reposicao.py` (já corrigido no código).
- **Poda de contactabilidade antes do disparo**: 241 fixos + 16 não-BR + 4 inválidos + 66
  institucionais. Sem ela, ~21-25% falha com `131026` — foi o que aconteceu nos três disparos
  históricos (19,2%, 33% e 50%).
- **Excluir quem comprou nos últimos 90 dias** (47 leads, um deles comprou em 06/09). As etapas de
  recência estão congeladas em 08/08 — recalcule de `sales` no momento do disparo.

### 3.3 Piloto recomendado

**39 leads** — os celulares válidos de `pedido_sem_faturar`. Maior intenção, menor risco.
Gates antes de liberar o próximo lote: entrega **≥ 85%** · `Parar mensagens` **≤ 5%** ·
resposta **≥ 6%**. Teto **≤ 150/dia**.

---

## 4. Decisões que tomei por você (defaults da spec §12)

Todas reversíveis; me diga se discorda de alguma.

| # | Decisão | Default adotado |
|---|---|---|
| Q1 | Desconto para quem volta? | **Não.** A oferta é memória + reposição + preço de tabela. Pedido de desconto → handoff. |
| Q2 | Frete grátis? | **O agente nunca fala de frete.** Há três versões incompatíveis em circulação (código diz uma coisa, o João já disse duas outras). Quem cota é o João. |
| Q4 | Qual número? | **O do João** (`553491461669`). Elimina a troca de número, que custa 26% dos leads. |
| Q5 | Os 182 com "Débito vencido"? | **Entram, sem nenhuma menção a débito.** Os 11 acima de R$ 5.000 saem para conferência manual. |
| Q7 | Os 665 de 36m+? | **Trilha de higienização, sem venda.** Quem clicar "Manter cadastro" vira opt-in registrado para uma 2ª campanha. |
| Q8 | `lead_sem_compra` e `ativo_0_3m`? | **Nenhum dos dois** na v1. |
| Q9 | Identidade | Assina **"João, do Café Canastra"**. Sem nome próprio, não conversa. Se perguntarem se é robô, confirma. |
| Q10 | Preço no 1º toque pós-clique? | **Sim**, e só do item que ele já comprou. |

---

## 5. O que deliberadamente NÃO está no escopo

- Worker de re-disparo automático a partir de `recontatar_em` (a data é gravada; a fila fica visível
  na etapa "Recontato agendado").
- Métricas por botão na UI de broadcast — na v1, SQL direto sobre `messages.message_type='button'`.
- Ampliar o catálogo do agente além dos 32 SKUs ativos (o Bling tem 444).
- **Nenhuma mensagem foi enviada a nenhum lead real.**

---

## 6. Furo conhecido que eu não fechei

O botão **"Iniciar"** do CRM chama a rota **Next.js** `/api/broadcasts/[id]/start`, que faz
`update({status:'running'})` direto no Supabase e **nunca encosta na rota FastAPI**. Ou seja: o
preflight (que agora valida os rótulos do template contra `flows.py`) só roda para quem chamar o
backend. Corrigir isso é migrar o start para o FastAPI — mexe no caminho de disparo de todas as
campanhas, não só desta, e preferi não fazer isso sem você.

Enquanto não for corrigido: **confira os rótulos do template no CRM antes de disparar.** Os quatro
templates criados já estão corretos e travados por teste.
