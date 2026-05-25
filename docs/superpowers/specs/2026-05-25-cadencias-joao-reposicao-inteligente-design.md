# Cadências do João — Reposição Inteligente + Follow-up de Cotação

**Data:** 2026-05-25
**Canal:** `NUMERO JOÃO` (`a3a607b1-6bff-4370-8609-b275eef270dd`, `553491461669`, modo `human`, Café Canastra)
**Pipelines envolvidos:** "Reposição - João" (recompra), Atacado/Private Label (cotação)

---

## Diagnóstico (data-driven)

Análise das 2161 mensagens do canal do João no último mês revelou:

- **442 leads de 541 nunca responderam à 1ª msg** (81%) — disparos antigos, fora de escopo.
- **22 leads em janela de perigo 24h-7d** (atendimento iniciado, sem resposta antes da janela Meta fechar).
- **18 leads com cotação enviada (tabela atacado / preço Private Label) sem retorno há 3+ dias** — alvo da cadência #2.
- **775 deals no pipeline "Reposição - João"**, dos quais **598 estão em "Já chamado"** sem follow-up automatizado — alvo da cadência #3.
- **`sales` tem apenas 1 venda registrada** — o time não está estruturando vendas no CRM, logo NÃO podemos usar `sale_created` / `repurchase_window` como gatilhos. Usamos `deal_stage_enter`.

## Modelo de negócio (Café Canastra)

3 linhas de produto, 5 pipelines:
1. **Atacado** (R$300 mín, tabela.cafecanastra.com, frete R$55)
2. **Private Label** (250g R$26,70 / 500g R$48,70, lote mín 100un)
3. **Consumo** final
4. **Exportação**
5. **Reposição - João** (clientes existentes/já contatados)

Tom do João nas mensagens reais: informal mas profissional, primeira pessoa, "Aqui é o João da Café Canastra ☕️", sem CTAs de venda agressivos.

## Decisões estratégicas

1. **Templates UTILITY > marketing.** Meta cobra menos, aprova mais rápido, tem entregabilidade superior. Toda a sequência usa categoria `utility`.
2. **Saídas claras por nó (quick reply 3 opções):** "sim, prosseguir" / "ainda não / depois" / "opt-out". Minimiza ruído e dá sinal limpo para o engine.
3. **Loop preservativo** em "ainda tenho estoque": espera 20d e revisita, em vez de queimar o lead.
4. **Round-robin nos nós de conversão:** quando o lead manifesta intenção, sai automação e entra humano (vendedor da equipe).
5. **Gatilho de recompra = `deal_stage_enter` em "Já chamado" do pipeline "Reposição - João"**, não `sale_created` (que está vazio).

---

## Cadência #2 — `followup_cotacao_3d`

**Universo:** leads em stage `atacado` ou `private_label` que receberam tabela/preço e não responderam há 3+ dias.

**Gatilho:**
- `keyword_received` com keywords: `["tabela", "preço", "valor", "quanto custa", "atacado", "private label"]`
- OU `stage_enter` em `atacado` / `private_label`

**Fluxo:**

```
[Gatilho]
    │
    ▼ WAIT 3 dias
[CONDIÇÃO: replied_recently 3d?] ── SIM → END
    │ NÃO
    ▼
[TEMPLATE UTILITY: continuidade_cotacao_pendente]
   Botões: [Sim, vamos prosseguir] [Tirar dúvidas antes] [Não tenho mais interesse]
    │
    ▼ WAIT 4 dias
[CONDIÇÃO: replied_recently 4d?]
    ├─ SIM → AÇÃO: assign_round_robin + add_tag "quente_cotacao" → END
    └─ NÃO
        ▼
[AÇÃO: add_tag "cold_cotacao"]
[AÇÃO: mark_deal_lost]
[END]
```

## Cadência #3 — `reposicao_inteligente`

**Universo:** 598 deals no stage "Já chamado" do pipeline "Reposição - João".

**Gatilho:** `deal_stage_enter` no stage_id correspondente a "Já chamado" no pipeline "Reposição - João".

**Fluxo:**

```
[Gatilho: deal entrou em "Já chamado"]
    │
    ▼ WAIT 5 dias
[CONDIÇÃO: replied_recently 5d?] ── SIM → END (já em conversa)
    │ NÃO
    ▼
[TEMPLATE UTILITY: check_estoque_reposicao]
   Botões: [Preciso repor] [Ainda tenho estoque] [Não atendo mais]
    │
    ▼ Aguarda resposta via keyword_received
   ┌─────┴─────┬─────────────┬──────────────────────┐
   ▼           ▼             ▼                      ▼ sem resposta 7d
"Preciso  "Ainda tenho"  "Não atendo"               │
 repor"      │              │                       ▼
   │         WAIT 20d       move_deal_stage  [TEMPLATE UTILITY:
   ▼         (revisita)     "Perdido"        lembrete_reposicao_final]
move_deal    └→ loop max 3  + add_tag        Botões: [Quero conversar]
"Negociação"  voltas        "não_recompra"   [Não preciso por agora]
 + assign                    END             [Tirar dos contatos]
 _round_robin                                  │
   END                                         ▼
                                        ┌──────┼──────┬─────────┐
                                        ▼      ▼      ▼         ▼ sem resposta 7d
                                   "Quero  "Não    "Tirar"      │
                                    conv"  preciso"             ▼
                                       │     │       │      add_tag
                                       ▼     WAIT    mark_deal_lost  "dormente_60d"
                                  move_deal  60d     + add_tag       move_deal
                                  "Negociação" loop  "opt_out"       "Perdido"
                                   + assign                          END
                                   _round_robin
                                    END
```

---

## Templates UTILITY a criar

### 1. `check_estoque_reposicao` (cadência #3, passo 1)

```json
{
  "name": "check_estoque_reposicao",
  "language": "pt_BR",
  "category": "utility",
  "components": [
    {
      "type": "BODY",
      "text": "Olá {{1}}, aqui é o João da Café Canastra ☕\n\nVocê estava nos meus contatos de reposição em nosso sistema.\nComo está seu estoque atual?",
      "example": { "body_text": [["João"]] }
    },
    { "type": "FOOTER", "text": "João | Café Canastra" },
    {
      "type": "BUTTONS",
      "buttons": [
        { "type": "QUICK_REPLY", "text": "Preciso repor" },
        { "type": "QUICK_REPLY", "text": "Ainda tenho estoque" },
        { "type": "QUICK_REPLY", "text": "Não atendo mais" }
      ]
    }
  ]
}
```

**Justificativa Meta:** check-in operacional de protocolo de reposição em aberto. Sem palavras promocionais, sem CTA de venda.

### 2. `lembrete_reposicao_final` (cadência #3, passo 2)

```json
{
  "name": "lembrete_reposicao_final",
  "language": "pt_BR",
  "category": "utility",
  "components": [
    {
      "type": "BODY",
      "text": "Olá {{1}}, ainda é o João do Café Canastra.\n\nNotei que minha mensagem anterior ficou sem resposta. Me dá só um sinal de positivo ou negativo para eu saber como prosseguir, por favor.",
      "example": { "body_text": [["João"]] }
    },
    { "type": "FOOTER", "text": "João | Café Canastra" },
    {
      "type": "BUTTONS",
      "buttons": [
        { "type": "QUICK_REPLY", "text": "Quero conversar" },
        { "type": "QUICK_REPLY", "text": "Não preciso por agora" },
        { "type": "QUICK_REPLY", "text": "Tirar dos contatos" }
      ]
    }
  ]
}
```

**Justificativa Meta:** follow-up de protocolo aberto sem resposta. Linguagem operacional, neutra.

### 3. `continuidade_cotacao_pendente` (cadência #2)

```json
{
  "name": "continuidade_cotacao_pendente",
  "language": "pt_BR",
  "category": "utility",
  "components": [
    {
      "type": "BODY",
      "text": "Olá {{1}}, aqui é o João da Café Canastra.\n\nSua solicitação de cotação está em aberto em nosso sistema há {{2}} dias.\nConfirme se ainda deseja prosseguir com o atendimento.",
      "example": { "body_text": [["João", "3"]] }
    },
    { "type": "FOOTER", "text": "João | Café Canastra" },
    {
      "type": "BUTTONS",
      "buttons": [
        { "type": "QUICK_REPLY", "text": "Sim, vamos prosseguir" },
        { "type": "QUICK_REPLY", "text": "Tirar dúvidas antes" },
        { "type": "QUICK_REPLY", "text": "Não tenho mais interesse" }
      ]
    }
  ]
}
```

**Justificativa Meta:** atualização sobre protocolo de cotação registrado. Confirmação de interesse — sem oferta promocional.

---

## Plano de execução

1. ✅ Salvar spec (este documento)
2. **Criar 3 templates** via Meta API + registrar em `message_templates`
3. **Aguardar aprovação Meta** (1h a 24h)
4. **Quando aprovados:** criar `campaigns` + `campaign_nodes` via SQL, status `draft`, para o usuário revisar no builder
5. Usuário ativa as cadências
6. Monitorar conversão via campaign_enrollments

## Critérios de sucesso

- 3 templates aprovados como UTILITY (sem recategorização para marketing)
- Cadência #3: ao menos 30% dos 598 deals em "Já chamado" respondem ao 1º template
- Cadência #3: ao menos 10% chegam ao stage "Negociação"
- Cadência #2: ao menos 25% das cotações pendentes recebem follow-up automatizado
- Zero opt-outs forçados (sempre temos opção "Tirar dos contatos" como saída digna)

## Notas

**Aviso de segurança ortogonal:** 29 tabelas no Supabase com RLS desabilitado, incluindo `channels` (que contém access_token Meta em texto claro no `provider_config`). Recomendado abordar antes de aumentar o número de usuários do CRM, mas fora do escopo desta entrega.
