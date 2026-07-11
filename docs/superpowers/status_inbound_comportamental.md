# Status — Regras Comportamentais Inbound (ciclo CRO 10-11/07/2026)

Registro definitivo do ciclo de otimização de conversão inbound. Origem: auditorias em
`docs/superpowers/reports/` (auditoria_inbound_hoje, auditoria_inbound_recente, auditoria_inbound_abandono).

## Regras comportamentais injetadas (prompts/descrições de tools)

- **Handoff responde antes** (`encaminhar_humano`, tools.py + prompts inbound private_label/atacado): se a última mensagem do lead contém pergunta respondível (preço, lote mínimo, prazo, formato), a `mensagem_despedida` COMEÇA respondendo — o lead nunca recebe o cartão do João no lugar da resposta.
- **Preço nunca solto** (base.py, bloco de preços + item 30 do checklist): toda mensagem que entrega preço/valor termina com pergunta de fechamento que pede decisão concreta; isento apenas quando o turno encerra via `encaminhar_humano`.
- **Qualificação com âncora** (10/07): handoff "qualificado" exige finalidade concreta + sinal ativo de avanço; emojis/aplausos/monossílabos não qualificam sozinhos.
- **Estabilidade de stage** (10/07): `mudar_stage` só com declaração explícita do lead; reverter exige correção explícita; gatilho determinístico de prefill (`buffer/prefill.py`) classifica a entrada de anúncio sem depender do LLM.
- Nenhum bloqueio hard novo: todas as regras são linguagem/descrição; circuit breaker de turnos preservado.

## Telemetria configurada (warnings fail-open, nunca bloqueiam/mutam)

- **`[HANDOFF SEM RESPOSTA]`** (orchestrator, caminho da tool): última msg do lead com "?" + `mensagem_despedida` sem dígito/R$. Blind spot conhecido: handoff da guarda verbalizada não instrumentado (per-spec).
- **`[PRECO SEM CTA]`** (orchestrator, padrão do [PROMPT ECHO], via `adherence.price_without_cta`): turno com `R$<n>` cuja última linha não termina em "?"; isento em turno de handoff. Limitações aceitas: `r$` minúsculo (proibido no prompt) e emoji após a pergunta.
- **`[STAGE FLAP]`** (executor `mudar_stage`): reversão de stage < 15 min na mesma conversa.
- **`[PREFILL STAGE]`** (buffer/prefill): acionamentos do gatilho determinístico de entrada.
- **`handoffs_verbalizados`** (daily QA report): contagem diária do marcador da guarda determinística.

## Persistência corrigida (10/07)

- Mídia do vendedor via CRM: `wamid` persistido + placeholder no `content` (`[áudio]`/`[imagem]`); leitura retroativa nos dois `get_history` (`describe_media_placeholder`).

## Fora do escopo da IA (assumido pela operação)

- SLA humano pós-handoff (57% dos drop-offs da manhã de 11/07) — tratado com a equipe de vendas; watchdog `handoff_sla_breach` segue como detector.

## Observar nos próximos dias

- Taxa residual dos warnings `[PRECO SEM CTA]`/`[HANDOFF SEM RESPOSTA]` (promover a métrica de QA só se justificar) e `handoffs_verbalizados` no relatório diário.
