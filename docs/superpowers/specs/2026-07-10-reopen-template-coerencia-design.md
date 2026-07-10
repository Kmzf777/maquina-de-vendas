# Coerência comercial do template de reabertura do follow-up (Rodada 5, 10/07/2026)

## Problema

`fire_reopen_template` (follow-up multi-touch e `ai_scheduled_return`) reabria a janela
de 24h da Meta com o template `continuar_conversa`, cujo corpo assume CULPA NOSSA por
atraso ("Infelizmente não consegui te responder a tempo e a nossa janela de atendimento
fechou. Peço desculpas pela espera!"). O gatilho real é o oposto: quem silenciou foi o
LEAD (toque seq=2+ da cadência, ou retorno agendado vencido). Incoerência observada ao
vivo em 10/07 (5 leads: Tainara, Luciana, Maria, Lucas, Yandra) — a Valéria respondeu
tudo em minutos e em seguida "pediu desculpas pela demora".

Agravante estrutural: o T2 (D+1) é agendado minutos DEPOIS da última mensagem do lead,
então ele vence ~24h+ε após ela — a janela está SEMPRE recém-fechada quando o T2 dispara.
Na prática, o T2 de lead silencioso é SEMPRE o template de reabertura (T3/T4 se dobram
nele via R1). O template de reabertura É a cadência visível ao lead silencioso — a
escolha do copy é a decisão comercial inteira.

## Alternativas avaliadas

1. **Manter `continuar_conversa`** — rejeitado (incoerência que motivou a auditoria).
2. **Criar template novo sob medida** — melhor copy possível, mas exige aprovação Meta
   (dias) e risco de classificação MARKETING. Fica como evolução futura.
3. **Re-tunar offsets da cadência (T2 dentro da janela)** — muda o ritmo comercial;
   ortogonal ao problema de copy; YAGNI agora.
4. **Trocar para um UTILITY aprovado coerente do catálogo** — ESCOLHIDA.

## Decisão

Template de reabertura passa a ser **`utilidade_geral_confirmacao_v1`** (aprovado,
categoria `utility`, idioma de aprovação `en_US` com corpo em português):

> "Ola, {{1}}! O Cafe Canastra esta aguardando sua confirmacao sobre {{2}} desde {{3}}.
> Responda essa mensagem para finalizarmos seu atendimento."
> Botões QUICK_REPLY: "Continuar atendimento" / "Tirar duvidas" / "Nao tenho interesse".

Coerência: enquadra o silêncio como pendência DO LEAD, sem pedir desculpas por atraso
inexistente; os botões dão caminho de continuação E saída digna ("Nao tenho interesse" →
tratado pelo fluxo normal de soft rejection na resposta).

### Parâmetros (posicionais, determinísticos)

- `{{1}}` nome: `sanitize_display_name(lead.name)` → primeiro nome; fallback
  `_NAME_FALLBACK` ("tudo bem") — mesmo padrão do template do João.
- `{{2}}` assunto: constante honesta `"a continuidade do atendimento"` (há de fato um
  atendimento em aberto — a conversa com a Valéria).
- `{{3}}` data: `conversations.last_customer_message_at` em dd/mm/YYYY (BRT,
  `_FOLLOWUP_TZ_BR`); fallback `now` se ausente.

### Invariantes preservados

- `language_code` = idioma da APROVAÇÃO (`en_US`) — armadilha de locale conhecida
  (template enviado com locale divergente → 404/erro de params).
- Gate de compliance UTILITY (`_reopen_template_category`) continua e passa (o novo
  template é utility).
- Persistido == enviado (Rodada 4): `_reopen_template_body` agora RENDERIZA o corpo com
  os mesmos params enviados; fallback = cópia fiel do corpo aprovado com os params
  substituídos.
- `awaiting_reopen` é consumido por QUALQUER resposta do lead (TTL 7d) — não depende de
  botão específico; mecânica R1 intacta.
- Intent do disparo continua `GENERIC` (`classify_template_intent`): não reverte o lead
  ao frame frio nem muda a resolução de persona.

## Fora de escopo

Scripts one-off (`recover_joao_templates.py` etc.) e disparos manuais de broadcast que
usam `continuar_conversa` por escolha do operador. Re-tuning de offsets da cadência.
