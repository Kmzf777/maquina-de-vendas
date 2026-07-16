# Varredura de Novos Atendimentos — pós-deploys de 12/07 (noite)

**Janela:** 12/07 16:30 UTC (fim da extração da auditoria inbound 12/07) → 12/07 ~19:15 UTC.
**Deploys na janela (UTC):** N1/N2 ~17:07 · S4 tempo verbal ~17:41 · pacote de polimento P1–P4 ~18:36.
**Escopo:** 6 conversas inbound (5 novas + cauda da Maria Socorro), ~106 mensagens, 100% lidas. 1 template broadcast sem resposta excluído.

## Validações empíricas (fixes anteriores)

- **N2/ponte ❤️:** "Ok muito obrigada" (Maria Socorro 17:16) → reação ❤️. ✓
- **Ponte silêncio de negócio:** Daniel 18:06 (pergunta de lote piloto pós-handoff) → `[ponte] pergunta de negócio detectada — silêncio`. ✓
- **N1 (sem alegação falsa de fotos):** zero ocorrências; caso Edimilson 17:58 mostra o comportamento correto novo — OFERECEU ("quer que eu te mande as fotos?") em vez de alegar envio. ✓
- **Regra 18C funcionando (contraste):** Empório Da Canastra 19:08 "Falo com vc amanhã" → `[agendar_retorno]` p/ 13/07. ✓
- **P4 (pergunta de avanço) pós-18:36:** todos os turnos informativos do Empório terminaram com pergunta. ✓ (amostra pequena)
- **P1 (saudação descolada) pós-18:36:** Brito 18:49 — "boa tarde" em bolha própria. ✓ para o escopo da guarda.
- **NÃO exercitados na janela** (sem tráfego do tipo): S4 tempo verbal pós-17:41 (nenhum enviar_fotos depois do deploy), P2 mídia coalescida, P3 sobrepromessa, Caso 0 (nenhum áudio novo).

## Achado NOVO — F1 (comportamental, prioridade desta rodada)

**Rogério Oliveira, 17:39 — adiamento morno descartado (violação da regra 18C).** Lead de empório em Juiz de Fora, qualificado, máquina comprada, recebeu preços dos dois tamanhos e disse "Vou apresentar para meu genro que é meu sócio e retorno a você. Agradeço sua atenção" → a IA chamou `registrar_sem_interesse_atual`, com um motivo que ADMITE o erro: "Não é rejeição, mas pedido de tempo para decisão". Estado resultante verificado: stage=perdido, ai_enabled=false, **0 follow-ups pendentes** — lead quente morto para a cadência. O mesmo padrão na mesma janela teve 3 tratamentos distintos: AhirNRF ("vou conversar com minha esposa") → nada, correto; Empório ("falo amanhã") → agendar_retorno, correto; Rogério → descarte, errado. A regra 18C exige agendar_retorno/resposta curta e proíbe sem_interesse na 1ª sinalização, mas o gatilho "vou apresentar pro sócio e RETORNO" não está listado nos exemplos.
**Fix recomendado:** (a) prompt — listar "vou apresentar pro meu sócio/esposa/genro e te retorno" como gatilho explícito 18C e proibir `registrar_sem_interesse_atual` quando o lead PROMETE retornar; (b) guarda determinística possível — se o argumento `motivo` da tool contém "não é rejeição"/"pedido de tempo", abortar o descarte (o modelo confessa a contradição no próprio argumento); (c) operacional — resgatar o lead Rogério (religar ai_enabled, stage de volta, retorno agendado).

## Observações menores

- **Run-on pitch+pergunta persiste fora do escopo da P1** (3 ocorrências: Daniel 17:03 e Brito 18:49 com saudação já separada; Edimilson 17:21 na variante "boa {nome},"). É sempre a MESMA frase estereotipada do opener private_label ("...mais gosta de fazer aqui(,) você já tem uma marca criada..."). A P1 cobriu a variante com saudação colada; o resíduo pede ou cue de split adicional no splitter (fronteira antes de "você já tem") ou observação de mais uma janela antes de generalizar — o root cause segue sendo o modelo usar \n simples entre ideias.
- **Vocativo com pushname de negócio:** "fechado, Empório Da Canastra" (19:11) — nome de empresa usado como nome de pessoa; a família de higiene de nomes (_CONVERSATIONAL_NON_NAMES) não cobre razão social.
- Empório: prometeu "te chamo amanhã por volta das 9h" com retorno agendado 13:00 UTC (10h BRT) — descasamento de 1h, cosmético.

## Veredito

Núcleo saudável e fixes anteriores confirmados no que o tráfego permitiu exercitar; zero regressões observadas. **Uma otimização nova é necessária (F1/18C)** — é conversão real vazando, com caso concreto e lead a resgatar — e dois itens seguem em observação (run-on residual do opener e pushname de negócio). S4/P2/P3/Caso 0 ainda sem tráfego pós-deploy que os exercite; próxima janela valida.
