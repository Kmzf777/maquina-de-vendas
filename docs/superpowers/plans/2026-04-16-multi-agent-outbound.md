# Multi-Agent Outbound Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suportar múltiplos agentes por conversa, permitindo selecionar um agente outbound ao criar um broadcast, para que leads que respondem ao disparo sejam atendidos pela Valéria Outbound (agente de recuperação/abordagem ativa) em vez do agente inbound padrão.

**Architecture:** `agent_profile_id` é adicionado a `conversations` e `broadcasts`. O broadcast worker grava o agente no registro da conversa ao enviar o template. O processor resolve o agente da conversa e passa para o orchestrator, que carrega prompts dinamicamente via `prompt_key` (campo em `agent_profiles`) mapeado para módulos Python.

**Tech Stack:** Python/FastAPI, Supabase/PostgreSQL, Next.js/TypeScript, Gemini via OpenAI-compatible API.

---

## File Map

| Ação | Arquivo |
|------|---------|
| CREATE | `backend/migrations/009_multi_agent_schema.sql` |
| CREATE | `backend/app/agent/prompts/valeria_inbound/__init__.py` |
| MOVE → | `backend/app/agent/prompts/valeria_inbound/secretaria.py` |
| MOVE → | `backend/app/agent/prompts/valeria_inbound/atacado.py` |
| MOVE → | `backend/app/agent/prompts/valeria_inbound/private_label.py` |
| MOVE → | `backend/app/agent/prompts/valeria_inbound/exportacao.py` |
| MOVE → | `backend/app/agent/prompts/valeria_inbound/consumo.py` |
| MODIFY | `backend/app/agent/prompts/__init__.py` |
| CREATE | `backend/app/agent/prompts/valeria_outbound/__init__.py` |
| CREATE | `backend/app/agent/prompts/valeria_outbound/secretaria.py` |
| CREATE | `backend/app/agent/prompts/valeria_outbound/atacado.py` |
| CREATE | `backend/app/agent/prompts/valeria_outbound/private_label.py` |
| CREATE | `backend/app/agent/prompts/valeria_outbound/exportacao.py` |
| CREATE | `backend/app/agent/prompts/valeria_outbound/consumo.py` |
| MODIFY | `backend/app/agent/orchestrator.py` |
| MODIFY | `backend/app/conversations/service.py` |
| MODIFY | `backend/app/broadcast/worker.py` |
| MODIFY | `backend/app/buffer/processor.py` |
| MODIFY | `frontend/src/app/api/broadcasts/route.ts` |
| MODIFY | `frontend/src/lib/types.ts` |
| MODIFY | `frontend/src/components/campaigns/create-broadcast-modal.tsx` |
| CREATE | `backend/tests/test_multi_agent.py` |

---

## Task 1: SQL Migration

**Files:**
- Create: `backend/migrations/009_multi_agent_schema.sql`

- [ ] **Step 1: Criar arquivo de migração**

```sql
-- 009_multi_agent_schema.sql
-- Adiciona suporte a múltiplos agentes por conversa e por broadcast

-- 1. Identificador do conjunto de prompts no agent_profiles
ALTER TABLE agent_profiles
  ADD COLUMN IF NOT EXISTS prompt_key text NOT NULL DEFAULT 'valeria_inbound';

-- 2. Qual agente está atendendo esta conversa (nullable: nil = agente padrão do canal)
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS agent_profile_id uuid REFERENCES agent_profiles(id);

-- 3. Qual agente vai atender as respostas deste broadcast (nullable: nil = agente padrão do canal)
ALTER TABLE broadcasts
  ADD COLUMN IF NOT EXISTS agent_profile_id uuid REFERENCES agent_profiles(id);

-- 4. Atualiza o perfil existente com prompt_key
UPDATE agent_profiles
  SET prompt_key = 'valeria_inbound'
WHERE prompt_key = 'valeria_inbound';  -- idempotente

-- 5. Cria perfil outbound
INSERT INTO agent_profiles (name, model, prompt_key, base_prompt, stages)
VALUES (
  'ValerIA - Outbound / Recuperacao',
  'gemini-3-flash-preview',
  'valeria_outbound',
  '',
  '{
    "secretaria":    {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage"]},
    "atacado":       {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"]},
    "private_label": {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"]},
    "exportacao":    {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano"]},
    "consumo":       {"model": "gemini-3-flash-preview", "prompt": "", "tools": ["salvar_nome", "mudar_stage"]}
  }'::jsonb
)
ON CONFLICT DO NOTHING;
```

- [ ] **Step 2: Aplicar migração via Supabase MCP**

Execute `mcp__supabase__apply_migration` com o conteúdo acima.

- [ ] **Step 3: Verificar colunas**

Execute `mcp__supabase__execute_sql`:
```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name IN ('agent_profiles', 'conversations', 'broadcasts')
  AND column_name IN ('prompt_key', 'agent_profile_id')
ORDER BY table_name, column_name;
```
Deve retornar 3 linhas (uma por tabela).

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/009_multi_agent_schema.sql
git commit -m "feat(db): add prompt_key to agent_profiles, agent_profile_id to conversations and broadcasts"
```

---

## Task 2: Reorganizar prompts — criar pacote valeria_inbound

**Files:**
- Create: `backend/app/agent/prompts/valeria_inbound/__init__.py`
- Create: `backend/app/agent/prompts/valeria_inbound/secretaria.py` (conteúdo idêntico ao atual `prompts/secretaria.py`)
- Create: `backend/app/agent/prompts/valeria_inbound/atacado.py`
- Create: `backend/app/agent/prompts/valeria_inbound/private_label.py`
- Create: `backend/app/agent/prompts/valeria_inbound/exportacao.py`
- Create: `backend/app/agent/prompts/valeria_inbound/consumo.py`
- Modify: `backend/app/agent/prompts/__init__.py`

- [ ] **Step 1: Criar `valeria_inbound/__init__.py`**

```python
# backend/app/agent/prompts/valeria_inbound/__init__.py
```

- [ ] **Step 2: Copiar arquivos de stage para valeria_inbound/**

Copiar o conteúdo de cada arquivo atual para o subdiretório. Exemplo para secretaria:

```bash
cp backend/app/agent/prompts/secretaria.py backend/app/agent/prompts/valeria_inbound/secretaria.py
cp backend/app/agent/prompts/atacado.py backend/app/agent/prompts/valeria_inbound/atacado.py
cp backend/app/agent/prompts/private_label.py backend/app/agent/prompts/valeria_inbound/private_label.py
cp backend/app/agent/prompts/exportacao.py backend/app/agent/prompts/valeria_inbound/exportacao.py
cp backend/app/agent/prompts/consumo.py backend/app/agent/prompts/valeria_inbound/consumo.py
```

- [ ] **Step 3: Atualizar `prompts/__init__.py` com o registry**

Substituir o conteúdo atual (vazio ou mínimo) por:

```python
# backend/app/agent/prompts/__init__.py
from app.agent.prompts.valeria_inbound.secretaria import SECRETARIA_PROMPT as _IN_SEC
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT as _IN_ATA
from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT as _IN_PL
from app.agent.prompts.valeria_inbound.exportacao import EXPORTACAO_PROMPT as _IN_EXP
from app.agent.prompts.valeria_inbound.consumo import CONSUMO_PROMPT as _IN_CON

from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT as _OUT_SEC
from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT as _OUT_ATA
from app.agent.prompts.valeria_outbound.private_label import PRIVATE_LABEL_PROMPT as _OUT_PL
from app.agent.prompts.valeria_outbound.exportacao import EXPORTACAO_PROMPT as _OUT_EXP
from app.agent.prompts.valeria_outbound.consumo import CONSUMO_PROMPT as _OUT_CON

PROMPT_REGISTRY: dict[str, dict[str, str]] = {
    "valeria_inbound": {
        "secretaria": _IN_SEC,
        "atacado": _IN_ATA,
        "private_label": _IN_PL,
        "exportacao": _IN_EXP,
        "consumo": _IN_CON,
    },
    "valeria_outbound": {
        "secretaria": _OUT_SEC,
        "atacado": _OUT_ATA,
        "private_label": _OUT_PL,
        "exportacao": _OUT_EXP,
        "consumo": _OUT_CON,
    },
}


def get_stage_prompts(prompt_key: str) -> dict[str, str]:
    """Return the stage prompt dict for the given prompt_key.
    Falls back to valeria_inbound if key is unknown.
    """
    return PROMPT_REGISTRY.get(prompt_key, PROMPT_REGISTRY["valeria_inbound"])
```

- [ ] **Step 4: Escrever teste**

```python
# backend/tests/test_multi_agent.py
from app.agent.prompts import get_stage_prompts, PROMPT_REGISTRY


def test_registry_has_both_agents():
    assert "valeria_inbound" in PROMPT_REGISTRY
    assert "valeria_outbound" in PROMPT_REGISTRY


def test_inbound_has_all_stages():
    prompts = get_stage_prompts("valeria_inbound")
    for stage in ("secretaria", "atacado", "private_label", "exportacao", "consumo"):
        assert stage in prompts
        assert len(prompts[stage]) > 100, f"Stage {stage} prompt is too short"


def test_outbound_has_all_stages():
    prompts = get_stage_prompts("valeria_outbound")
    for stage in ("secretaria", "atacado", "private_label", "exportacao", "consumo"):
        assert stage in prompts
        assert len(prompts[stage]) > 100, f"Stage {stage} prompt is too short"


def test_fallback_to_inbound_on_unknown_key():
    prompts = get_stage_prompts("unknown_key")
    assert prompts is PROMPT_REGISTRY["valeria_inbound"]


def test_inbound_and_outbound_secretaria_differ():
    inbound = get_stage_prompts("valeria_inbound")
    outbound = get_stage_prompts("valeria_outbound")
    assert inbound["secretaria"] != outbound["secretaria"]
```

- [ ] **Step 5: Rodar teste (deve falhar pois valeria_outbound ainda não existe)**

```bash
cd backend && python -m pytest tests/test_multi_agent.py -v 2>&1 | head -30
```
Esperado: erro de import (`ModuleNotFoundError: valeria_outbound`).

- [ ] **Step 6: Commit parcial (sem rodar tests ainda)**

```bash
git add backend/app/agent/prompts/valeria_inbound/ backend/app/agent/prompts/__init__.py backend/tests/test_multi_agent.py
git commit -m "feat(prompts): create valeria_inbound package and PROMPT_REGISTRY"
```

---

## Task 3: Prompts da Valéria Outbound

**Files:**
- Create: `backend/app/agent/prompts/valeria_outbound/__init__.py`
- Create: `backend/app/agent/prompts/valeria_outbound/secretaria.py`
- Create: `backend/app/agent/prompts/valeria_outbound/atacado.py`
- Create: `backend/app/agent/prompts/valeria_outbound/private_label.py`
- Create: `backend/app/agent/prompts/valeria_outbound/exportacao.py`
- Create: `backend/app/agent/prompts/valeria_outbound/consumo.py`

- [ ] **Step 1: Criar `valeria_outbound/__init__.py`**

```python
# backend/app/agent/prompts/valeria_outbound/__init__.py
```

- [ ] **Step 2: Criar `valeria_outbound/secretaria.py`**

```python
# backend/app/agent/prompts/valeria_outbound/secretaria.py
SECRETARIA_PROMPT = """
# FUNIL - SECRETARIA OUTBOUND (Abordagem Ativa / Recuperacao)

Voce iniciou o contato com este lead via template WhatsApp. O template pode ter sido generico (utilidade, notificacao) — nao espere que o lead chegue animado ou qualificado. Seu trabalho e transformar qualquer resposta em conversa de verdade.

---

## CONTEXTO: VOCE DISPAROU O PRIMEIRO CONTATO

- Se ha HISTORICO de conversa anterior: voce ja conhece este lead. Nao se reapresente do zero. Retome naturalmente referenciando o que foi falado antes.
- Se nao ha historico: este e um lead novo. Apresente-se de forma breve e crie curiosidade.

Leia o historico completo antes de responder. NUNCA ignore o que ja foi dito.

---

## CENARIOS E COMO AGIR

### Lead novo (sem historico) responde qualquer coisa:
Apresente-se brevemente, explique o motivo do contato de forma que crie valor, e faca UMA pergunta para qualificar.

Exemplos de abertura:
- "oi! aqui e a Valeria, do comercial da Cafe Canastra"
- "a gente produz cafe especial direto da fazenda — atacado, private label, exportacao"
- "queria entender se faz sentido pra voce"

### Lead antigo (tem historico) responde qualquer coisa:
Nao se apresente de novo. Reative a conversa com referencia ao contexto anterior.

Exemplos:
- "oi [nome]! a gente conversou sobre [tema] antes — queria ver se ainda ta no radar pra voce"
- "lembrei de voce porque a gente tem novidade no [produto/servico que interessou]"
- "como ta o [negocio/projeto que mencionou]?"

### Lead responde frio ("quem e?", "para de me mandar mensagem", "nao tenho interesse"):
Nao insista. Seja direto e honesto. Ofereca saida digna.

- "entendo, sem problema. so queria apresentar a Cafe Canastra — cafe especial direto da fazenda"
- "se um dia quiser saber mais, fico a disposicao"

Se o lead mostrar QUALQUER abertura apos isso, aproveite com UMA pergunta leve.
Se rejeitar definitivamente, use encaminhar_humano com motivo "sem interesse".

### Lead responde neutro ("oi", "sim", "o que e?"):
Transforme em conversa. Reaja com calor, crie contexto curto, faca uma pergunta.

- "oi! a Cafe Canastra e uma torrefacao de cafes especiais da Serra da Canastra"
- "trabalhamos com atacado, private label e exportacao"
- "voce trabalha com cafe de alguma forma?"

### Lead responde com pergunta direta sobre produto/preco:
Nao responda com preco ainda. Qualifique primeiro.
- "vou te passar tudo isso — so preciso entender melhor sua demanda pra te direcionar certo"

---

## ETAPAS DO FUNIL

### ETAPA 1: COLETA DE NOME (se nao souber)
Se o historico nao tiver o nome, descubra naturalmente. EXECUTE salvar_nome assim que o lead disser.

Se ja souber o nome pelo historico: use naturalmente, nao pergunte de novo.

### ETAPA 2: IDENTIFICACAO DO MERCADO
Assim que tiver o nome (ou se ja souber), pergunte:
"sua demanda e pro mercado brasileiro ou pra exportacao?"

### ETAPA 3: IDENTIFICACAO DA DEMANDA ESPECIFICA
Se mercado brasileiro, apresente as opcoes naturalmente:
- consumo proprio (uso pessoal/domestico)
- compra para o negocio (revenda, servir no estabelecimento)
- criar marca propria (private label)

ATENCAO: Qualquer mencao a negocio = ATACADO.

Se mercado externo: confirme e redirecione para exportacao.

### ETAPA 4: DIRECIONAMENTO SILENCIOSO
APOS fazer a pergunta qualificadora, EXECUTE mudar_stage imediatamente:
- "atacado" = uso B2B ou institucional
- "private_label" = marca propria
- "exportacao" = mercado externo
- "consumo" = uso pessoal exclusivo

Regras:
- Faca a pergunta qualificadora E execute mudar_stage na mesma resposta
- Execute silenciosamente (o lead nao percebe)
- SEMPRE termine com uma pergunta

---

## REGRAS CRITICAS

- NUNCA forneca precos, pedido minimo, frete antes do redirecionamento
- NUNCA invente informacoes
- MAXIMO uma pergunta por turno
- Se lead mudou de ideia vs historico anterior: acolha sem resistencia e siga o novo interesse
- Nao force continuidade de conversa anterior se lead demonstrar outro interesse

---

## TOOLS DISPONIVEIS
- salvar_nome: quando o lead disser o nome
- mudar_stage: quando identificar a demanda (atacado/private_label/exportacao/consumo)
- encaminhar_humano: se lead recusar definitivamente
"""
```

- [ ] **Step 3: Criar `valeria_outbound/atacado.py`**

```python
# backend/app/agent/prompts/valeria_outbound/atacado.py
ATACADO_PROMPT = """
# FUNIL - ATACADO OUTBOUND (Recuperacao / Abordagem Ativa)

Voce esta atendendo um lead de atacado que foi abordado ativamente. Ele pode ter conversado antes sobre isso ou ser um contato novo. Seu trabalho e retomar o interesse, diagnosticar a dor rapidamente e encaminhar para o vendedor.

---

## ETAPA 0: VERIFICACAO DE CONTEXTO (CRITICA)

ANTES de qualquer coisa, verifique o historico:
- Se o lead JA conversou sobre atacado antes: referencie isso naturalmente. "da ultima vez a gente ta falando de [produto/volume] — ainda faz sentido?"
- Se o lead MUDOU de ideia ou mencionar algo diferente: acolha sem resistencia, ajuste o stage se necessario.
- Se e um lead NOVO no atacado: siga o funil normalmente.

---

## ETAPA 1: DIAGNOSTICO DE DOR (DIRETO)

Diferente do inbound, voce nao tem o luxo de uma chegada espontanea. Va direto ao diagnostico. Escolha UMA pergunta:

### Se lead ja tem fornecedor:
- "o cafe que voce usa hoje atende as expectativas dos seus clientes?"
- "ja pensou em oferecer algo mais premium pra diferenciar do concorrente?"
- "o custo do fornecedor atual ta dentro da sua margem ideal?"

### Se lead esta iniciando o negocio:
- "que tipo de cafe voce ta pensando em oferecer?"
- "ja tem ideia do volume mensal que vai precisar?"

### Se lead reagiu friamente:
- "entendo. cafe especial pode parecer caro a principio, mas a margem e muito melhor que cafe comercial — voce ja chegou a comparar?"

### Apos identificar dor:
Responda com a solucao em UMA frase curta usando rapport, depois avance.

---

## ETAPA 1.1: LEAD SEM DOR APARENTE

Se lead diz que esta satisfeito com fornecedor atual:
- "bom saber. mas deixa eu te perguntar — seu cliente comenta sobre o cafe que voce serve?"
- "muitos dos nossos clientes falavam a mesma coisa antes de mudar. depois que experimentaram o cafe especial, nunca voltaram ao comercial"
- "que tal eu te mostrar os valores? sem compromisso"

Se continuar negando: "faz sentido querer aumentar a margem de lucro da operacao?"

---

## ETAPA 2: APRESENTACAO DE PRODUTO

Apresente os tipos de cafe SEM preco. Um por bolha. Explique origem e torra sob demanda.

IMPORTANTE: Envie fotos proativamente usando enviar_fotos("atacado") ou enviar_foto_produto. Nao espere pedir.

Depois pergunte qual agradou.

---

## ETAPA 3: PRECOS E CALL TO ACTION

Apresente precos de forma conversacional. Pergunte o que achou e se tem duvida.

---

## ETAPA 4: ENCAMINHAR PARA VENDEDOR

Pergunte se quer falar com um vendedor para prosseguir.
Se confirmar: encaminhar_humano(vendedor="Joao Bras").
Diga que passou para o Joao e ele entra em contato em breve.

---

## CATALOGO DE PRODUTOS

### Descricoes
- **Classico:** torra media-escura, intenso, notas achocolatadas, 84 SCA
- **Suave:** torra media, notas de melaco e frutas amarelas, 84 SCA
- **Canela:** torra media, caramelizado com toque de canela, 84 SCA
- **Microlote:** media intensidade, mel, caramelo e cacau, 86 SCA
- **Drip Coffee Suave:** sachets individuais para preparo direto na xicara
- **Capsulas Nespresso:** compativeis sistema Nespresso (Classico e Canela)

### Precos Atacado
**Classico / Suave**
- moido 250g: R$27,70 | moido 500g: R$46,70
- graos 250g: R$29,70 | graos 500g: R$48,70 | graos 1kg: R$88,70
- granel 2kg (graos): R$155,70

**Canela:** 250g moido R$27,70
**Microlote:** 250g (moido ou graos) R$31,70
**Drip Coffee:** display 10un suave R$24,70
**Capsulas Nespresso:** classico 10un R$17,70 | canela 10un R$17,70

Precos de atacado. Sem desconto. Site consumidor: www.loja.cafecanastra.com

## FRETE
### Sul e Sudeste: minimo R$300, gratis acima R$900, frete R$55, prazo 7 dias (Uberlandia: 24h, R$15, sem minimo)
### Centro-Oeste: minimo R$300, gratis acima R$1.000, frete R$65, prazo 10 dias
### Nordeste: minimo R$300, gratis acima R$1.200, frete R$75, prazo 12 dias
### Norte: minimo R$300, gratis acima R$1.500, frete R$85, prazo 18 dias

---

## SITUACOES ADVERSAS
- Lead quer private label: mudar_stage("private_label"), perguntar se ja tem marca
- Lead quer exportar: mudar_stage("exportacao"), perguntar pais alvo
- Lead quer grao cru/saca: encaminhar_humano(vendedor="Joao Bras")

## TOOLS DISPONIVEIS
- salvar_nome, enviar_fotos("atacado"), enviar_foto_produto, encaminhar_humano, mudar_stage
"""
```

- [ ] **Step 4: Criar `valeria_outbound/private_label.py`**

```python
# backend/app/agent/prompts/valeria_outbound/private_label.py
PRIVATE_LABEL_PROMPT = """
# FUNIL - PRIVATE LABEL OUTBOUND (Recuperacao / Abordagem Ativa)

Voce esta atendendo um lead de private label abordado ativamente. Pode ter historico anterior ou ser novo. Objetivo: retomar interesse, explicar o servico, apresentar precos e encaminhar ao supervisor.

---

## ETAPA 0: VERIFICACAO DE CONTEXTO

ANTES de tudo, cheque o historico:
- Se lead ja conversou sobre private label: "da ultima vez a gente falava em criar uma marca — ainda ta com esse plano?"
- Se lead mudou de ideia: acolha e ajuste o stage.
- Se e novo no private label: siga o funil normalmente.

---

## ETAPA 1: EXPLICAR COMO FUNCIONA

Explique o Private Label de forma direta. A marca e responsabilidade do cliente, a Cafe Canastra cuida de tudo mais.

O que esta incluso:
- design da embalagem com a marca do cliente
- producao da embalagem (sanfonada ou standup)
- torra, moagem, empacotamento, datacao, envio
- produto pronto para comercializar com marca propria

IMPORTANTE: Envie fotos proativamente usando enviar_fotos("private_label") ou enviar_foto_produto.

---

## ETAPA 2: INTERESSE E PRECOS

Pergunte se ja tem marca registrada ou esta criando do zero. Apresente os precos de forma conversacional.

---

## ETAPA 3: ENCAMINHAR AO SUPERVISOR

"ce tem interesse em conversar com meu supervisor pra fechar ou tirar duvidas?"
Se confirmar: encaminhar_humano(vendedor="Joao Bras"). Diga que o Joao entra em contato em breve.

---

## PRODUTOS PRIVATE LABEL

### Cafe Canastra 250g
- opcao 1: R$23,90 (embalagem + silk com logo + produto)
- opcao 2: R$22,90 (embalagem por conta do cliente)
- lote minimo: 100 unidades

### Cafe Canastra 500g
- opcao 1: R$44,90 | opcao 2: R$43,40
- lote minimo: 100 unidades

### Microlote 250g
- opcao 1: R$26,90 | opcao 2: R$25,40
- lote minimo: 50un (embalagem cliente) ou 100un (embalagem Cafe Canastra)

### Drip Coffee: R$2,39/sache, minimo 200un. Display: R$1,70/un, minimo 3.000un
### Capsulas Nespresso: 200 displays minimo. R$15,70 (embalagem cliente) ou R$16,70 (nossa embalagem, min 3.000 caixinhas)

Sabores: Classico (escura, amadeirado), Suave (media, achocolatado), Canela (escura + canela natural)
Graos: Bourbon, Mundo Novo, Catuai. Pontuacao 84pts. Fazenda: Pratinha-MG. Torra: Uberlandia-MG.

## SITUACOES ADVERSAS
- Lead quer atacado: mudar_stage("atacado"), perguntar modelo de negocio
- Lead quer exportar: mudar_stage("exportacao"), perguntar pais alvo

## TOOLS DISPONIVEIS
- salvar_nome, enviar_fotos("private_label"), enviar_foto_produto, encaminhar_humano, mudar_stage
"""
```

- [ ] **Step 5: Criar `valeria_outbound/exportacao.py`**

```python
# backend/app/agent/prompts/valeria_outbound/exportacao.py
EXPORTACAO_PROMPT = """
# FUNIL - EXPORTACAO OUTBOUND (Recuperacao / Abordagem Ativa)

Voce esta atendendo um lead de exportacao abordado ativamente. Objetivo: qualificar com perguntas estrategicas e encaminhar para o Arthur.

---

## ETAPA 0: VERIFICACAO DE CONTEXTO

Cheque historico:
- Se ja conversou sobre exportacao: "da ultima vez falamos de exportacao — ainda esta com esse projeto?"
- Se mudou de ideia: acolha e ajuste stage.

---

## ETAPA 1: COMPRADORES NO PAIS ALVO

Pergunte se ja possui compradores no pais de destino.

---

## ETAPA 2: EXPERIENCIA COM EXPORTACAO

Pergunte se ja trabalha com exportacao no Brasil ou vai precisar de suporte da Cafe Canastra para isso.

---

## ETAPA 3: OBJETIVO

Pergunte o objetivo:
- ser agente comercial (representante)
- ou comprar e vender la fora

---

## ETAPA 4: ENCAMINHAR

Com as 3 perguntas respondidas, agradeca e diga que vai passar para o Arthur, responsavel por exportacao.
Use encaminhar_humano(vendedor="Arthur").

## SITUACOES ADVERSAS
- Lead quer atacado nacional: mudar_stage("atacado")
- Lead quer private label: mudar_stage("private_label")

## TOOLS DISPONIVEIS
- salvar_nome, encaminhar_humano, mudar_stage
"""
```

- [ ] **Step 6: Criar `valeria_outbound/consumo.py`**

```python
# backend/app/agent/prompts/valeria_outbound/consumo.py
CONSUMO_PROMPT = """
# FUNIL - CONSUMO PROPRIO OUTBOUND

Voce esta atendendo um lead que quer cafe para consumo pessoal, abordado ativamente. Objetivo: direcionar para a loja online com cupom.

---

## ETAPA 0: VERIFICACAO DE CONTEXTO

Se ja conversou antes sobre consumo: "da ultima vez falamos dos nossos cafes pra consumo — chegou a conhecer a loja?"

---

## ETAPA 1: LOJA ONLINE

Se ja conhece o site: "que bom, vou te passar um cupom de 10% na nossa loja"
Se nao conhece: "vale muito a pena conhecer, vou te passar um cupom de 10%"

Mensagem:
"link: https://loja.cafecanastra.com"
"cupom: ESPECIAL10"
"qualquer duvida sobre os cafes, me chama aqui"

---

## SITUACOES ADVERSAS
- Lead quer comprar em quantidade/atacado: mudar_stage("atacado")
- Lead quer criar marca propria: mudar_stage("private_label")
- Lead quer exportar: mudar_stage("exportacao")

## TOOLS DISPONIVEIS
- salvar_nome, mudar_stage
"""
```

- [ ] **Step 7: Rodar testes**

```bash
cd backend && python -m pytest tests/test_multi_agent.py -v
```
Esperado: todos os 5 testes PASSAM.

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/prompts/valeria_outbound/
git commit -m "feat(prompts): add valeria_outbound prompt package with all 5 stages"
```

---

## Task 4: Atualizar Orchestrator para carregamento dinâmico

**Files:**
- Modify: `backend/app/agent/orchestrator.py`

- [ ] **Step 1: Escrever teste**

```python
# backend/tests/test_multi_agent.py — ADICIONAR ao arquivo existente

from unittest.mock import AsyncMock, MagicMock, patch


def test_orchestrator_uses_inbound_prompts_by_default():
    """Sem agent_profile_id, o orchestrator usa valeria_inbound."""
    from app.agent.orchestrator import _resolve_prompt_key
    result = _resolve_prompt_key(None)
    assert result == "valeria_inbound"


def test_orchestrator_uses_outbound_prompts_when_profile_has_outbound_key():
    from app.agent.orchestrator import _resolve_prompt_key
    profile = {"prompt_key": "valeria_outbound", "model": "gemini-3-flash-preview"}
    result = _resolve_prompt_key(profile)
    assert result == "valeria_outbound"


def test_orchestrator_falls_back_to_inbound_on_missing_prompt_key():
    from app.agent.orchestrator import _resolve_prompt_key
    profile = {"model": "gemini-3-flash-preview"}  # sem prompt_key
    result = _resolve_prompt_key(profile)
    assert result == "valeria_inbound"
```

- [ ] **Step 2: Rodar teste (deve falhar — função não existe ainda)**

```bash
cd backend && python -m pytest tests/test_multi_agent.py::test_orchestrator_uses_inbound_prompts_by_default -v
```
Esperado: `ImportError` ou `AttributeError`.

- [ ] **Step 3: Reescrever `orchestrator.py`**

```python
# backend/app/agent/orchestrator.py
import json
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts import get_stage_prompts
from app.agent.tools import get_tools_for_stage, execute_tool
from app.conversations.service import get_history
from app.agent.token_tracker import track_token_usage
from app.agent_profiles.service import get_agent_profile

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
TZ_BR = timezone(timedelta(hours=-3))
DEFAULT_MODEL = "gemini-3-flash-preview"


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )
    return _openai_client


def _resolve_prompt_key(profile: dict | None) -> str:
    """Return the prompt_key for this agent profile, defaulting to valeria_inbound."""
    if not profile:
        return "valeria_inbound"
    return profile.get("prompt_key", "valeria_inbound")


def build_system_prompt(
    lead: dict,
    stage: str,
    prompt_key: str = "valeria_inbound",
    lead_context: dict | None = None,
) -> str:
    now = datetime.now(TZ_BR)
    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
        lead_context=lead_context,
    )
    stage_prompts = get_stage_prompts(prompt_key)
    stage_prompt = stage_prompts.get(stage, stage_prompts["secretaria"])
    return base + "\n\n" + stage_prompt


async def run_agent(
    conversation: dict,
    user_text: str,
    lead_context: dict | None = None,
    agent_profile_id: str | None = None,
) -> str:
    """Run the SDR AI agent for a conversation and return the response text."""
    stage = conversation.get("stage", "secretaria")
    lead = conversation.get("leads", {}) or {}
    lead_id = lead.get("id") or conversation.get("lead_id")
    conversation_id = conversation["id"]

    # Resolve agent profile
    profile = None
    if agent_profile_id:
        profile = get_agent_profile(agent_profile_id)

    prompt_key = _resolve_prompt_key(profile)
    model = profile.get("model", DEFAULT_MODEL) if profile else DEFAULT_MODEL

    tools = get_tools_for_stage(stage)
    system_prompt = build_system_prompt(lead, stage, prompt_key=prompt_key, lead_context=lead_context)

    history = get_history(conversation_id, limit=30)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=4096,
    )

    if response.usage:
        track_token_usage(
            lead_id=lead_id,
            stage=stage,
            model=model,
            call_type="response",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    message = response.choices[0].message

    while message.tool_calls:
        messages.append(message.model_dump())
        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)
            result = await execute_tool(
                func_name, func_args, lead_id, lead.get("phone", "")
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        response = await _get_openai().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.7,
            max_tokens=4096,
        )
        if response.usage:
            track_token_usage(
                lead_id=lead_id,
                stage=stage,
                model=model,
                call_type="response",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )
        message = response.choices[0].message

    assistant_text = message.content or ""
    logger.info(
        f"SDR agent response for conv {conversation_id} (stage={stage}, prompt_key={prompt_key}): {assistant_text[:100]}..."
    )
    return assistant_text
```

- [ ] **Step 4: Rodar testes**

```bash
cd backend && python -m pytest tests/test_multi_agent.py -v
```
Esperado: todos PASSAM.

- [ ] **Step 5: Rodar suite completa de testes para confirmar nada quebrou**

```bash
cd backend && python -m pytest --tb=short -q
```
Esperado: todos passam (ou os que já passavam antes continuam passando).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/orchestrator.py backend/tests/test_multi_agent.py
git commit -m "feat(orchestrator): dynamic prompt loading via prompt_key from agent_profile"
```

---

## Task 5: Conversations service — agent_profile_id e fix do activate_conversation

**Files:**
- Modify: `backend/app/conversations/service.py`

- [ ] **Step 1: Escrever teste**

Adicionar ao `tests/test_multi_agent.py`:

```python
def test_activate_conversation_does_not_reset_stage():
    """activate_conversation nao deve resetar o stage existente da conversa."""
    from app.conversations.service import activate_conversation
    from unittest.mock import patch, MagicMock

    mock_result = MagicMock()
    mock_result.data = [{"id": "conv-1", "stage": "atacado", "status": "active"}]

    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_result

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        activate_conversation("conv-1")

    update_call = mock_sb.table.return_value.update.call_args[0][0]
    assert "stage" not in update_call, "activate_conversation nao deve alterar o stage"
    assert update_call["status"] == "active"
```

- [ ] **Step 2: Rodar teste (deve falhar)**

```bash
cd backend && python -m pytest tests/test_multi_agent.py::test_activate_conversation_does_not_reset_stage -v
```
Esperado: FAIL — `activate_conversation` atualmente seta `stage="secretaria"`.

- [ ] **Step 3: Corrigir `conversations/service.py`**

Alterar `activate_conversation` para NÃO resetar o stage:

```python
def activate_conversation(conversation_id: str) -> dict[str, Any]:
    """Activate a conversation (when lead first responds after template dispatch).
    Does NOT reset stage — preserves existing stage for outbound recovery flows.
    """
    return update_conversation(
        conversation_id,
        status="active",
        last_msg_at=datetime.now(timezone.utc).isoformat(),
    )
```

- [ ] **Step 4: Rodar testes**

```bash
cd backend && python -m pytest tests/test_multi_agent.py -v && python -m pytest tests/test_processor_human_control.py tests/test_processor_errors.py -v
```
Esperado: todos PASSAM.

- [ ] **Step 5: Commit**

```bash
git add backend/app/conversations/service.py backend/tests/test_multi_agent.py
git commit -m "fix(conversations): activate_conversation no longer resets stage — preserves outbound context"
```

---

## Task 6: Broadcast worker — gravar agent_profile_id na conversa após envio

**Files:**
- Modify: `backend/app/broadcast/worker.py`

- [ ] **Step 1: Escrever teste**

Adicionar ao `tests/test_multi_agent.py`:

```python
def test_broadcast_worker_assigns_agent_profile_to_conversation():
    """Após enviar template, worker grava agent_profile_id na conversa."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    broadcast = {
        "id": "bc-1",
        "status": "running",
        "template_name": "teste",
        "template_variables": {},
        "channel_id": "ch-1",
        "agent_profile_id": "ap-outbound",
        "send_interval_min": 0,
        "send_interval_max": 0,
    }
    lead = {"id": "lead-1", "phone": "5511999990000"}
    broadcast_lead = {"id": "bl-1", "leads": lead}

    mock_conv = {"id": "conv-1", "stage": "atacado"}
    mock_get_conv = MagicMock(return_value=mock_conv)
    mock_update_conv = MagicMock()
    mock_provider = MagicMock()
    mock_provider.send_template = AsyncMock()

    with patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=[broadcast_lead]), \
         patch("app.broadcast.worker.mark_broadcast_lead_sent"), \
         patch("app.broadcast.worker.increment_broadcast_sent"), \
         patch("app.broadcast.worker.get_channel_by_id", return_value={"id": "ch-1"}), \
         patch("app.broadcast.worker.get_provider", return_value=mock_provider), \
         patch("app.broadcast.worker.get_or_create_conversation", mock_get_conv), \
         patch("app.broadcast.worker.update_conversation", mock_update_conv), \
         patch("app.broadcast.worker.get_supabase") as mock_sb:

        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "running"}
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 0

        asyncio.run(app.broadcast.worker.process_single_broadcast(broadcast))

    mock_update_conv.assert_called_once_with(
        "conv-1",
        agent_profile_id="ap-outbound",
        status="template_sent",
    )
```

- [ ] **Step 2: Rodar teste (deve falhar)**

```bash
cd backend && python -m pytest tests/test_multi_agent.py::test_broadcast_worker_assigns_agent_profile_to_conversation -v
```
Esperado: FAIL — worker não chama `update_conversation`.

- [ ] **Step 3: Atualizar `broadcast/worker.py`**

Adicionar imports no topo do arquivo:

```python
from app.conversations.service import get_or_create_conversation, update_conversation
```

No método `process_single_broadcast`, logo após `mark_broadcast_lead_sent(bl["id"])`, adicionar:

```python
            # Assign agent profile to conversation if broadcast has one configured
            if broadcast.get("agent_profile_id"):
                try:
                    conversation = get_or_create_conversation(lead["id"], channel_id)
                    update_conversation(
                        conversation["id"],
                        agent_profile_id=broadcast["agent_profile_id"],
                        status="template_sent",
                    )
                except Exception as ce:
                    logger.warning(f"Could not assign agent profile to conversation for {lead['phone']}: {ce}")
```

O bloco completo após a mudança (contexto para localizar onde inserir):

```python
            mark_broadcast_lead_sent(bl["id"])
            increment_broadcast_sent(broadcast_id)

            # Assign agent profile to conversation if broadcast has one configured
            if broadcast.get("agent_profile_id"):
                try:
                    conversation = get_or_create_conversation(lead["id"], channel_id)
                    update_conversation(
                        conversation["id"],
                        agent_profile_id=broadcast["agent_profile_id"],
                        status="template_sent",
                    )
                except Exception as ce:
                    logger.warning(f"Could not assign agent profile to conversation for {lead['phone']}: {ce}")

            # Enroll in cadence if configured
            if broadcast.get("cadence_id"):
```

- [ ] **Step 4: Rodar testes**

```bash
cd backend && python -m pytest tests/test_multi_agent.py -v
```
Esperado: todos PASSAM.

- [ ] **Step 5: Commit**

```bash
git add backend/app/broadcast/worker.py backend/tests/test_multi_agent.py
git commit -m "feat(broadcast): assign agent_profile_id to conversation after template dispatch"
```

---

## Task 7: Buffer processor — resolver e passar agent_profile_id

**Files:**
- Modify: `backend/app/buffer/processor.py`

- [ ] **Step 1: Escrever teste**

Adicionar ao `tests/test_multi_agent.py`:

```python
def test_processor_resolves_agent_profile_from_conversation():
    """Processor usa agent_profile_id da conversa (prioridade sobre canal)."""
    conv_agent = "ap-outbound"
    channel_agent = "ap-inbound"

    conversation = {
        "id": "conv-1",
        "stage": "atacado",
        "status": "active",
        "agent_profile_id": conv_agent,
    }
    channel = {
        "id": "ch-1",
        "agent_profiles": {"id": channel_agent, "name": "Inbound"},
    }

    from app.buffer.processor import _resolve_agent_profile_id
    result = _resolve_agent_profile_id(conversation, channel)
    assert result == conv_agent


def test_processor_falls_back_to_channel_agent():
    """Sem agent_profile_id na conversa, usa o agente do canal."""
    channel_agent = "ap-inbound"
    conversation = {"id": "conv-1", "stage": "secretaria", "status": "active"}
    channel = {
        "id": "ch-1",
        "agent_profiles": {"id": channel_agent, "name": "Inbound"},
    }

    from app.buffer.processor import _resolve_agent_profile_id
    result = _resolve_agent_profile_id(conversation, channel)
    assert result == channel_agent


def test_processor_returns_none_when_no_agent():
    """Sem agente em conversa nem canal, retorna None (human-only mode)."""
    conversation = {"id": "conv-1", "stage": "secretaria", "status": "active"}
    channel = {"id": "ch-1"}

    from app.buffer.processor import _resolve_agent_profile_id
    result = _resolve_agent_profile_id(conversation, channel)
    assert result is None
```

- [ ] **Step 2: Rodar testes (devem falhar — função não existe)**

```bash
cd backend && python -m pytest tests/test_multi_agent.py::test_processor_resolves_agent_profile_from_conversation -v
```
Esperado: `ImportError`.

- [ ] **Step 3: Atualizar `buffer/processor.py`**

Adicionar a função auxiliar logo após as importações:

```python
def _resolve_agent_profile_id(conversation: dict, channel: dict) -> str | None:
    """Resolve which agent_profile_id to use for this conversation.

    Priority:
    1. conversation.agent_profile_id (set by broadcast worker)
    2. channel.agent_profiles.id (default channel agent)
    3. None (human-only mode)
    """
    conv_agent = conversation.get("agent_profile_id")
    if conv_agent:
        return conv_agent
    channel_profile = channel.get("agent_profiles")
    if channel_profile:
        return channel_profile.get("id")
    return None
```

Alterar o bloco que detecta o agent profile (substituir o check atual `if not agent_profile`):

```python
    # Resolve agent profile: conversation takes priority over channel default
    agent_profile_id = _resolve_agent_profile_id(conversation, channel)
    if not agent_profile_id:
        logger.info(f"No agent profile for channel {channel_id}, human-only mode")
        _update_last_msg(conversation["id"])
        return

    # Run AI agent
    try:
        conversation["leads"] = lead
        response = await run_agent(conversation, resolved_text, agent_profile_id=agent_profile_id)
    except Exception as e:
        logger.error(f"Agent error for {phone}: {e}", exc_info=True)
        _update_last_msg(conversation["id"])
        return
```

Remover o bloco antigo:
```python
    # Check if channel has an agent profile
    agent_profile = channel.get("agent_profiles")
    if not agent_profile:
        logger.info(f"No agent profile for channel {channel_id}, human-only mode")
        _update_last_msg(conversation["id"])
        return

    # Run AI agent
    try:
        conversation["leads"] = lead
        response = await run_agent(conversation, resolved_text)
```

- [ ] **Step 4: Rodar todos os testes**

```bash
cd backend && python -m pytest --tb=short -q
```
Esperado: todos PASSAM.

- [ ] **Step 5: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_multi_agent.py
git commit -m "feat(processor): resolve agent_profile_id from conversation with channel fallback"
```

---

## Task 8: Frontend — API de broadcasts aceita agent_profile_id

**Files:**
- Modify: `frontend/src/app/api/broadcasts/route.ts`
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Adicionar `agent_profile_id` ao type `Broadcast` em `types.ts`**

Localizar a interface `Broadcast` (ou `BroadcastRecord`) e adicionar o campo:

```typescript
agent_profile_id: string | null;
```

- [ ] **Step 2: Atualizar `route.ts` para persistir `agent_profile_id`**

No `POST handler`, adicionar `agent_profile_id` ao insert:

```typescript
export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("broadcasts")
    .insert({
      name: body.name,
      channel_id: body.channel_id || null,
      template_name: body.template_name,
      template_preset_id: body.template_preset_id || null,
      template_variables: body.template_variables || {},
      send_interval_min: body.send_interval_min || 3,
      send_interval_max: body.send_interval_max || 8,
      cadence_id: body.cadence_id || null,
      scheduled_at: body.scheduled_at || null,
      agent_profile_id: body.agent_profile_id || null,   // <- NOVO
      status: body.scheduled_at ? "scheduled" : "draft",
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/broadcasts/route.ts frontend/src/lib/types.ts
git commit -m "feat(frontend/api): persist agent_profile_id on broadcast creation"
```

---

## Task 9: Frontend — Dropdown de agente no modal de criação de broadcast

**Files:**
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx`

- [ ] **Step 1: Adicionar estado e fetch de agentes**

No topo do componente, adicionar:

```typescript
import type { Channel, Cadence, TemplatePreset, AgentProfile } from "@/lib/types";

// Dentro do componente, junto com os outros estados:
const [agentProfiles, setAgentProfiles] = useState<AgentProfile[]>([]);
const [agentProfileId, setAgentProfileId] = useState("");
```

No `useEffect` que já busca canais e cadências, adicionar:

```typescript
fetch("/api/agent-profiles")
  .then((r) => r.json())
  .then((d) => setAgentProfiles(Array.isArray(d) ? d : d.data || []));
```

- [ ] **Step 2: Adicionar campo no formulário (Step 1 do modal)**

Logo após o select de cadência, adicionar:

```tsx
<div>
  <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">
    Agente
  </label>
  <select
    value={agentProfileId}
    onChange={(e) => setAgentProfileId(e.target.value)}
    className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
  >
    <option value="">Agente padrão do canal</option>
    {agentProfiles.map((a) => (
      <option key={a.id} value={a.id}>{a.name}</option>
    ))}
  </select>
</div>
```

- [ ] **Step 3: Incluir no payload de criação**

No `handleCreate`, dentro do `body` do fetch para `/api/broadcasts`, adicionar:

```typescript
agent_profile_id: agentProfileId || null,
```

- [ ] **Step 4: Incluir no reset e na tela de revisão (Step 3)**

No `resetForm`:
```typescript
setAgentProfileId("");
```

Na tela de revisão (step 3), dentro da div de resumo:
```tsx
{agentProfileId && (
  <p>
    <span className="text-[#5f6368]">Agente:</span>{" "}
    <strong>{agentProfiles.find((a) => a.id === agentProfileId)?.name}</strong>
  </p>
)}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(frontend): add agent profile selector to create broadcast modal"
```

---

## Task 10: Limpeza — remover arquivos de prompt legados

**Files:**
- Delete: `backend/app/agent/prompts/secretaria.py`
- Delete: `backend/app/agent/prompts/atacado.py`
- Delete: `backend/app/agent/prompts/private_label.py`
- Delete: `backend/app/agent/prompts/exportacao.py`
- Delete: `backend/app/agent/prompts/consumo.py`

- [ ] **Step 1: Verificar que nenhum arquivo importa dos paths antigos**

```bash
grep -r "from app.agent.prompts.secretaria\|from app.agent.prompts.atacado\|from app.agent.prompts.private_label\|from app.agent.prompts.exportacao\|from app.agent.prompts.consumo" backend/app/ --include="*.py"
```
Esperado: nenhum resultado.

- [ ] **Step 2: Remover arquivos legados**

```bash
rm backend/app/agent/prompts/secretaria.py
rm backend/app/agent/prompts/atacado.py
rm backend/app/agent/prompts/private_label.py
rm backend/app/agent/prompts/exportacao.py
rm backend/app/agent/prompts/consumo.py
```

- [ ] **Step 3: Rodar suite completa**

```bash
cd backend && python -m pytest --tb=short -q
```
Esperado: todos PASSAM.

- [ ] **Step 4: Commit final**

```bash
git add -A
git commit -m "chore(prompts): remove legacy root-level stage prompt files"
```

---

## Self-Review

### Spec coverage
- ✅ `agent_profile_id` em `conversations` — Task 1
- ✅ `agent_profile_id` em `broadcasts` — Task 1
- ✅ `prompt_key` em `agent_profiles` — Task 1
- ✅ Seed do perfil outbound — Task 1
- ✅ Estrutura `valeria_inbound/` e `valeria_outbound/` — Tasks 2 e 3
- ✅ `PROMPT_REGISTRY` e `get_stage_prompts()` — Task 2
- ✅ Orchestrator dinâmico — Task 4
- ✅ Fix `activate_conversation` (não reseta stage) — Task 5
- ✅ Broadcast worker atribui agente à conversa — Task 6
- ✅ Processor resolve agente por prioridade (conversation > channel) — Task 7
- ✅ Frontend API aceita `agent_profile_id` — Task 8
- ✅ Frontend modal com dropdown de agente — Task 9
- ✅ Prompts outbound com contexto de histórico + resiliência a templates genéricos — Task 3

### Nenhum placeholder encontrado
### Types consistentes: `agent_profile_id: str | None` em Python, `string | null` em TS, `uuid` no SQL
