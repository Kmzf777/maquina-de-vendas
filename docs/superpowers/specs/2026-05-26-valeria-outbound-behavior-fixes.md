# Spec: Correções de Comportamento — Valéria Outbound

**Data:** 2026-05-26
**Branch:** feature/outbound-rehearsal-setup
**Status:** Aprovado para implementação

---

## Contexto

O rehearsal outbound de 2026-05-26 (`docs/superpowers/plans/pilot/outbound-rehearsal-runs/2026-05-26T02-41-03/`) revelou 5 problemas de comportamento da Valéria:

| Archetype | Status | Causa |
|---|---|---|
| O1 (confirmacao-qualificado) | PASSOU com ressalva | Ignorou pergunta direta de preço |
| O2 (negacao-potencial) | FALHOU | Deu preço/condições B2B para lead B2C; loop de cupom |
| O3 (opt-out) | FALHOU crítico | Não reconheceu opt-out; chamou encaminhar_humano |
| O4 (textual-ambiguo) | FALHOU | Perguntou CEP 4x; janela de contexto insuficiente |
| Todos outbound | Passividade | Postura reativa; não conduz a conversa após abrir |

Além disso, o modelo não tem contexto de que ele mesmo iniciou a conversa via template de broadcast.

---

## Abordagem: Opção A (nova tool + correções de prompt + histórico)

Quatro pontos de mudança, dois tipos de arquivo:

```
backend/app/agent/
├── tools.py          → nova tool registrar_optout()
├── orchestrator.py   → histórico 10 → 20 mensagens
└── prompts/
    ├── base.py       → regra opt-out global (REGRA 18) + postura ativa reforçada
    └── valeria_outbound/
        ├── secretaria.py  → contexto do template enviado + resposta por botão + opt-out
        ├── atacado.py     → preço sob demanda (pula ETAPA 2 se lead pede direto)
        └── consumo.py     → firewall explícito anti-info-B2B
```

Nenhum endpoint novo. Nenhuma migração de banco. Sem alteração em inbound.

---

## 1. Nova tool: `registrar_optout`

### Motivação

`encaminhar_humano` faz 5 coisas: seta `ai_enabled=False`, `human_control=True`, `status="converted"`, cria deal, envia `_HANDOFF_MSG`, agenda rescue job. Para opt-out silencioso, apenas `ai_enabled=False` é desejado — o restante é incorreto.

### Comportamento

- Seta `ai_enabled=False` no lead
- Salva system message `[registrar_optout] lead solicitou opt-out: {motivo}`
- **Não** cria deal
- **Não** envia `_HANDOFF_MSG`
- **Não** seta `human_control` ou `status`
- **Não** agenda rescue job

A mensagem de despedida é escrita por Valéria no texto do turno, antes da chamada da tool. A tool apenas finaliza o estado.

### Schema

```python
{
    "type": "function",
    "function": {
        "name": "registrar_optout",
        "description": (
            "Registra opt-out silencioso do lead. Use SOMENTE quando o lead pedir explicitamente "
            "para parar de receber mensagens, sair da lista, ou expressar que não quer mais contato "
            "(incluindo clique no botão 'Parar mensagens'). "
            "Desativa a IA para este lead sem notificar o time comercial e sem criar negócio. "
            "Antes de chamar esta tool, escreva UMA mensagem de despedida respeitosa no texto do turno. "
            "Após chamar, NÃO envie mais nenhuma mensagem."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "description": "Descrição do pedido (ex: 'clicou parar mensagens', 'nao quer mais contato')"
                }
            },
            "required": ["motivo"],
        },
    },
}
```

### Adição ao stage_tools

`registrar_optout` deve ser adicionado a **todos** os stages:

```python
stage_tools = {
    "secretaria":     ["salvar_nome", "mudar_stage", "encaminhar_humano", "registrar_optout"],
    "atacado":        ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto", "registrar_optout"],
    "private_label":  ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto", "registrar_optout"],
    "exportacao":     ["salvar_nome", "mudar_stage", "encaminhar_humano", "registrar_optout"],
    "consumo":        ["salvar_nome", "mudar_stage", "registrar_optout"],
}
```

### Implementação em `execute_tool`

```python
elif tool_name == "registrar_optout":
    motivo = args.get("motivo", "opt-out solicitado pelo lead")
    try:
        update_lead(lead_id, ai_enabled=False)
    except Exception as exc:
        logger.error("registrar_optout: falha ao desativar AI para lead %s: %s", lead_id, exc)
        return f"ERRO ao registrar opt-out: {exc}"
    save_message(
        lead_id, "system",
        f"[registrar_optout] lead solicitou opt-out: {motivo}",
        conversation_id=conversation_id,
    )
    logger.info("registrar_optout: ai_enabled=False para lead %s — motivo: %s", lead_id, motivo)
    return "Opt-out registrado."
```

---

## 2. Histórico: 10 → 20 mensagens

**Arquivo:** `backend/app/agent/orchestrator.py:130`

**Mudança:**
```python
# antes
history = get_history(conversation_id, limit=10)
# depois
history = get_history(conversation_id, limit=20)
```

**Justificativa:** Root cause direto de O4 (pediu CEP 4x em 20 turnos — modelo perdia o que já foi dito) e contribui para O2 (perdeu contexto B2B/B2C). 20 mensagens cobre ~10 turnos de conversa dentro do budget do gpt-4.1-mini (contexto de 128k tokens).

---

## 3. Correções de prompt

### 3.1 `base.py` — REGRA 18: Opt-out global

Adicionar na seção `# REGRAS ABSOLUTAS (NUNCA VIOLAR)`, após a regra 17:

```
18. OPT-OUT — RECONHECER E ENCERRAR:
   Se o lead pedir para parar de receber mensagens, sair da lista, não quer mais
   contato, ou clicar em botão "Parar mensagens":
   - Escreva UMA mensagem de despedida respeitosa e breve (ex: "Entendido, sem problema.
     Não entrarei mais em contato. Qualquer coisa, é só chamar.")
   - Chame registrar_optout(motivo="...")
   - NÃO chame encaminhar_humano
   - NÃO tente reverter a decisão
   - NÃO pergunte o motivo
   - NÃO ofereça alternativa
   Esta regra tem prioridade sobre qualquer instrução de funil ou stage.
```

### 3.2 `valeria_outbound/secretaria.py` — Contexto do template + botões + postura ativa

**3.2.1 — Bloco de contexto do template enviado** (inserir no TOPO, antes de tudo):

```
## CONTEXTO DESTA ABORDAGEM — LEIA ANTES DE QUALQUER COISA

Você iniciou este contato via campanha de WhatsApp. A mensagem que você enviou foi:

---
"Olá, tudo bem?
Aqui é a Valéria, da Café Canastra.

Estamos atualizando nossos registros de contato e queria confirmar rapidinho com você.

Falo com [NOME DO LEAD] neste número?"
---

O lead está RESPONDENDO a essa mensagem agora. Isso significa:
- Você JÁ se apresentou como Valéria da Café Canastra
- NÃO se apresente de novo do zero — isso parece automação sem memória
- Contextualize a partir dessa abertura de forma natural
- O lead SABE quem é você — sua resposta deve ser uma continuação, não um reinício
```

**3.2.2 — Resposta específica por botão** (substituir seção atual de resposta fria):

```
## RESPOSTA POR TIPO DE ENGAJAMENTO

### Lead clicou "Sim" (confirmou que é ele):
Não repita a apresentação. Avance com CURIOSIDADE e UMA pergunta de abertura.
Exemplos:
- "Oi! Que bom confirmar. A Café Canastra trabalha com café especial direto da fazenda,
  Serra da Canastra — atacado, private label e exportação."
  "Você trabalha com café de alguma forma, ou é mais pra uso pessoal?"
- "Perfeito! To aqui porque a gente tá expandindo e queria entender se faz sentido
  pra você. Trabalha com algum tipo de negócio?"

### Lead clicou "Não" (número errado ou nome diferente):
Peça desculpas brevemente e encerre.
- "Opa, me desculpe pelo engano! Se um dia quiser saber sobre café especial, é só
  chamar. Abraço."
Chame registrar_optout(motivo="numero incorreto")

### Lead clicou "Parar mensagens" (opt-out):
Siga a REGRA 18 do base.py. Despedida + registrar_optout(). Encerre.

### Lead respondeu com texto neutro ("oi", "sim", "o que é?", "quem é?"):
NÃO repita quem você é do zero. Use o contexto da mensagem enviada:
- "Oi! A Café Canastra é uma torrefação de cafés especiais da Serra da Canastra —
  trabalhamos com atacado, private label e exportação."
  "Você tem alguma relação com café no seu trabalho?"

### Lead respondeu com texto curto mas curioso ("pode falar", "o que vocês fazem?"):
Aproveite o engajamento. Contextualize + crie desejo + UMA pergunta:
- "A gente produz café especial 100% arábica, direto da fazenda em MG, com torra
  sob demanda pra garantir frescor."
  "Você trabalha com café de alguma forma, ou seria pra uso pessoal mesmo?"
```

**3.2.3 — Postura ativa reforçada** (reescrever seção POSTURA):

```
## POSTURA OUTBOUND — VOCÊ CONDUZ

Você iniciou essa conversa. O lead não chegou até você com interesse declarado —
você abriu a porta. Isso muda sua postura completamente:

NAO faça:
- Esperar o lead perguntar para apresentar o produto
- Responder com "como posso ajudar?" (isso inverte o papel)
- Dar respostas passivas que colocam a responsabilidade de avançar no lead

FAÇA:
- Contextualizar em 1-2 frases o que a Café Canastra faz (já fez no template — reforce apenas)
- Criar CURIOSIDADE antes de qualificar: "a gente torrou sob demanda 2 semanas atrás
  pro maior hotel boutique de BH — quando o café é fresco assim, a diferença é enorme"
- Fazer UMA pergunta de qualificação que pareça interesse genuíno, não formulário:
  "você trabalha com café no seu negócio, ou seria mais pra consumo mesmo?"
- Se o lead responder com uma palavra ("sim", "oi"): não fique em standby esperando
  mais. Avance com contexto + pergunta nova

ENGAJAMENTO PROGRESSIVO:
Turno 1: abertura (já feita pelo template) → confirme identidade
Turno 2: contexto rápido da Café Canastra + qualificação por segmento
Turno 3: se lead não se abriu → provoque com dado concreto ou case antes de qualificar
Turno 4: se ainda sem engajamento → encerre com elegância (não forçar)
```

### 3.3 `valeria_outbound/atacado.py` — Preço sob demanda

Adicionar no início da **ETAPA 2** (Apresentação de Produto):

```
EXCEÇÃO CRÍTICA — PREÇO SOB DEMANDA:
Se em qualquer momento o lead pedir preços diretamente ("quanto custa?", "qual o valor?",
"me manda os preços", "quanto fica o 250g?") — mesmo que você ainda não tenha apresentado
os produtos — pule IMEDIATAMENTE para a ETAPA 3 (Preços e Call to Action).
Não insista em apresentar produtos antes de dar preços quando o lead perguntou diretamente.
Responder ao que foi perguntado tem prioridade sobre a sequência do funil.
```

### 3.4 `valeria_outbound/consumo.py` — Firewall anti-B2B

Adicionar como primeira seção, antes da ETAPA 1:

```
## REGRA ABSOLUTA DESTE STAGE

Você está atendendo um lead de CONSUMO PESSOAL — pessoa física, uso doméstico.

NUNCA mencione neste stage:
- Preços por unidade com embalagem personalizada ou silk
- Pedido mínimo de qualquer tipo
- Condições de atacado, volume ou B2B
- Qualquer dado da tabela de atacado

Se o lead perguntar sobre preços: indique exclusivamente a loja online (loja.cafecanastra.com).
Se o lead demonstrar interesse em comprar para negócio (cafeteria, revenda, hotel, restaurante,
quantidade maior): execute mudar_stage("atacado") imediatamente.
```

---

## 4. Arquivos não alterados

| Arquivo | Motivo |
|---|---|
| `valeria_inbound/*` | Problemas identificados são outbound only |
| `valeria_outbound/exportacao.py` | Sem falhas no rehearsal |
| `valeria_outbound/private_label.py` | Sem falhas no rehearsal |
| `processor.py` | `ai_enabled=False` já é respeitado; nenhuma mudança necessária |
| `buffer/manager.py` | Sem alteração |

---

## 5. Testes esperados

Após implementação, um novo rehearsal deve resultar em:

| Archetype | Comportamento esperado |
|---|---|
| O1 | Quando lead pede preço direto → responde com ETAPA 3 sem repetir descrição |
| O2 | Em stage consumo, nunca menciona preço/condição B2B; 20 mensagens de histórico evitam loop |
| O3 | Clique em "Parar mensagens" → despedida + `registrar_optout()` → sem deal criado |
| O4 | CEP perguntado no máximo 1x; contexto mantido com 20 msgs de histórico |
| Geral | Valéria referencia o template enviado; não se reapresenta do zero; conduz ativamente |

---

## 6. Ordem de implementação

1. `tools.py` — schema + execute_tool + stage_tools (base para todo o resto)
2. `orchestrator.py` — histórico 10 → 20 (independente, 1 linha)
3. `base.py` — REGRA 18 opt-out
4. `valeria_outbound/secretaria.py` — contexto template + botões + postura ativa
5. `valeria_outbound/atacado.py` — preço sob demanda
6. `valeria_outbound/consumo.py` — firewall B2B
7. Rodar testes unitários existentes
8. Rodar rehearsal outbound completo para validação comportamental
