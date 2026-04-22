# Valéria MVP Pilot — Rehearsal + Piloto Warm + (Condicional) Tools de Fechamento

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demonstrar a Valéria executando o ciclo completo (lead frio → qualificação → conversa → o mais próximo possível do fechamento) em leads reais controlados, dentro de 3-4 dias, com o mínimo de infra nova.

**Arquitetura:** Plano em duas fases. **Fase 1 (operacional, 1-2 dias)** — rehearsal manual via dev router + piloto com 5-10 leads warm reais, ajustes inline de prompt conforme gaps aparecem. **Fase 2 (condicional, 2-3 dias)** — se a Fase 1 mostrar que qualificação funciona mas Valéria para no handoff humano, adicionar 2-3 tools mínimas de fechamento (`gerar_link_pagamento`, `registrar_pedido_simples`) para a IA conseguir conduzir até o "sim".

**Tech Stack:** Python 3 + FastAPI (backend existente), Supabase (leads/conversations/messages), Redis (dev router whitelist), OpenAI GPT-4.1-mini (modelo atual), WhatsApp Cloud API.

**Princípio MVP:** nenhuma refatoração arquitetural. Reusar o que já existe em `backend/app/agent/tools.py`, `backend/app/agent/orchestrator.py`, `backend/app/broadcast/worker.py`. Se precisar escolher entre "consertar prompt" e "refatorar código", consertar prompt.

---

## Contexto

A Valéria está pré-launch. A arquitetura funciona em L3 (stage-based agent com tools), orquestrador único, 4 categorias, handoff humano via tool. O dono do negócio quer ver um ciclo completo de venda. Não queremos construir infra (eval harness, workflows duráveis, memória persistente) antes de demonstrar que o core funciona em mundo real.

A Fase 1 é o caminho mais curto até esse artefato demonstrável. A Fase 2 só dispara se o diagnóstico da Fase 1 indicar fechamento como o gap crítico — não executar preventivamente.

---

## Fase 1 — Rehearsal Manual + Piloto Warm

**Objetivo:** Ao fim do dia 2, ter 5-10 transcrições reais mostrando Valéria conduzindo leads até qualificação ou além, documento de gaps observados, e recomendação clara se Fase 2 vale executar.

### Task 1.1: Preparar lista de 5 arquétipos de lead e cenários

**Files:**
- Create: `docs/superpowers/plans/pilot/2026-04-20-rehearsal-scripts.md`

- [ ] **Step 1: Escrever os 5 arquétipos num arquivo markdown**

Cada arquétipo deve incluir: persona (1-2 linhas), primeira resposta ao template outbound, 3-5 objeções/perguntas típicas que o lead faria, critério de "passou" (ex: chegou em stage correto, recebeu catálogo, pediu preço). Arquétipos mínimos:

```markdown
# Arquétipos para rehearsal

## A1 — Cafeteria pequena (ATACADO clássico)
Persona: dono de cafeteria em BH, 1 loja, compra 10kg/mês de um torrefador local.
Primeira resposta ao template: "oi, vi a mensagem. o que voces tem de cafe?"
Objeções esperadas: "qual o preço?", "tem amostra?", "qual o MOQ?", "entrega pra BH?"
Critério de passou: Valéria chega no stage atacado, envia fotos do catálogo, dá preço consistente, pergunta volume.

## A2 — Empreendedor com marca própria (PRIVATE_LABEL)
Persona: influenciador de café que quer lançar a própria marca.
Primeira resposta: "vocês fazem marca própria?"
Objeções: "quantidade mínima pra private label?", "quanto custa embalagem personalizada?", "posso usar meu design?"
Critério: Valéria transita pro stage private_label, explica o serviço, encaminha humano.

## A3 — Multi-intent (ATACADO + PRIVATE_LABEL)
Persona: tem cafeteria hoje, quer lançar marca própria em 2027.
Primeira resposta: "tenho uma cafeteria mas também penso em criar minha marca de café. da pra falar dos dois?"
Critério: Valéria NÃO trava num stage só; reconhece os dois interesses (modo de falha A1 da avaliação estratégica).

## A4 — Objetor de preço (ATACADO com resistência)
Persona: lead que já tem fornecedor e tá curioso mas cético.
Primeira resposta: "ja tenho fornecedor, mas me conta o que voces tem de diferente"
Objeções: "o meu tá em R$X, voces cobram mais caro?", "em quantos dias entrega?"
Critério: Valéria não desiste na primeira resistência, entra em diagnóstico, apresenta diferencial.

## A5 — Exportação exploratória
Persona: pessoa em Portugal perguntando se dá pra importar pra café que vai abrir em Lisboa.
Primeira resposta: "vou abrir um cafe em Lisboa, voces exportam?"
Critério: Valéria reconhece EXPORTAÇÃO, não trata como CONSUMO pessoal, encaminha humano com contexto completo.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/pilot/2026-04-20-rehearsal-scripts.md
git commit -m "docs: add rehearsal archetypes for Valéria MVP pilot"
```

---

### Task 1.2: Validar que o dev router está pronto e whitelist tem seu número

**Files:**
- Read only (nenhuma modificação): `backend/app/webhook/dev_router.py` (ou equivalente)

- [ ] **Step 1: Confirmar whitelist Redis**

Rode no host do dev:
```bash
docker exec -it <redis-container> redis-cli SMEMBERS dev:phone_routes
```

Expected: seu número de celular (ou número de teste controlado) deve aparecer na lista. Se não aparecer:

```bash
docker exec -it <redis-container> redis-cli SADD dev:phone_routes "+55DDNNNNNNNNN"
```

- [ ] **Step 2: Confirmar que backend dev está rodando**

VS Code task: `Run All Dev (CRM & Backend)`. Ou manual:
```bash
cd backend && uvicorn app.main:app --reload --env-file .env.local --port 8001
```

Expected: log de startup sem erros, endpoint `/health` retorna 200.

- [ ] **Step 3: Teste smoke — mandar 1 mensagem do seu celular**

Mande "oi" pra o número do canal de teste. Acompanhe log do dev (`backend/logs/` ou stdout). Expected: ver no log que o dev router pegou a mensagem, não a produção.

**Sem commit nesta task — é só validação operacional.**

---

### Task 1.3: Rehearsal — rodar os 5 arquétipos manualmente

**Files:**
- Modify inline (se necessário): `backend/app/agent/prompts/valeria_inbound/*.py`, `backend/app/agent/prompts/valeria_outbound/*.py`

- [ ] **Step 1: Criar broadcast de teste com 1 lead (você mesmo)**

Pelo CRM ou script, criar um broadcast outbound com o template atual, `agent_profile_id` = Valéria Outbound, lead = seu número. Disparar.

Expected: chega template no seu WhatsApp.

- [ ] **Step 2: Rodar o arquétipo A1**

Responder como A1 descrito no arquivo de rehearsal. Levar a conversa até onde o critério de "passou" diz. Anotar no mesmo arquivo:
- Onde a Valéria travou (se travou)
- O que soou "bot" (frase específica, não geral)
- O que foi bom (pra não mexer)

- [ ] **Step 3: Se achou gap crítico, consertar prompt inline**

Critério de "crítico": Valéria disse preço errado, travou num loop, recusou informação que deveria dar, soou ofensiva/robótica. Se crítico, abra o prompt correspondente (ex: `backend/app/agent/prompts/valeria_outbound/atacado.py`) e ajuste o texto. Hot-reload do uvicorn já pega.

Se não é crítico (só um "podia ser melhor"), anotar no doc e seguir.

- [ ] **Step 4: Commit do ajuste de prompt (se houve)**

```bash
git add backend/app/agent/prompts/
git commit -m "fix(prompt): ajuste no stage <X> para caso do arquétipo A1 rehearsal"
```

- [ ] **Step 5: Repetir Steps 2-4 para A2, A3, A4, A5**

Mesmo fluxo para cada arquétipo. Um arquétipo por vez — não batch.

- [ ] **Step 6: Fechar o rehearsal com um relatório curto**

Adicionar seção ao arquivo `2026-04-20-rehearsal-scripts.md`:

```markdown
# Resultado Rehearsal

| Arquétipo | Passou | Gaps críticos | Gaps menores |
|---|---|---|---|
| A1 | ✓/✗ | ... | ... |
| A2 | ... | ... | ... |
...

## Decisão
- [ ] Ir pro piloto warm (Task 1.4) — confiança aceitável
- [ ] Mais uma rodada de rehearsal — N gaps críticos ainda abertos
```

- [ ] **Step 7: Commit do relatório**

```bash
git add docs/superpowers/plans/pilot/2026-04-20-rehearsal-scripts.md
git commit -m "docs: relatório do rehearsal da Valéria — $(date +%Y-%m-%d)"
```

---

### Task 1.4: Piloto com 5-10 leads warm reais

**Pré-requisito:** decisão "ir pro piloto" da Task 1.3.

**Files:**
- Create: `docs/superpowers/plans/pilot/2026-04-20-pilot-log.md`

- [ ] **Step 1: Selecionar 5-10 leads warm**

Critérios (pelo menos 3 dos 4): (a) relacionamento prévio com a Canastra, (b) perfil B2B plausível (cafeteria, private label, revendedor), (c) mix de categorias — 3-5 atacado, 1-2 private label, 1 export se possível, (d) alguém que você confia não causar estrago reputacional se algo der errado.

Listar em `pilot-log.md` com: nome, empresa, categoria esperada, número, por que escolheu.

- [ ] **Step 2: Criar broadcast real**

Pelo CRM da Canastra, broadcast outbound com `agent_profile_id` = Valéria Outbound, template validado, lista dos leads acima. Lembrete: dev router NÃO deve interceptar esses números (retirar da whitelist Redis se estiverem).

- [ ] **Step 3: Disparar e monitorar ao vivo**

Ao longo do dia, observar:
- Conversas no CRM (UI existente de conversas realtime, plan 2026-04-09)
- Logs do backend prod
- Eventuais chamadas pro seu celular dos próprios leads (reação orgânica)

- [ ] **Step 4: Para cada conversa, registrar no pilot-log**

```markdown
## Lead L1 — <nome> — <empresa>
- Categoria esperada: ATACADO
- Categoria acertada pela Valéria: ✓/✗
- Stage final alcançado: <secretaria/atacado/private_label/exportacao/consumo>
- Encaminhou pra humano: ✓/✗ (em que momento?)
- Lead pediu preço: ✓/✗ — Valéria deu preço certo? ✓/✗
- Lead mandou áudio/imagem: ✓/✗ — como Valéria tratou?
- Bot-score subjetivo (1-10) — soou humano?
- Próximo passo real (se houver): conversão, reunião marcada, cotação enviada, silêncio.
```

- [ ] **Step 5: Consolidação ao fim do dia 2**

Escrever no final do pilot-log:

```markdown
# Consolidação — <data>

## Números
- Leads abordados: N
- Responderam em < 24h: M
- Chegaram no stage correto: P
- Encaminharam pra humano com qualificação útil: Q
- Pediram preço/produto/cotação: R
- Fecharam ou marcaram próximo passo: S

## Diagnóstico do gap
- [ ] Qualificação funciona, fechamento é o gap → **ativar Fase 2**
- [ ] Qualificação ainda tem falha → mais rehearsal, NÃO Fase 2
- [ ] Tudo funcionou até o ponto possível sem tools novas → **ativar Fase 2 pra subir a régua**
- [ ] Funcionou bem o suficiente pra demo ao dono como está → **parar e apresentar**
```

- [ ] **Step 6: Commit do piloto completo**

```bash
git add docs/superpowers/plans/pilot/2026-04-20-pilot-log.md
git commit -m "docs: piloto warm da Valéria — log e consolidação"
```

- [ ] **Step 7: Apresentar ao dono**

Gate de decisão. Materiais: pilot-log.md + 3-5 screenshots das melhores conversas + 1-2 screenshots das piores (transparência). Decisão do dono sobre:
- Executar Fase 2 agora?
- Escalar pra 50 leads antes?
- Pausar e consertar prompt mais fundo?

---

## Fase 2 — Tools Mínimas de Fechamento (Condicional)

**Gatilho:** diagnóstico "Qualificação funciona, fechamento é o gap" OU "subir a régua pra demo mais impressionante" na Task 1.4 Step 5.

**Não começar Fase 2 antes de aprovar o gatilho com o dono.**

**Escopo proposital:** 2 tools apenas. Resistir à tentação de adicionar 10. Cada tool adicional é mais um lugar pra bug + um prompt mais confuso.

### Task 2.1: Tool `gerar_link_pagamento`

Gera um link de pagamento estático (pode ser link de checkout fixo por categoria ou via integração Mercado Pago/Stripe — o que a Canastra já usa). MVP = link fixo hardcoded por categoria e por faixa de volume. Refinamento vem depois.

**Files:**
- Modify: `backend/app/agent/tools.py` (adicionar ao TOOLS_SCHEMA e ao execute_tool)
- Modify: `backend/app/agent/prompts/valeria_outbound/atacado.py` (instruir uso da tool no fechamento)
- Modify: `backend/app/agent/prompts/valeria_inbound/atacado.py` (idem)
- Test: `backend/tests/test_agent_tools.py` (arquivo existente — estender)

- [ ] **Step 1: Escrever teste falhando**

Adicionar em `backend/tests/test_agent_tools.py`:

```python
import pytest
from app.agent.tools import execute_tool

@pytest.mark.asyncio
async def test_gerar_link_pagamento_atacado_retorna_link():
    result = await execute_tool(
        "gerar_link_pagamento",
        {"categoria": "atacado", "volume_kg": 10},
        lead_id="lead-test-id",
        phone="+5500000000",
        conversation_id="conv-test-id",
    )
    assert "http" in result.lower(), "tool deve retornar um link de pagamento"
    assert "10" in result or "atacado" in result.lower(), "contexto mínimo deve aparecer no retorno"


@pytest.mark.asyncio
async def test_gerar_link_pagamento_categoria_invalida_retorna_erro():
    result = await execute_tool(
        "gerar_link_pagamento",
        {"categoria": "invalida", "volume_kg": 10},
        lead_id="lead-test-id",
        phone="+5500000000",
        conversation_id="conv-test-id",
    )
    assert "não" in result.lower() or "nao" in result.lower() or "erro" in result.lower()
```

- [ ] **Step 2: Rodar e confirmar falha**

```bash
cd backend && pytest tests/test_agent_tools.py::test_gerar_link_pagamento_atacado_retorna_link -v
```

Expected: FAIL — `Tool gerar_link_pagamento nao reconhecida`.

- [ ] **Step 3: Adicionar schema da tool em `tools.py`**

Em `backend/app/agent/tools.py`, dentro de `TOOLS_SCHEMA` (depois do último item existente, antes do fechamento `]`):

```python
    {
        "type": "function",
        "function": {
            "name": "gerar_link_pagamento",
            "description": "Gera um link de pagamento para o lead fechar a compra. Use SOMENTE quando o lead confirmou intenção de comprar e já tem volume definido.",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {
                        "type": "string",
                        "enum": ["atacado", "private_label"],
                        "description": "Categoria do produto",
                    },
                    "volume_kg": {
                        "type": "number",
                        "description": "Volume em kg que o lead quer comprar",
                    },
                },
                "required": ["categoria", "volume_kg"],
            },
        },
    },
```

Adicionar na mesma função, ao final antes do `return f"Tool ... nao reconhecida"`:

```python
    elif tool_name == "gerar_link_pagamento":
        categoria = args.get("categoria")
        volume = args.get("volume_kg", 0)
        LINKS = {
            "atacado": "https://pagamento.cafecanastra.com/atacado",
            "private_label": "https://pagamento.cafecanastra.com/private-label",
        }
        link = LINKS.get(categoria)
        if not link:
            return f"categoria {categoria} nao tem link de pagamento configurado"
        save_message(
            lead_id,
            "system",
            f"Link de pagamento gerado ({categoria}, {volume}kg): {link}",
            conversation_id=conversation_id,
        )
        return f"Link de pagamento ({categoria}, {volume}kg): {link}"
```

Também adicionar `"gerar_link_pagamento"` nas listas de stages `atacado` e `private_label` dentro de `get_tools_for_stage`:

```python
    stage_tools = {
        "secretaria": ["salvar_nome", "mudar_stage"],
        "atacado": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto", "gerar_link_pagamento"],
        "private_label": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto", "gerar_link_pagamento"],
        ...
    }
```

> **Importante:** os URLs de pagamento acima são placeholders de exemplo. Na execução real, confirmar com o dono/financeiro qual URL canônica usar (pode ser link de checkout do ERP, Mercado Pago, Pagar.me, etc.). Substituir antes do merge. Sem invenção.

- [ ] **Step 4: Rodar testes e confirmar passa**

```bash
cd backend && pytest tests/test_agent_tools.py::test_gerar_link_pagamento_atacado_retorna_link tests/test_agent_tools.py::test_gerar_link_pagamento_categoria_invalida_retorna_erro -v
```

Expected: PASS nos dois.

- [ ] **Step 5: Atualizar prompts para ensinar a Valéria a usar a tool**

Em `backend/app/agent/prompts/valeria_outbound/atacado.py` e `backend/app/agent/prompts/valeria_inbound/atacado.py`, adicionar uma etapa de fechamento (posição: depois da apresentação de preços, antes de `encaminhar_humano`):

```
ETAPA N — FECHAMENTO:
Quando o lead confirmar intencao clara de comprar E tiver volume definido em kg:
1. Gere o link de pagamento chamando gerar_link_pagamento(categoria, volume_kg)
2. Envie o link numa mensagem curta: "fechou! aqui o link pro pagamento: <link>. qualquer duvida me avisa."
3. So chame encaminhar_humano se o lead preferir falar com pessoa ou pedir forma alternativa de pagamento.

NAO gere link de pagamento sem volume confirmado. Se o lead nao falou volume, pergunte antes.
```

Adaptação equivalente em `private_label.py` (inbound e outbound). EXPORTAÇÃO e CONSUMO não recebem a tool agora — são casos complexos demais pra fechamento automático em MVP.

- [ ] **Step 6: Teste manual da tool via rehearsal**

Repetir o rehearsal do arquétipo A1 (cafeteria pequena) pelo dev router. Guiar até a Valéria oferecer o link. Validar: (a) o link apareceu, (b) o texto da Valéria soou humano (não robotizado), (c) ela não mandou link sem volume.

Se falhar em (b) ou (c), ajustar o prompt inline e repetir.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/tools.py backend/app/agent/prompts/ backend/tests/test_agent_tools.py
git commit -m "feat(agent): adicionar tool gerar_link_pagamento para fechamento no MVP"
```

---

### Task 2.2: Tool `registrar_pedido_simples`

Registra a intenção de pedido num local canônico (tabela `deals` existente no Supabase? nova tabela `orders`? Google Sheet?). MVP = reusar `create_deal` que já existe (visto em `tools.py:175`), com campos preenchidos a partir do que a Valéria coletou na conversa (volume, produto, link de pagamento enviado).

**Files:**
- Modify: `backend/app/agent/tools.py`
- Modify: `backend/app/leads/service.py` (se `create_deal` precisar de campos novos)
- Modify: prompts atacado/private_label (inbound + outbound)
- Test: `backend/tests/test_agent_tools.py`

- [ ] **Step 1: Ler `create_deal` existente e decidir se extende ou cria irmão**

```bash
grep -n "def create_deal" backend/app/leads/service.py
```

Abrir e ler a assinatura. Se já aceita campos livres (ex: `notes`, `metadata`), reusar. Se não, estender com parâmetro opcional `details: str | None = None`.

- [ ] **Step 2: Escrever teste falhando**

Em `backend/tests/test_agent_tools.py`:

```python
@pytest.mark.asyncio
async def test_registrar_pedido_simples_cria_deal(monkeypatch):
    calls = []
    def fake_create_deal(lead_id, title, **kwargs):
        calls.append({"lead_id": lead_id, "title": title, **kwargs})
        return {"id": "deal-fake"}
    monkeypatch.setattr("app.agent.tools.create_deal", fake_create_deal)

    result = await execute_tool(
        "registrar_pedido_simples",
        {
            "categoria": "atacado",
            "produto": "classico",
            "volume_kg": 10,
            "observacoes": "lead pediu entrega urgente",
        },
        lead_id="lead-test-id",
        phone="+5500000000",
        conversation_id="conv-test-id",
    )
    assert len(calls) == 1
    assert "atacado" in calls[0]["title"].lower() or "pedido" in calls[0]["title"].lower()
    assert "registrado" in result.lower() or "ok" in result.lower()
```

- [ ] **Step 3: Rodar e confirmar falha**

```bash
cd backend && pytest tests/test_agent_tools.py::test_registrar_pedido_simples_cria_deal -v
```

Expected: FAIL — tool não reconhecida.

- [ ] **Step 4: Adicionar schema e execute branch**

Em `TOOLS_SCHEMA` (mesmo padrão anterior):

```python
    {
        "type": "function",
        "function": {
            "name": "registrar_pedido_simples",
            "description": "Registra a intencao de pedido do lead para acompanhamento. Use depois de gerar link de pagamento ou quando o lead confirmou verbalmente que vai comprar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {"type": "string", "enum": ["atacado", "private_label"]},
                    "produto": {"type": "string", "description": "Nome do produto (ex: classico, suave, microlote)"},
                    "volume_kg": {"type": "number"},
                    "observacoes": {"type": "string", "description": "Notas livres — prazo, endereço, preferências"},
                },
                "required": ["categoria", "volume_kg"],
            },
        },
    },
```

Em `execute_tool`:

```python
    elif tool_name == "registrar_pedido_simples":
        categoria = args.get("categoria", "")
        produto = args.get("produto", "")
        volume = args.get("volume_kg", 0)
        obs = args.get("observacoes", "")
        title = f"Pedido {categoria} {produto} {volume}kg".strip()
        create_deal(lead_id, title=title)
        save_message(
            lead_id,
            "system",
            f"Pedido registrado: {title}. Obs: {obs}" if obs else f"Pedido registrado: {title}",
            conversation_id=conversation_id,
        )
        return f"Pedido registrado ({title})"
```

Adicionar `"registrar_pedido_simples"` nas listas `atacado` e `private_label` em `get_tools_for_stage`.

- [ ] **Step 5: Rodar testes**

```bash
cd backend && pytest tests/test_agent_tools.py -v
```

Expected: PASS em todos os testes novos + todos os existentes continuam passando.

- [ ] **Step 6: Atualizar prompts**

Em `valeria_*/atacado.py` e `valeria_*/private_label.py`, estender a ETAPA DE FECHAMENTO adicionada na Task 2.1:

```
4. Depois de enviar o link, chame registrar_pedido_simples com categoria, produto, volume_kg e observacoes (prazo/endereco/etc).
5. Responda algo como "registrei aqui seu pedido. assim que o pagamento cair, te aviso e a equipe prepara a remessa".
```

- [ ] **Step 7: Teste manual via rehearsal**

Repetir arquétipo A1 até o fechamento simulado. Confirmar: link + registro de pedido + frase de confirmação. Se a Valéria fizer as 3 coisas, está cumprindo o ciclo completo.

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/tools.py backend/app/agent/prompts/ backend/tests/test_agent_tools.py
git commit -m "feat(agent): adicionar tool registrar_pedido_simples para fechar ciclo MVP"
```

---

### Task 2.3: Piloto warm v2 (5 leads novos OU 5 leads antigos retomados)

**Gatilho:** Tasks 2.1 e 2.2 completas.

**Files:**
- Append to: `docs/superpowers/plans/pilot/2026-04-20-pilot-log.md` (seção "Piloto v2")

- [ ] **Step 1: Escolher leads**

Opção A: 5 leads novos, mesmo critério da Task 1.4. Opção B: 5 leads do piloto v1 que ficaram em "cotação solicitada" ou "interessado mas não fechou" — retomar com o agent_profile_id outbound (ou um novo template de reengajamento). Opção B é mais rápida e também demonstra que a Valéria consegue retomar (embora sem memória persistente, vai depender do histórico na conversa).

- [ ] **Step 2: Disparar e monitorar ao vivo**

Mesmo procedimento da Task 1.4. **Atenção especial**: validar se a Valéria **realmente usa** as novas tools `gerar_link_pagamento` e `registrar_pedido_simples` quando apropriado, ou se ignora e continua encaminhando humano. Se ignorar, o prompt ainda não está forte o suficiente — iterar.

- [ ] **Step 3: Log e consolidação**

Seção nova no pilot-log:

```markdown
# Piloto v2 — Fechamento

| Lead | Chegou em intenção de compra? | Tool de link usada? | Tool de registro usada? | Fechou? |
|---|---|---|---|---|
| L1 | ✓/✗ | ✓/✗ | ✓/✗ | ✓/✗/parcial |
...

## Veredicto
- Taxa de uso das novas tools: X/Y
- Taxa de fechamento real (pagamento confirmado): Z/Y
- Reação qualitativa dos leads ao link ter vindo da "IA": (coletar 2-3 frases)
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/pilot/2026-04-20-pilot-log.md
git commit -m "docs: piloto warm v2 pós tools de fechamento"
```

- [ ] **Step 5: Apresentação final ao dono**

Entregável: pilot-log consolidado v1+v2, screenshots de uma conversa completa (template → qualificação → catálogo → preço → link → pedido registrado), 1 transcrição anotada mostrando o "momento mágico".

---

## Verificação End-to-End

Como testar o plano inteiro funcionou:

1. **Fase 1 sucesso:** pelo menos 50% dos leads do piloto v1 chegaram a um stage de venda (atacado/private_label/exportacao), e você tem 3+ transcrições onde a Valéria não pareceu robô.
2. **Fase 2 sucesso:** em pelo menos 1 conversa, a Valéria gerou link de pagamento + registrou pedido SEM intervenção humana, e o lead reagiu ao link (clicou / perguntou / pagou).
3. **Demo ao dono:** o dono consegue ver um print/transcrição que começa em "template enviado" e termina em "pedido registrado" numa única conversa da Valéria. Esse é o artefato.

Se algum dos três falhar, o plano pós-mortem fica no pilot-log com decisão "o quê atacar depois":
- Falha em (1) → voltar pro rehearsal, consertar prompts de qualificação
- Falha em (2) → iterar os prompts de fechamento, talvez remover opção `encaminhar_humano` em atacado pra forçar a IA a tentar fechar
- Falha em (3) → investigar se o problema é geração de lead (template ruim, horário ruim) vs condução (prompt) vs fechamento (tool/UX)

---

## O que este plano NÃO inclui (de propósito)

- Eval harness sintético — volta pra mesa se depois de escalar ficar impossível testar mudança de prompt à mão.
- Memória persistente inter-conversas — só faz sentido com ciclo de vendas comprovado.
- Workflows duráveis pro outbound — só justifica se o piloto mostrar que timing/nudges são o gap.
- Multi-modal (áudio/imagem) — anotar se apareceu no piloto mas não consertar agora.
- Perfil contínuo multi-intent — refatoração grande, adiar pós-validação.

Esses ficam na avaliação estratégica (`/home/Kelwin/.claude/plans/claude-com-todo-o-velvety-kettle.md`) pra quando fizer sentido.

---

## Arquivos Críticos

- `backend/app/agent/orchestrator.py` — `run_agent()` (linhas 60-167). Zero alteração prevista.
- `backend/app/agent/tools.py` — `TOOLS_SCHEMA` (linhas 47-135), `execute_tool` (linhas 151-241), `get_tools_for_stage` (linhas 138-148). Adições na Fase 2.
- `backend/app/agent/prompts/valeria_inbound/atacado.py` e `private_label.py` — ajustes da Fase 2 (ETAPA FECHAMENTO).
- `backend/app/agent/prompts/valeria_outbound/atacado.py` e `private_label.py` — idem.
- `backend/app/leads/service.py` — `create_deal` (reuso na Task 2.2).
- `backend/tests/test_agent_tools.py` — arquivo de testes existente, estender.
- `docs/superpowers/plans/pilot/2026-04-20-rehearsal-scripts.md` — novo, da Task 1.1.
- `docs/superpowers/plans/pilot/2026-04-20-pilot-log.md` — novo, da Task 1.4.
