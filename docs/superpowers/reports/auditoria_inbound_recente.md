# Auditoria Rápida — Conversas INBOUND Recentes (janela de implementação)

**Data:** 10-11/07/2026 (janela UTC: 2026-07-10T22:37 → 2026-07-11T01:37, ~3h)
**Objetivo:** varredura de segurança pré-push — verificar se as anomalias da auditoria de 10/07 se repetiram em leads novos ou se surgiu comportamento novo, durante a janela em que as correções eram implementadas (produção ainda rodando o código ANTIGO).
**Método:** script temporário read-only (`backend/scripts/temp_audit_recent.py`, removido após o uso), mesma classificação de modalidade da auditoria anterior; leitura integral dos transcritos; validação de preço citado contra a tabela `products`.

## Volumetria

109 mensagens / 5 conversas com atividade (0 outbound) / **3 conversas novas** (Elias Félix, Ostemberg, Sandro) + 2 já auditadas hoje (João Marcos, Nilson).

## Resultado: LIMPA — nenhuma falha grave nova

| Verificação | Resultado na janela |
|---|---|
| Mídia vazia do vendedor (achado grave P1) | **0 ocorrências novas** |
| Loops / duplicatas consecutivas da IA | 0 |
| Vazamento técnico ao cliente | 0 |
| Alucinação de preço | 0 — R$97,70 (Clássico/Suave grãos 1kg, atacado) citado ao João Marcos confere **exatamente** com `products`; R$25,70/100un (private label 250g) ao Ostemberg idem |
| Pedido de humano ignorado | 0 |
| Ghosting com IA ligada | 0 (respostas em 26-50s em todas as conversas ativas) |
| Lead preso em `pending` | 0 — nas 3 conversas novas o gatilho de prefill foi classificado pelo LLM em 9s-28min (Elias demorou porque a conversa evoluiu antes); reforça o valor do gatilho determinístico implementado |
| Handoff prematuro / flapping (achados P2/P3) | **Sem caso novo.** As flags levantadas apontam para a MESMA conversa do Nilson já auditada (23:04-23:11 UTC, anterior às correções — reincidência esperada: produção roda o código antigo) |

## Destaques qualitativos

- **João Marcos (continuação do caso "preso em pending"):** o lead voltou, o LLM desta vez moveu o stage para `atacado`, a conversa foi longa e de alta qualidade (volumes, exportação, agendamento de retorno para 13/07 via `agendar_retorno`) e o handoff foi **legítimo** — lead qualificado com finalidade+volume e pediu o supervisor. O melhor lead do dia.
- **Observação menor (não bloqueia):** no mesmo atendimento, o lead pediu explicitamente os preços de 250g/500g/1kg e a IA respondeu com um reconhecimento ("entendi perfeitamente a sua necessidade") sem entregar os valores — mitigado pelo handoff + retorno agendado, mas é um miss de responsividade a registrar para o QA.
- As 3 conversas novas (private label) seguem persona, descoberta gradual e preços do catálogo, sem promessas irreais.

## Decisão

Nenhum critério de aborto atendido. **Push para produção autorizado e executado** (as correções implementadas cobrem exatamente as reincidências observadas na conversa pré-fix do Nilson).
