# Valéria Outbound — Handoff Proativo + Instrumentação de Qualificação (Design/Spec)

**Data:** 2026-07-04
**Origem:** Auditoria do funil "Valeria - Importação Leads Frios" (pipeline `a9487d77-ae93-42fe-89b8-9747d5e9cdf4`). Ver memória `project_valeria_outbound_frios_audit`.
**Objetivo:** Fechar o vazamento de leads qualificados que esfriam antes de chegar ao closer humano (João) e tornar a cascata Disparos→Respostas→Qualificados→Aceites mensurável, sem reescrever os prompts existentes.

## Contexto empírico (o que já existe e NÃO deve ser refeito)

Os prompts do outbound são maduros e carregam de código via `PROMPT_REGISTRY` (`orchestrator.py:586`); não há prompt vazio. O `encaminhar_humano` (`tools.py`) já gera um resumo estruturado de qualificação (`app/agent/summary.py`) e já o grava em `lead_notes` (autor `qualificação-ia`) e em `metadata.handoff_summary`, e já roteia o card ao pipeline do vendedor via `move_deal_to_vendor_pipeline` (`leads/service.py:704`). A triagem e o `mudar_stage` funcionam (78/119 respondentes roteados). O gargalo é o handoff passivo, a atribuição de responsável ausente, e a métrica contaminada.

## Global Constraints

- Não reescrever o registro de prompts; apenas edições cirúrgicas nas seções de handoff e guardas determinísticas em volta.
- João = user `1c3c78ed-ef47-4dca-9a63-2052f28e8fd6` (`joao@cafecanastra.com`), dono dos pipelines "João -".
- Fonte de verdade do responsável: `pipelines.owner_user_id` do destino em `SEGMENT_HANDOFF_PIPELINE`; fallback para o ID do João em atacado/private_label.
- Segmentos consumo/secretaria não têm vendedor: `assigned_to` permanece nulo (self-service).
- Todo caminho de handoff é fail-soft: erro logado nunca derruba o desligamento da IA.
- Deploy: push para master dispara produção — validar por pytest + rehearsal antes de qualquer push.

## Item 1 — Atribuição de responsável no handoff

Novo helper `vendor_user_id_for_segment(segment) -> str | None` em `leads/service.py`, lendo `pipelines.owner_user_id` pelo nome mapeado em `SEGMENT_HANDOFF_PIPELINE`, com fallback para o ID do João em atacado/private_label e `None` para consumo/secretaria. No `encaminhar_humano` (`tools.py`), resolver o segmento (via `get_lead(...).stage`) ANTES do update de desligamento e incluir `assigned_to` no mesmo `update_lead(status="converted", human_control=True, ai_enabled=False, assigned_to=...)`, tornando a atribuição atômica com o handoff. `update_lead` já é passthrough genérico (`**fields`) — nenhuma mudança nele.

## Item 2 — Métrica pura (marcador estruturado)

O resumo humano em `lead_notes` já existe; não recriar. Adicionar, no fluxo do handoff (independente do sucesso do LLM de resumo), um carimbo estruturado `lead.metadata.handoff = {vendedor_id, vendedor, segmento, motivo, at}`. A métrica "Qualificados/Aceites" passa a contar leads com esse carimbo, separando handoffs reais das desqualificações suaves (`registrar_sem_interesse_atual` ramo "cliente ativo") que hoje poluem o estágio "Qualificado" do kanban.

## Item 3 — Gatilho de handoff proativo

Nova ferramenta `qualificar_lead(finalidade, volume, urgencia)` registrada em `TOOLS_SCHEMA` e disponibilizada em `get_tools_for_stage` para atacado, private_label e exportacao. Ela persiste as âncoras em `lead.metadata.qualificacao` e, quando finalidade E volume estiverem presentes (urgência opcional), dispara deterministicamente o handoff (reusando `execute_tool("encaminhar_humano", ...)`), com motivo "handoff proativo — âncoras capturadas". A decisão de transferir passa do julgamento do modelo para o código — o modelo apenas relata âncoras. Edição cirúrgica na seção "ETAPA DE HANDOFF" de `atacado.py`/`private_label.py` instruindo a chamar `qualificar_lead` conforme as âncoras aparecem, sem aguardar sinal explícito de compra.

Rede de segurança (padrão dominante do vazamento, "caso Joabe"): flag `metadata.catalog_shown=true` gravada quando `enviar_fotos` dispara em atacado/private_label; regra no motor de follow-up que, para lead qualificado que viu catálogo e ficou um ciclo de follow-up sem responder, dispara handoff proativo com motivo "qualificado inativo pós-catálogo". Cuidado explícito para rodar antes do follow-up padrão e não colidir com o `cancel_followups_by_phone` já acionado no handoff.

## Item 4 — Aderência ao prompt (guardas determinísticas, sem reescrever)

Filtro de saída que detecta frases proibidas ("pra te direcionar", "pra eu te direcionar da melhor forma") no texto da assistente antes do envio e as remove/reescreve, no mesmo espírito do sanitizer de `tool_code`. Detector determinístico de auto-produtor na mensagem do lead em atacado/private_label ("eu que produzo", "eu mesmo torro", "sou produtor", "produzo meu café", "tenho minha marca/fazenda de café") que força `registrar_sem_interesse_atual(motivo="auto-produtor/concorrente — fora do ICP")` em vez de deixar o modelo continuar. Conservador e ancorado em frases explícitas; evitar elípticas ambíguas ("sou eu mesma") para não desqualificar lead legítimo. Seguir o padrão de `_normalize_text` e das tuplas de sinais já existentes em `tools.py`.

## Testes (TDD)

Cobertura por unidade, espelhando `test_encaminhar_humano_pipeline.py`: (a) handoff de atacado grava `assigned_to`=João; (b) carimbo `metadata.handoff` presente; (c) `vendor_user_id_for_segment` resolve owner e cai no fallback; (d) `qualificar_lead` persiste âncoras e NÃO transfere só com finalidade; (e) `qualificar_lead` com finalidade+volume dispara `encaminhar_humano`; (f) filtro de frase proibida; (g) gatilho de auto-produtor chama `registrar_sem_interesse_atual`; (h) backstop pós-catálogo dispara handoff após inatividade.

## Sequenciamento

Itens 1 e 2 (baratos, baixo risco) primeiro; item 4 (guardas pequenas) em seguida; item 3 (maior mudança de comportamento) validado no rehearsal de outbound antes de qualquer push. Núcleo acoplado (`tools.py`/`leads/service.py`) implementado de forma coesa; peças independentes (prompts, guardas, backstop no scheduler) delegáveis em paralelo.
