# Spec — Correções de Roteamento Outbound (15/07/2026)

**Origem:** auditoria outbound 15/07 (`docs/superpowers/reports/auditoria_outbound_2026-07-15.md`).
**Escopo:** 3 falhas de UX/conversão. Não altera a fundação (opt-out, preços, anti-alucinação — todos verdes).
**Restrição de paridade:** o código roda igual em dev e prod; nada de `localhost`/IP fixo. Idioma dos prompts segue o padrão Gemini (XML container + Markdown imperativo, termos definidos no bloco — `gemini-prompting-strategies.md`).

---

## Problema 1 — Rigidez do script (caso Francine)

**Sintoma:** cliente existente pediu *"pode me mandar tabela?"*; a Valéria **ignorou o pedido** e rodou o funil de lead novo ("café entra no seu negócio ou consumo?", "qual nome da sua empresa?"). Cliente confusa: *"Não estava te entendendo"*.

**Causa:** o `POSTURA_HUNTER` (playbook outbound) tem LEI 2 (fechar todo turno com pergunta investigativa) e LEI 3 (cliente conhecido = recompra, não re-qualificar), mas **nenhuma regra manda atender um pedido direto e acionável antes de conduzir**. O modelo prioriza a própria agenda de qualificação sobre o pedido explícito do lead.

**Solução (Trilha A — prompt):** nova **LEI 5 — PEDIDO DIRETO SE ATENDE PRIMEIRO** no `POSTURA_HUNTER`:
- Se o lead faz um pedido concreto e acionável (`manda a tabela`, `me passa o preço`, `manda o catálogo/link`, `quanto custa X`), **atender no mesmo turno ANTES** de qualquer pergunta de qualificação.
- PROIBIDO responder a pedido direto com contra-pergunta de qualificação que ignora o pedido.
- Vale em dobro para cliente já conhecido (compõe com a LEI 3).
- Depois de atender, mantém a LEI 2 (fecha com pergunta investigativa) — **sem conflito com os testes de aderência** (o fecho ativo continua obrigatório; muda só a ordem: entrega primeiro, conduz depois).

## Problema 2 — Ponte pós-handoff em silêncio absoluto (caso Itamar) + presunção falsa (caso Hueiner)

**Sintoma A (Itamar):** após o handoff, o lead perguntou *"Gostaria de visitar a produção, como faço?"* → a ponte classificou como pergunta de negócio e ficou em **silêncio total** (só um marcador no banco), sem avisar nada ao lead nem alertar o vendedor. Sinal quente de fundo de funil vira dead-air, 100% dependente do SLA humano.

**Sintoma B (Hueiner):** a IA (ainda viva, pré-handoff) abriu com *"você já compra da gente, né?"* — presunção de relacionamento **sem lastro** (o lead respondeu "ainda não"). Isso é um problema de **prompt** (LEI 1 já proíbe, mas o modelo reincidiu), não da ponte de código.

**Causa (A):** `_maybe_send_handoff_bridge` em `backend/app/buffer/processor.py`. O ramo `_looks_like_business_question` retorna **silêncio total** por design (auditoria 11/07, casos Mateus/Leonardo — "não carimbar por cima da pergunta"). O receio original era *enterrar* a pergunta com um texto de roteamento. Mas o efeito colateral é dead-air em perguntas legítimas.

**Solução (Trilha B — backend): "escudo seguro".** Reescrever o ramo:
- Pergunta de negócio pós-handoff → em vez de silêncio, enviar um **aviso curto, seguro e NÃO-COMERCIAL de recebimento**: *"recebi sua mensagem! seu atendimento já tá com o João e ele te responde por aqui, tá?"*. Isso **não responde** a pergunta (o humano ainda lê e responde — não enterra nada) mas fecha o vácuo. Marcador system atualizado. **Cooldown dedicado** (`bridge_ack:{conv}`, 1h) para não martelar a cada mensagem.
- O texto é ESTÁTICO (sem LLM) — a ponte segue sendo roteamento puro, sem risco de alucinar histórico ou responder errado.

**Solução (Sintoma B — Trilha A prompt):** reforçar a LEI 1 do `POSTURA_HUNTER` com o exemplo banido literal (`"você já compra da gente, né?"`, `"você já é nosso cliente"`) e a alternativa NEUTRA (`"você já conhece / já comprou da gente?"` — pergunta, não afirmação) quando não há lastro no CRM.

## Problema 3 — Sem rota de escalonamento para reclamação do atendimento humano (casos Aislan/Sirli)

**Sintoma:** Aislan (cliente com pedido fechado e **não entregue**) reclamou *"faz quase 1 ano tentando negociar e não me enviaram nada… visualizam e não respondem"*. A única jogada foi handoff normal para o João — que o próprio lead identificou como o vendedor que o ignorou: *"esse aí é um deles que me deixou várias vezes sem responder. vou agradecer por tudo!"*. Lead perdido, sem ninguém acima do João sabendo.

**Causa:** não existe distinção entre *lead qualificado* (handoff normal) e *lead reclamando do atendimento humano* (precisa de visibilidade da gerência). O `encaminhar_humano` devolve o lead ao mesmo gargalo, em silêncio para a gestão.

**Solução:** duas frentes, cobrindo os dois momentos (IA viva e pós-handoff):

- **Trilha A (IA viva, antes do handoff):** novo tool **`escalar_reclamacao`** + regra em `base.py`. Quando o lead reclama do **atendimento humano / pedido não entregue / vendedor não responde** (distinto da "reclamação de robô", que já existe), a IA chama `escalar_reclamacao(motivo=…)`, que:
  1. dispara `create_system_alert(type="lead_complaint_escalation", severity="critical", …)` → **WhatsApp para `ADMIN_ALERT_PHONE` + Sentry + linha em `system_alerts`** (gerência vê na hora);
  2. carimba observação/tag de escalonamento no lead;
  3. cascateia para `encaminhar_humano` (mantém card/rescue/deal e desliga a IA), com `mensagem_despedida` que **reconhece a frustração** e avisa que o time foi acionado com prioridade — em vez do pitch padrão.
- **Trilha B (pós-handoff, IA já desligada → ponte):** novo detector puro `_looks_like_complaint(text)`. Na ponte, ANTES do ramo de pergunta de negócio: reclamação pós-handoff → dispara `create_system_alert(critical)` (cooldown `bridge_escalation:{conv}`, 12h, para não spammar a gerência) + envia aviso seguro de escalonamento ao lead (*"puxa, sinto muito por isso — já sinalizei aqui internamente pra resolverem com prioridade"*) + marcador.

**Limitação conhecida (documentada):** o sistema tem um único supervisor (`SUPERVISOR_NAME`/`SUPERVISOR_PHONE` = João Brás). Não há um segundo rep para re-rotear. O ganho real é **tornar a reclamação VISÍVEL para a gerência** (alerta crítico externo) em vez de morrer no funil — a pessoa acima do João decide a intervenção. Re-roteamento a um segundo vendedor fica fora deste escopo (exige cadastro de fallback de vendedor).

---

## Contrato de mudança / não-regressão

- **Fundação intacta:** opt-out, preços, anti-alucinação de fotos — não tocados.
- **Aderência outbound:** LEI 2 (fecho ativo) e a blacklist permanecem; LEI 5 só reordena (atende → depois conduz). Todos os substrings verificados por `test_outbound_postura_hunter_2026_07_13.py` são preservados (só adição).
- **Ponte:** o contrato do ramo "pergunta de negócio → silêncio total" MUDA para "aviso seguro de recebimento". `test_bridge_business_question_2026_07_11.py` é reescrito para o novo contrato. Encerramento social (❤️), reação (silêncio) e vácuo puro (carimbo) permanecem.
- **Fail-soft absoluto:** toda a lógica nova da ponte e do alerta é best-effort — nenhuma exceção escala para o processor (padrão já existente).
- **Novo tool** entra pelo REGISTRY (fonte única) com `effects=ToolEffects(disables_ai=True, may_cascade_to=("encaminhar_humano",))`.
