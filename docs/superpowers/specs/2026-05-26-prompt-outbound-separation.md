# Spec: Separação system/user no prompt outbound da Valéria

**Data:** 2026-05-26
**Branch:** feature/outbound-rehearsal-setup
**Escopo:** `valeria_outbound` — fluxo de prospecção ativa

---

## Problema

O `SECRETARIA_PROMPT` de `valeria_outbound/secretaria.py` é um monólito que mistura:
- **Regras de negócio fixas** (postura outbound, funil de qualificação, restrições de segurança)
- **Contexto transitório** (qual mensagem de campanha foi enviada, o fato de que o lead está respondendo agora)

Tudo isso vai para o role `system`, que deveria conter apenas instruções imutáveis. O resultado é perda de autoridade semântica do sistema e impossibilidade de variar o template de campanha sem editar o prompt.

---

## Solução: Opção A — Contexto como primeiro `user` message

### Separação de papéis

| Role | Conteúdo |
|------|----------|
| `system` | Persona da Valéria, regras absolutas, postura outbound, funil de 4 etapas, tipos de engajamento (Sim/Não/texto neutro/curioso/frio), restrições de segurança |
| `user` (turno 1, injetado) | Mensagem da campanha enviada ao lead + nome do lead + aviso de que ele está respondendo agora |
| `user` (turnos seguintes) | Mensagem real do lead (comportamento atual, sem alteração) |

O contexto dinâmico é injetado **somente no primeiro turno** (histórico vazio). Em turnos subsequentes, o histórico já captura implicitamente a origem outbound.

---

## Arquitetura

### 1. `valeria_outbound/secretaria.py` — limpeza

Remover as linhas 1–20 (bloco `## CONTEXTO DESTA ABORDAGEM`). Manter apenas as regras de negócio a partir de `## CONTEXTO OUTBOUND — ABORDAGEM ATIVA`.

### 2. `valeria_outbound/context.py` — novo arquivo

```python
def build_outbound_first_turn_context(campaign_message: str, lead_name: str | None) -> str:
    name_line = f"O lead se chama {lead_name}." if lead_name else ""
    return (
        f"Contexto desta abordagem outbound:\n\n"
        f"Mensagem enviada na campanha:\n---\n{campaign_message}\n---\n\n"
        f"{name_line}\n"
        f"O lead está respondendo a essa mensagem agora."
    ).strip()
```

Recebe `campaign_message` (string, vinda de `lead_context["campaign_message"]`) e `lead_name`. Sem lógica de roteamento, sem efeito colateral.

### 3. `orchestrator.py` — injeção condicional

Após construir `messages = [{role:"system", ...}] + history`, antes de appender `user_text`:

```python
is_outbound = prompt_key == "valeria_outbound"
is_first_turn = len(history) == 0
campaign_message = (lead_context or {}).get("campaign_message")

if is_outbound and is_first_turn and campaign_message:
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context
    ctx = build_outbound_first_turn_context(campaign_message, lead.get("name"))
    messages.append({"role": "user", "content": ctx})

messages.append({"role": "user", "content": user_text})
```

A lógica de `mudar_stage` no loop de tool calls **não é alterada** — ela reconstrói apenas o `system` message (`messages[0]`), nunca os `user` messages do histórico.

---

## Contrato de entrada

Para ativar o contexto dinâmico, o caller de `run_agent` deve passar:

```python
lead_context = {
    "campaign_message": "Ola, tudo bem?\nAqui e a Valeria, da Cafe Canastra...",
    # campos existentes continuam funcionando normalmente:
    "name": "João",
    "company": "Padaria do João",
    "previous_stage": None,
    "notes": None,
}
```

Se `campaign_message` estiver ausente ou `lead_context` for `None`, o bloco de injeção é ignorado silenciosamente — sem quebrar fluxos que não passam esse campo.

---

## O que NÃO muda

- `base.py` e todos os prompts inbound
- O loop de tool calls e o tratamento de `registrar_optout` / `encaminhar_humano`
- Os outros stages outbound (`atacado`, `private_label`, `exportacao`, `consumo`)
- A estrutura do `PROMPT_REGISTRY`
- A API client (continua usando `chat.completions.create`)

---

## Arquivos alterados

| Arquivo | Tipo de mudança |
|---------|----------------|
| `backend/app/agent/prompts/valeria_outbound/secretaria.py` | Remover linhas 1–20 |
| `backend/app/agent/prompts/valeria_outbound/context.py` | Criar (novo) |
| `backend/app/agent/orchestrator.py` | Adicionar bloco de injeção condicional em `run_agent()` |
