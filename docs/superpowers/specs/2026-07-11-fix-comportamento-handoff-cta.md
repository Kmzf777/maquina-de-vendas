# Spec — Handoff responde antes + CTA obrigatório pós-preço

**Origem:** `docs/superpowers/reports/auditoria_inbound_abandono.md` (Categorias 2 e 3).
**Sintoma:** (Cat. 2) lead faz a pergunta mais quente da conversa (preço/pedido mínimo/detalhes) e recebe o cartão do João no lugar da resposta — 3 casos em 11h; (Cat. 3) turno entrega preço sem pergunta de fechamento e o lead fica no vácuo — caso Sandro.

## Abordagens consideradas

- **A) Só prompt/descrição.** Zero código; sem observabilidade — não saberemos se a instrução pegou.
- **B) Prompt/descrição incisivos + telemetria log-only (ESCOLHIDA).** A instrução resolve; o log mede a taxa residual sem nenhum bloqueio (mesmo padrão do `[PROMPT ECHO]` em `orchestrator.py:1348`).
- **C) Guarda hard (auto-anexar CTA / bloquear handoff sem resposta).** Rejeitada: texto enlatado quebra o tom (regra 22/bolhas), detecção de "pergunta respondida" é infactível deterministicamente e a diretriz do projeto veta engessar o funil.

Diretriz de redação (risco de esforço cognitivo do Flash): cada instrução nova tem 1-3 linhas, imperativa, com exemplo mínimo — nada de checklist longo novo.

## Mudança 1 (Cat. 2) — "Responda, DEPOIS se despeça" no handoff

### 1a. Descrição da tool `encaminhar_humano` (`backend/app/agent/tools.py:238-242`)
No trecho que manda escrever a `mensagem_despedida`, acrescentar (1-2 linhas, incisivo):
"SE a ultima mensagem do lead contem uma pergunta que voce sabe responder (preco, lote minimo, prazo, formato), a `mensagem_despedida` COMECA respondendo essa pergunta, e so depois faz o transbordo — NUNCA encaminhe deixando a pergunta do lead sem resposta."

### 1b. Descrição do parâmetro `mensagem_despedida` (`tools.py:249-255`)
Acrescentar 1 linha no mesmo espírito: "Se o lead acabou de perguntar preco/lote/prazo, a resposta vem PRIMEIRO, na propria mensagem (ex.: 'o 250g fica por volta de R$25,70 com lote minimo de 100 unidades — e pra detalhar tudo...')."

### 1c. Prompts inbound (`valeria_inbound/private_label.py` e `valeria_inbound/atacado.py`)
No bloco de critério de handoff adicionado em 10/07 (regra "pergunta de preço = sinal ativo de avanço"), acrescentar UMA frase: a pergunta que qualificou o handoff é respondida NA mensagem de despedida — o lead nunca recebe o cartão no lugar da resposta.

### 1d. Telemetria log-only `[HANDOFF SEM RESPOSTA]`
No executor de `encaminhar_humano` (ou no ponto do orchestrator onde a tool-call é processada — o implementador escolhe o local com acesso à última mensagem do lead e à `mensagem_despedida`): se a última mensagem do lead termina com "?" (ou contém "?" em qualquer linha) E a `mensagem_despedida` não contém dígito nem "R$", logar `logger.warning("[HANDOFF SEM RESPOSTA] ...")` com conversation_id/lead_id. Heurística deliberadamente simples e fail-open; NUNCA bloqueia o handoff. (Falso-negativo aceitável: pergunta não-numérica respondida em texto; falso-positivo aceitável: pergunta cuja resposta não tem número — o log é sinal p/ QA, não métrica exata.)

## Mudança 2 (Cat. 3) — CTA obrigatório após preço

### 2a. Regra no bloco de preço de `base.py` (seção "TURNO 3: passar os precos" ~L825 / regras de valores ~L800)
Acrescentar regra curta e imperativa:
"REGRA DO PRECO NUNCA SOLTO: toda mensagem que entrega preco/valor TERMINA com uma pergunta de fechamento que pede uma decisao concreta do lead (ex.: 'faz sentido pra voce comecar com 100 unidades?' / 'quer que eu ja simule o pedido?'). Preco sem pergunta = lead no vacuo. Isso NAO se aplica quando voce esta encerrando via encaminhar_humano."

### 2b. Item no checklist de autoverificação (`base.py` ~L1074, numeração sequencial existente)
Um item novo, no formato dos existentes: "Entreguei preco/valor neste turno? Minha ULTIMA bolha termina com pergunta de fechamento? (regra do preco nunca solto)".

### 2c. Telemetria log-only `[PRECO SEM CTA]`
Função pura em `backend/app/agent/adherence.py` (padrão dos guards existentes): `price_without_cta(text: str) -> bool` — True quando o texto contém preço (`R\$\s?\d`) E a última linha não-vazia não termina com "?". Chamada no orchestrator no mesmo ponto/padrão do `[PROMPT ECHO]` (`orchestrator.py:1348`), APENAS quando o turno NÃO terminou em tool de encerramento (handoff) — `logger.warning`. Sem bloqueio, sem mutação do texto.

## Fora do escopo
- Qualquer bloqueio/mutação de resposta (diretriz anti-engessamento).
- Prompts outbound (o relatório é inbound; a persona outbound tem roteiro próprio de preço).
- Métrica no daily QA report (os warnings ficam para observação; promover a métrica só se a taxa residual justificar).

## Critérios de aceite
1. Descrições de `encaminhar_humano`/`mensagem_despedida` e prompts inbound com as frases novas; nenhuma instrução nova com mais de 3 linhas.
2. `price_without_cta` com testes unitários (tabela: preço+sem ?; preço+com ?; sem preço; multi-bolha com ? só no fim; R$ em URL/milhar não confunde).
3. Warnings `[PRECO SEM CTA]`/`[HANDOFF SEM RESPOSTA]` testados (caplog) e comprovadamente não alteram a resposta nem o handoff.
4. Testes de aderência/rehearsal/fallback existentes verdes (atenção: fallbacks tipo "opa, me embolei" não contêm R$ → não disparam; despedidas de handoff são isentas do check de CTA).
5. Suíte completa `pytest` verde.
