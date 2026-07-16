# Spec — Valéria: Resiliência de Mídia/Contexto, Roteamento de Handoff e Consistência de Catálogo

- **Data:** 2026-07-01
- **Autor:** Engenharia (via Claude Code)
- **Status:** Aprovado para planejamento (writing-plans)
- **Origem:** Relatório qualitativo de produção 30/06–01/07 (persona Valéria, fluxos Inbound e Outbound)
- **Escopo:** Documento único, faseado (P0/P1/P2). Três frentes de solução ancoradas em investigação de código.

---

## 1. Contexto e Motivação

A IA "Valéria" opera em produção como agente comercial de WhatsApp da Café Canastra sobre um backend FastAPI + Redis + Supabase, com dois eixos de persona (`valeria_inbound` e `valeria_outbound`), cinco stages comerciais (`secretaria`, `atacado`, `private_label`, `exportacao`, `consumo`) e o modelo `gemini-2.5-flash` via endpoint OpenAI-compat. O relatório de produção elogiou a persona Inbound e a consultividade, mas apontou falhas críticas que corroem confiança e queimam leads quentes: resets de contexto ("me embolei"), duplicação de mensagens (texto e fotos em dobro), divergência de regra de negócio (lote mínimo 50 vs 100), ausência de material estruturado de atacado, e falhas de continuidade no handoff (roteamento sem subespecialidade, vácuo no lead, saltos duplos).

Esta spec traduz esses sintomas em causas-raiz verificadas no código e desenha três planos de solução coordenados, com faseamento por risco e estratégia de testes.

---

## 2. Diagnóstico Arquitetural

O diagnóstico abaixo é resultado de leitura direta do código, não de suposição. Cada causa aponta o arquivo e o mecanismo real.

**Resets de contexto ("me embolei").** A frase `_SAFETY_FALLBACK_GENERIC` ("opa, me embolei aqui por um instante…") vive em `backend/app/agent/orchestrator.py:62`. Ela não decorre de erro de parsing nem de um `try/except` genérico: é o caminho de *resposta vazia* do LLM, quando o `gemini-2.5-flash` devolve `completion_tokens=0` — o modelo queima o orçamento de saída "pensando". Já existe um retry silencioso com thinking desligado, mas ele não cobre o amplificador principal: **a montagem do histórico está invertida**. Em `backend/app/conversations/service.py:288`, `get_history` ordena por `created_at` de forma **ascendente** e aplica `limit(60)`, retornando as 60 mensagens **mais antigas** da conversa em vez das mais recentes. Em qualquer conversa com mais de 60 turnos, o assunto atual desaparece do prompt e o modelo, sem âncora recente, tende a devolver vazio — exatamente diante de mensagens longas, narrativas emocionais ou trocas prolongadas. Dois fatores agravam: imagens inbound não têm visão computacional (viram só o marcador cego `[imagem]` em `backend/app/buffer/processor.py`, com o `describe_image`/GPT-4o de `backend/app/whatsapp/media.py` sendo código morto, nunca importado), e narrativas longas entram inteiras no prompt sem qualquer condensação, aumentando a chance de estouro do thinking.

**Duplicação de mensagens.** A régua que sustenta a re-coalescência, `_has_newer_inbound` (`backend/app/buffer/processor.py`), compara timestamps com `.gt("created_at")` de forma **estrita**. Como `created_at` é gerado pelo Postgres em `save_message` sem controle de granularidade, duas mensagens do lead podem colidir no mesmo timestamp; nesse caso nenhum dos dois workers concorrentes se enxerga como "mais novo" e **ambos respondem**, produzindo blocos de texto e lotes de foto duplicados. Some-se a isso que `enviar_fotos` (`backend/app/agent/tools.py`) apenas *loga* o dedup e **re-enfileira o lote inteiro**, ao contrário de `enviar_foto_produto` que aborta cedo; e que o retry de envio na Meta (`backend/app/whatsapp/meta.py`) não carrega guard de idempotência, podendo reemitir a mesma bolha no fio.

**Inconsistência de regras de negócio e catálogo.** A fonte de verdade está fragmentada em quatro lugares: a tabela `products` no Supabase, o frete hardcoded em `backend/app/agent/pricing.py`, preços e o número "100 unidades" hardcoded em `backend/app/agent/prompts/base.py`, e o mapa de fotos em `tools.py`. O campo `min_lot` é **texto livre nunca validado** em código — a régua de pedido mínimo em `pricing.py` só valida R$300 de frete, jamais a quantidade. A regra real de negócio (100 unidades no padrão; 50 unidades apenas no Microlote quando o cliente usa a própria embalagem) não existe de forma executável. Há ainda um **conflito ativo de política**: `valeria_inbound/atacado.py` obriga "amaciar" o preço ("por volta de", "na faixa de"), enquanto o bloco `<catalogo_de_produtos>` injetado por `orchestrator.py` proíbe amaciar. Não existe PDF nem tabela estruturada de atacado no repositório — apenas cinco imagens.

**Falhas de continuidade no handoff.** Todo transbordo aterrissa no João (telefone hardcoded em `backend/app/agent/tools.py`). O vendedor Arthur **não possui canal/telefone** em lugar algum do código — existe somente como *pipeline no CRM* (`SEGMENT_HANDOFF_PIPELINE` em `backend/app/leads/service.py`). Consequentemente, a exportação promete Arthur mas quem contata é o João: uma **promessa falsa estrutural**, com `base.py` e `exportacao.py` se contradizendo sobre nomear Arthur. A confirmação proativa do vendedor (`schedule_handoff_rescue`, 15 min de default) é grampeada à janela comercial 09h–16h, seg–sex, podendo atrasar até o próximo dia útil; e há caminhos de SLA que falham em silêncio (erro Meta 4xx cancela o job sem retry; canal ausente marca o lead como convertido mas não contata ninguém). Por fim, o handoff pode disparar sem uma ponte de valor e sem captura estruturada de dados do pedido (nome, CNPJ, intenção) no auge da energia de compra.

---

## 3. Plano 1 — Resiliência de Mídia, Textos Longos e Contexto

O objetivo é eliminar o reset de contexto na raiz e preservar o rapport diante de mídia e narrativas longas.

### 3.1 Correção de ordenação do histórico (P0)

A correção de maior impacto e menor risco é reescrever a recuperação de histórico em `get_history` (`backend/app/conversations/service.py`) para buscar as **60 mensagens mais recentes**: ordenar por `created_at` de forma **decrescente**, aplicar `limit(60)` e então **reverter a lista para ordem cronológica ascendente** antes de devolvê-la ao montador de prompt em `orchestrator.py`. O contrato de saída da função permanece idêntico (lista em ordem cronológica), de modo que nenhum consumidor a jusante precisa mudar; apenas a *janela* de mensagens deixa de ser a mais antiga e passa a ser a mais recente. O dossiê de longo prazo (`rolling_summary`) continua cobrindo o histórico anterior à janela.

### 3.2 Endurecimento do caminho de resposta vazia (P1)

Mantém-se o retry silencioso com thinking desligado já existente, e adicionam-se duas defesas. Primeiro, **sumarização de narrativas longas**: quando a mensagem atual do lead ultrapassar um limiar de comprimento, o backend gera uma versão condensada dela (preservando fatos e intenção) para compor o turno enviado ao modelo, reduzindo o estouro de thinking que hoje produz `completion_tokens=0`. Segundo, **retomada contextual em vez de reset genérico**: quando ainda assim a resposta vier vazia e houver dossiê ou stage ativo, o fallback deixa de emitir o "me embolei" genérico e passa a emitir uma retomada que *cita o último assunto tratado* (por exemplo, referenciando o segmento ou a última pergunta em aberto), preservando a sensação de continuidade. O comportamento honesto já estabelecido — jamais afirmar que "a mensagem chegou cortada" — é mantido.

### 3.3 Visão nativa leve para imagens inbound (P2)

Hoje imagens inbound são cegas para o modelo, o que causa divagação e resposta vazia. Como o pipeline já usa `generateContent` do Gemini para transcrição de áudio, esta capacidade **liga a visão nativa leve para imagens de entrada**: ao resolver a mídia no processor, a imagem é submetida ao modelo de visão e sua **descrição curta é injetada no lugar do marcador cego**, na forma `[imagem: <descrição>]`. Isso substitui e aposenta o código morto de `backend/app/whatsapp/media.py` (`describe_image`/GPT-4o nunca importado), consolidando a estratégia de mídia num único provedor. O prompt permanece proibido de *inventar* conteúdo de mídia; a diferença é que agora existe um sinal real a descrever, recuperando leads que enviam a arte/logo e hoje caem no reset.

---

## 4. Plano 2 — Roteamento de Handoff por Subespecialidade e SLA

O objetivo é acabar com a promessa falsa, permitir roteamento por subespecialidade sem reescrever o fluxo, e garantir que o lead quente nunca fique no vácuo.

### 4.1 Tabela `vendors` como fonte única de roteamento (P2)

Introduz-se uma tabela `vendors` como autoridade de roteamento, contendo ao menos `name`, `phone_number_id`, `whatsapp`, `segments[]` e `enabled`. João é semeado com `enabled=true` cobrindo os segmentos padrão (saca/atacado, private_label, consumo); Arthur é semeado com `enabled=false` e `segments=['exportacao', 'grao_verde']`. A execução de `encaminhar_humano` (`backend/app/agent/tools.py`) passa a **resolver o destino de contato a partir da tabela**, filtrando por segmento/stage **e por `enabled=true`** — o que hoje sempre recai no João, por ser o único habilitado. No dia em que o canal do Arthur existir, ligar o flag `enabled=true` ativa o roteamento por subespecialidade (cartão de contato, rescue e template proativo passam a sair do destino correto) sem qualquer outra mudança de código. Os telefones hardcoded em `tools.py` são removidos em favor da tabela.

### 4.2 Eliminação da promessa falsa (P1/P2)

A regra de nomeação de vendedor passa a ser derivada da tabela `vendors`: **a IA só nomeia ao lead quem está `enabled` para aquele segmento e realmente fará o contato**. As instruções contraditórias de `backend/app/agent/prompts/base.py` e `backend/app/agent/prompts/valeria_inbound/exportacao.py` são alinhadas a essa regra única. Enquanto Arthur estiver `enabled=false`, a Valéria confirma o repasse da exportação **sem cravar um nome de vendedor**, evitando prometer um contato que não ocorrerá; o card, contudo, continua sendo roteado para o pipeline do Arthur no CRM (esse roteamento de CRM já funciona e permanece). O alinhamento textual dos prompts é P1 (correção imediata da promessa falsa); a derivação plena a partir da tabela é P2 (acompanha a tabela `vendors`).

### 4.3 Ponte de valor e captura estruturada antes do transbordo (P1)

O transbordo prematuro é substituído por um *gate* leve: só encaminhar ao humano depois de capturar nome, segmento e um sinal de intenção de compra, construindo uma ponte de valor no auge da energia. Adiciona-se **captura estruturada de CNPJ e intenção** (campo/tool dedicado que persiste o CNPJ, hoje inexistente — o CNPJ só aparece como tópico conversacional em `exportacao.py`). O resumo de qualificação (`generate_qualification_summary`) é reaproveitado, agora enriquecido com o CNPJ estruturado, entregando ao vendedor um briefing completo.

### 4.4 SLA da confirmação proativa (P1)

A primeira confirmação do vendedor é **desacoplada da janela comercial**: em vez de depender exclusivamente do rescue grampeado a 09h–16h, envia-se imediatamente, dentro da sessão de handoff, uma confirmação de que o contato já está com o vendedor — de modo que o lead quente nunca fique no vácuo. O **rescue de 15 minutos** é mantido como rede de segurança. Além disso, o processamento do rescue ganha **retry/alerta em erro Meta 4xx** (hoje cancela silenciosamente sem retry) e uma **proteção de canal órfão**: se não houver canal ativo para contatar o lead, o sistema não marca o lead como resolvido de forma cega — emite alerta para intervenção humana, evitando o lead órfão que hoje fica sem qualquer contato.

---

## 5. Plano 3 — Consistência de Dados e Catálogo

O objetivo é estabelecer o banco como autoridade única de preços e lote mínimo, resolver o conflito de política de preço, e estancar a duplicação de material.

### 5.1 Banco de dados como autoridade de lote mínimo (P1)

A tabela `products` é estendida para modelar o lote mínimo de forma **estruturada e validável**, substituindo o `min_lot` de texto livre: um campo numérico `min_lot_qty` (quantidade padrão, tipicamente 100) e um campo `min_lot_packaging_rule` que codifica a exceção do Microlote — **50 unidades quando o cliente usa a própria embalagem; 100 unidades com embalagem Café Canastra**. Essa quantidade passa a ser **validada em código** no caminho de orçamento (`pricing.py`/`calcular_orcamento`), que hoje só valida o pedido mínimo em R$300 de frete e ignora a quantidade. Com isso, os números hardcoded de `backend/app/agent/prompts/base.py` ("100 unidades", preços de exemplo como "R$23,90") são **removidos**, e a IA passa a citar lote mínimo e preço exclusivamente a partir da autoridade do banco.

### 5.2 Política de preço firme (P0)

Resolve-se o conflito ativo entre `valeria_inbound/atacado.py` (que obriga amaciar o preço com "por volta de", "na faixa de") e o bloco `<catalogo_de_produtos>` de `orchestrator.py` (que proíbe amaciar). Adota-se a **política de preço firme**: o preço de tabela não é estimativa e não deve ser suavizado. As duas fontes de instrução são tornadas coerentes com essa política, eliminando a divergência de comportamento observada.

### 5.3 Álbum curado, correção de duplicação e idempotência (P0)

O envio de material passa a ser um **álbum curado** com legendas em formato de **mini-tabela** (preço e lote por foto), oferecendo ao cliente a estrutura de "tabela de atacado" que ele pede sem depender de PDF (fora de escopo agora). Três correções fecham a duplicação: `enviar_fotos` (`backend/app/agent/tools.py`) passa a **abortar o reenvio** quando o lote já foi enviado, adotando o mesmo padrão de retorno antecipado que `enviar_foto_produto` já usa (hoje apenas loga e re-enfileira o lote inteiro); o envio na Meta (`backend/app/whatsapp/meta.py`) ganha uma **chave de idempotência** para que o retry de rede não reemita a mesma bolha; e, na régua de re-coalescência, o **desempate de timestamp** de `_has_newer_inbound` (`backend/app/buffer/processor.py`) deixa de depender de `.gt("created_at")` estrito, passando a usar `id`/sequência monotônica (ou `>=` com desempate por `id`), de forma que uma colisão de timestamp não faça mais os dois workers concorrentes responderem.

---

## 6. Faseamento

O trabalho é organizado em três fases por risco e impacto, de modo que o sangramento em produção pare primeiro.

**P0 — Hotfixes de baixo risco.** Correção de ordenação do `get_history` (§3.1); aborto de reenvio no `enviar_fotos` (§5.3); desempate de timestamp na re-coalescência (§5.3); política de preço firme e alinhamento do valor de lote mínimo no prompt (§5.2). São mudanças cirúrgicas que atacam diretamente os sintomas mais visíveis (reset de contexto, fotos/texto em dobro, divergência de preço).

**P1 — Robustez estrutural.** Endurecimento do caminho de resposta vazia com sumarização de narrativa e retomada contextual (§3.2); banco como autoridade de lote mínimo com validação (§5.1); alinhamento textual anti-promessa-falsa (§4.2); ponte de valor e captura estruturada de CNPJ/intenção (§4.3); SLA de confirmação proativa imediata, retry em 4xx e proteção de canal órfão (§4.4); chave de idempotência no envio Meta (§5.3).

**P2 — Novas capacidades.** Tabela `vendors` e roteamento multi-vendedor por subespecialidade, com Arthur atrás do flag `enabled=false` (§4.1); derivação plena da regra de nomeação a partir da tabela (§4.2); visão nativa leve para imagens inbound, aposentando o código morto (§3.3).

---

## 7. Estratégia de Testes

Cada correção recebe teste unitário no padrão já existente no repositório, que favorece helpers puros testáveis isoladamente (`_empty_fallback_text`, `_has_newer_inbound`, `decide_persona`). Quatro testes são exigidos explicitamente e servem de âncora de regressão:

O teste de **`get_history`** valida que, numa conversa com mais de 60 mensagens, a função retorna a janela das 60 mais recentes em ordem cronológica ascendente — travando a regressão da ordenação invertida. O teste de **idempotência do `enviar_fotos`** valida que um segundo disparo do mesmo lote (por reexecução do agente ou retry) não re-enfileira as fotos, isto é, o lote não é enviado duas vezes. O teste de **colisão de timestamps na re-coalescência** valida que, quando duas mensagens inbound compartilham o mesmo `created_at`, a régua identifica corretamente a mensagem mais nova (via `id`/sequência) e apenas um turno responde, sem duplicação. O teste de **destino de handoff por segmento** valida que a resolução de vendedor a partir da tabela `vendors` filtra por `enabled=true`: um lead de exportação, com Arthur `enabled=false`, é roteado para o contato do João e a IA não nomeia Arthur ao lead.

Os testes acompanham suas respectivas fases: os de `get_history`, `enviar_fotos` e colisão de timestamp entram em P0/P1 junto de suas correções; o de destino de handoff por segmento entra em P2 com a tabela `vendors`.

---

## 8. Riscos e Notas de Implementação

A mudança de janela do `get_history` altera o conteúdo do prompt em todas as conversas longas; embora corrija um bug claro, convém observar métricas de token e comportamento após o deploy. A introdução da tabela `vendors` deve preservar o comportamento atual enquanto só o João está `enabled`, de forma que P2 seja uma capacidade latente e não uma mudança de comportamento imediata. A remoção de dados hardcoded do `base.py` exige que a tabela `products` esteja corretamente populada pela operação (via CSV), sob risco de a IA ficar sem preço/lote a citar — a operação deve validar o seed antes do corte. Uma nota técnica: a WhatsApp Cloud API **não** expõe idempotency key no envio; a "idempotência no envio Meta" (§5.3) é, portanto, realizada como um **guard de idempotência na camada de aplicação** — um `SETNX` no Redis sobre o hash `(conversation_id, texto/mídia)` numa janela curta, que impede o retry de reemitir a mesma bolha. Por fim, todas as mudanças respeitam as diretrizes do projeto: paridade de código entre ambientes, operação do Dev Router sobre payload bruto, e foco exclusivo no fluxo Meta Graph API.

---

## Apêndice A — Mapa de Arquivos Alterados

O mapa abaixo consolida, por fase, os arquivos criados e modificados. Caminhos relativos à raiz do repositório `feats2`.

### P0 — Hotfixes

| Arquivo | Ação | Responsabilidade da mudança |
|---|---|---|
| `backend/app/conversations/service.py` | Modificar (`get_history`) | Buscar as 60 mensagens mais recentes (order desc + limit) e reverter para ordem cronológica antes de retornar (§3.1). |
| `backend/app/agent/tools.py` | Modificar (`enviar_fotos`) | Abortar reenvio com `return` antecipado quando o marcador `[enviar_fotos]` já existe no histórico, espelhando `enviar_foto_produto` (§5.3). |
| `backend/app/buffer/processor.py` | Modificar (`_has_newer_inbound`) | Desempate de timestamp: comparar por `id`/sequência (ou `created_at` com desempate por `id`) em vez de `.gt("created_at")` estrito (§5.3). |
| `backend/app/agent/prompts/valeria_inbound/atacado.py` | Modificar | Adotar política de preço firme; remover a obrigação de "amaciar" ("por volta de"), alinhando ao bloco de catálogo (§5.2). |
| `backend/app/agent/prompts/base.py` | Modificar | Alinhar o valor de lote mínimo à autoridade do catálogo; preparar remoção dos números hardcoded (§5.2, prep. §5.1). |
| `backend/tests/test_get_history_window.py` | Criar | Teste da janela recente do `get_history`. |
| `backend/tests/test_enviar_fotos_idempotente.py` | Criar | Teste do aborto de reenvio do `enviar_fotos`. |
| `backend/tests/test_recoalesce_timestamp_tie.py` | Criar | Teste da colisão de timestamp na re-coalescência. |

### P1 — Robustez estrutural

| Arquivo | Ação | Responsabilidade da mudança |
|---|---|---|
| `backend/migrations/2026XXXX_products_min_lot_structured.sql` | Criar | Adicionar `min_lot_qty` (int) e `min_lot_packaging_rule` (jsonb) à tabela `products` (§5.1). |
| `backend/app/agent/pricing.py` | Modificar | Validar a quantidade mínima estruturada no cálculo de orçamento (§5.1). |
| `backend/app/agent/catalog.py` | Modificar | Renderizar o lote mínimo estruturado no bloco de catálogo (§5.1). |
| `backend/app/agent/tools.py` | Modificar (`calcular_orcamento`; captura de CNPJ) | Validar lote mínimo; nova tool/campo de captura estruturada de CNPJ/intenção (§5.1, §4.3). |
| `backend/app/agent/prompts/base.py` | Modificar | Remoção definitiva dos preços/lote hardcoded; regra única anti-promessa-falsa (§5.1, §4.2). |
| `backend/app/agent/prompts/valeria_inbound/exportacao.py` | Modificar | Confirmar repasse sem cravar nome enquanto Arthur `enabled=false` (§4.2). |
| `backend/app/agent/orchestrator.py` | Modificar | Sumarização de narrativa longa; retomada contextual no fallback de resposta vazia (§3.2). |
| `backend/app/agent/summary.py` | Modificar | Enriquecer o briefing de qualificação com CNPJ estruturado (§4.3). |
| `backend/app/follow_up/service.py` / `scheduler.py` | Modificar | Confirmação proativa imediata; retry/alerta em erro 4xx; proteção de canal órfão (§4.4). |
| `backend/app/buffer/processor.py` | Modificar | Guard de idempotência de envio (SETNX Redis sobre hash da bolha) (§5.3). **`whatsapp/meta.py` fora do escopo** — a série BSUID reescreveu o `_post`; a idempotência fica só no processor. |
| `backend/tests/test_empty_response_recovery.py` | Criar | Teste da retomada contextual sem reset genérico. |
| `backend/tests/test_min_lot_validation.py` | Criar | Teste da validação de lote mínimo estruturado (50/100). |
| `backend/tests/test_handoff_sla_guards.py` | Criar | Teste dos guards de SLA (4xx/canal órfão/confirmação imediata). |

### P2 — Novas capacidades

| Arquivo | Ação | Responsabilidade da mudança |
|---|---|---|
| `backend/migrations/2026XXXX_vendors_table.sql` | Criar | Tabela `vendors` (`name`, `phone_number_id`, `whatsapp`, `segments[]`, `enabled`) + seed João/Arthur (§4.1). |
| `backend/app/vendors/service.py` | Criar | `resolve_vendor_for_segment(segment)` filtrando por `enabled=true`; fonte única de roteamento (§4.1). |
| `backend/app/agent/tools.py` | Modificar (`encaminhar_humano`) | Resolver destino via `vendors` em vez de telefone hardcoded (§4.1). |
| `backend/app/follow_up/scheduler.py` | Modificar | Template proativo resolvido a partir do vendedor destino (§4.1). |
| `backend/app/agent/prompts/base.py` | Modificar | Derivação plena da regra de nomeação a partir da tabela `vendors` (§4.2). |
| `backend/app/buffer/processor.py` | Modificar (`_resolve_media`) | Injetar `[imagem: <descrição>]` via visão nativa Gemini (§3.3). |
| `backend/app/agent/vision.py` | Criar | `describe_image_inbound(bytes, mimetype)` via `generateContent` (§3.3). |
| `backend/app/whatsapp/media.py` | Remover | Código morto (`describe_image`/GPT-4o) aposentado (§3.3). |
| `backend/tests/test_vendor_routing.py` | Criar | Teste do destino de handoff por segmento com `enabled=false`. |
| `backend/tests/test_inbound_vision.py` | Criar | Teste da injeção de descrição de imagem inbound. |
