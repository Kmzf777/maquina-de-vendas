# Plano de Perfeição Outbound — Design

**Data:** 2026-06-22
**Autor:** Valéria Outbound Audit
**Status:** Aguardando revisão do usuário

## Contexto

O Inbound está sólido. O foco agora é deixar a persona **Valéria Outbound** uma máquina
de conversão ativa. A auditoria do cérebro outbound (`valeria_outbound/*`, `base.py`,
`orchestrator.py`) e da infra de follow-up (`follow_up/*`, `buffer/processor.py`),
cruzada com dados reais de produção, revelou três frentes de melhoria. Cada uma vira
um épico independente abaixo.

### Achados de dados (produção, 1.165 leads)

| Campo | Preenchimento | Implicação |
|---|---|---|
| `name` | 99% | Único sinal de personalização escalável hoje |
| `company` | 17% | Existe mas **não é injetado** no prompt |
| `endereco`, `razao_social`, `sale_value`, `utm_*` | 0% | Personalização geográfica/histórico é **impossível** com campos atuais |
| `phone` | 99% | **DDD é proxy geográfico gratuito** (alavanca escolhida) |

## Decisões tomadas (brainstorming)

1. **Personalização geográfica** → derivar **região a partir do DDD** do telefone. Sem captura nova.
2. **Gatilho de follow-up** → agendar quando o lead **engajou e esfriou** (respondeu ao menos
   1x no outbound e depois silenciou), não só quando há "interesse comercial claro".
3. **Objeções** → escopo único nesta entrega: tratar **"onde você pegou meu número?"** (LGPD/confiança).

Fora de escopo nesta spec (registrados como backlog): preço-sob-demanda na secretaria, cofre
de prova social, escassez/urgência legítima.

---

## Épico A — Personalização por Região (DDD)

### Objetivo
Permitir que a Valéria abra com conexão regional genuína ("vi que você é de Minas, o pessoal
daí curte café especial") logo no início, sem depender do lead revelar a localização.

### Componentes

**A1. Helper `ddd_to_region(phone) -> str | None`** (novo, em `app/leads/service.py` ou
`app/utils/geo.py`)
- Entrada: telefone cru (`phone`/`wa_id`). Extrai o DDD (2 dígitos após `55`).
- Saída: nome da região/estado de referência (ex.: DDD 31/34/35/37/38 → "Minas Gerais";
  61 → "Brasília/DF"; 11–19 → "São Paulo"; 21/22/24 → "Rio de Janeiro"; etc.).
- DDD desconhecido/telefone internacional → `None`.
- **Unidade testável isolada:** mapa DDD→região é tabela pura; testes cobrem os principais DDDs,
  número sem 55, número curto, DDD inexistente.

**A2. Plumbing no `lead_context`** (`buffer/processor.py:572` e o caminho `ai_reengage`)
- Após montar `lead_context`, injetar:
  - `lead_region` = `ddd_to_region(lead["phone"])` quando houver;
  - `company` = `lead.get("company")` quando houver (hoje existe mas não chega ao prompt).

**A3. Renderização na persona** (`base.py`, bloco `<crm_data>`)
- Quando `lead_region` presente, adicionar linha com **instrução de uso cauteloso**:
  > "Região provável do lead (derivada do DDD, não confirmada): {região}. Você PODE usar isso
  > para criar conexão regional leve e genuína no aquecimento — NUNCA afirme como certeza
  > ('você é de X', proibido), use forma suave ('vi que seu DDD é de X, você é de lá?')."
- Guard-rail crítico: o DDD **não é** a cidade exata e o número pode ser portado. A instrução
  deve impedir afirmação categórica e impedir que vire pergunta de qualificação pesada (não
  pode violar a Regra 0 de aquecimento).

**A4. Hipótese de segmento da campanha** (`valeria_outbound/context.py` +
ponto de origem do disparo)
- No disparo (broadcast/dispatcher), persistir `metadata.campaign_segment` quando a campanha
  tiver segmento-alvo (atacado/private_label/etc.).
- `build_outbound_first_turn_context` passa a receber e injetar o segmento como **hipótese
  suave**, não como fato: "esta campanha mirava leads de atacado — trate como hipótese, confirme
  na conversa, não pressuponha (Regra 21 anti-premissa)".

### Fora de escopo (A)
Captura ativa de cidade via ferramenta; enriquecimento por CNPJ. Backlog futuro.

---

## Épico B — Autonomia de Follow-up (o vácuo / ghosting)

### Objetivo
Cobrir o cenário real: lead responde "Sim", a Valéria aquece, o lead some **morno** (sem
interesse comercial declarado). Hoje isso **não agenda nenhum follow-up**.

### Componentes

**B1. Novo gatilho "engajou e esfriou"** (`buffer/processor.py`, bloco de agendamento ~`:670`)
- Hoje: agenda só se `interest` (tool `marcar_interesse`).
- Novo: se `is_outbound` E o lead já respondeu ao menos 1x nesta conversa (há mensagem `user`
  no histórico) E `followup_enabled` E canal IA → agendar follow-up mesmo sem `interest`.
- Idempotência: `schedule_followup` já cancela pendentes anteriores e recria — mantém 1 ciclo
  por conversa. Não duplica com o caminho `interest`.
- **Não** agendar para: opt-out, soft rejection (`registrar_sem_interesse_atual`), handoff,
  canal humano, lead que já é cliente.

**B2. Unificar a voz do follow-up com a persona Valéria**
(`follow_up/scheduler.py::_generate_followup_message`)
- Hoje usa system prompt Gemini **genérico** ("Você é um assistente de vendas..."), ignorando
  as regras de voz (acentos, sem ponto final, fragmentação, sem emoji).
- Mudança: a geração do follow-up deve carregar a persona Valéria. Duas opções de implementação
  (decidir no plano):
  - (b1) Reaproveitar o `base.py` como system prompt + um wrapper de "reengajamento";
  - (b2) Convergir o follow-up padrão outbound para o handler `ai_reengage` (que já usa
    `run_agent` com a persona `valeria_outbound`), com uma instrução de nudge.
- Requisito invariável: a mensagem de follow-up segue o MODELO DE ESCRITA do `base.py`.

**B3. Clamp de janela comercial no follow-up padrão**
(`follow_up/service.py::schedule_followup`)
- Hoje só `handoff_rescue` passa por `_clamp_to_business_window`. Os jobs 1h/23h podem disparar
  de madrugada.
- Mudança: aplicar `_clamp_to_business_window` ao `fire_at` dos jobs seq=1 e seq=2.
- Atenção: o clamp empurra para o próximo horário útil — validar que isso não estoura a janela
  Meta de 24h (o guard de `process_due_followups` já cancela `window_expired`, então é seguro,
  mas o seq=2 a 23h + clamp pode virar `window_expired` em vez de enviar; documentar o trade-off).

### Fora de escopo (B)
Template aprovado de reengajamento >24h (precisa de aprovação Meta — backlog separado).

---

## Épico C — Objeção "Onde você pegou meu número?" (LGPD)

### Objetivo
Tratar com transparência a objeção de privacidade/desconfiança — a mais perigosa do frio e
sensível a LGPD. Hoje não há tratamento explícito; a IA improvisa.

### Componentes

**C1. Nova subseção em `valeria_outbound/secretaria.py`** (cenários de entrada)
- Gatilhos: "onde pegou meu número", "como conseguiu meu contato", "quem te passou meu número",
  "não autorizei contato".
- Roteiro: reconhecer com transparência + **não inventar** origem. Mensagem honesta sobre o
  cadastro/base de contato comercial da Café Canastra + abrir a porta de saída imediata
  (respeito à decisão do lead) ANTES de qualquer pergunta:
  > "seu contato veio da nossa base comercial de cadastros\n\nse não fizer sentido pra você,
  > é só me avisar que removo agora mesmo\n\nmas se café especial direto da fazenda te
  > interessar, posso te contar rapidinho"
- Se o lead pedir remoção/demonstrar incômodo → `registrar_optout` (Hard Opt-out, Regra 18A).
- Se demonstrar curiosidade → segue o aquecimento normal (Regra 0).

**C2. Reforço curto no `base.py`** (situações especiais)
- Uma linha apontando que objeção de origem do número = transparência + porta de saída +
  nunca inventar quem passou o número (a Regra 13 já proíbe citar terceiros).

### Fora de escopo (C)
Demais objeções priorizadas ficam no backlog.

---

## Testabilidade (visão geral)

| Unidade | Como testar isolada |
|---|---|
| `ddd_to_region` | Tabela pura; teste de DDDs-chave + edge cases |
| Plumbing `lead_context` | Teste de `processor` (espelha `test_processor_lead_context.py`) |
| Renderização região | Teste de `base.py` (espelha `test_base_prompt.py`) |
| Gatilho "engajou e esfriou" | Teste de `processor`: lead outbound respondeu + sem interest → agenda |
| Voz do follow-up | Teste do gerador: saída respeita regras de voz (sem emoji, sem ponto final) |
| Clamp follow-up | Teste de `schedule_followup`: `fire_at` cai na janela 09–16h |
| Objeção LGPD | Teste comportamental (archetype outbound) com a pergunta de origem |

## Ordem de implementação sugerida

1. **Épico C** (LGPD) — menor risco, só prompt, valor imediato.
2. **Épico A** (DDD/região) — helper + plumbing + prompt.
3. **Épico B** (follow-up) — maior superfície (gatilho + voz + clamp), implementar por último.

## Riscos e mitigações

- **DDD ≠ cidade / número portado** → instrução de uso suave, nunca afirmação categórica (A3).
- **Follow-up morno virar spam** → 1 ciclo idempotente por conversa; respeita opt-out/soft/handoff (B1).
- **Voz unificada quebrar guards do `ai_reengage`** → se optar por (b2), manter guards de
  `ai_enabled`/janela 24h/canal humano intactos.
- **Paridade de ambiente** → helper e plumbing funcionam igual em dev/prod (sem `localhost`,
  sem dependência de env).
