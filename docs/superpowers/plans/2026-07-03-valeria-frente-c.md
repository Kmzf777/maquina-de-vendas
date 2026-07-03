# Frente C — Engenharia de Prompt e Tools (com declaração de fluxo/perfil por bloco)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development para implementar task a task. Steps usam checkbox (`- [ ]`).
> **REGRA DESTA FRENTE:** toda mudança de prompt DECLARA no commit e no report: fluxo (`inbound`/`outbound`/`ambos-via-base`) + perfil (`base`/`secretaria`/`atacado`/`private_label`/`consumo`/`exportacao`). Práticas obrigatórias do guia `gemini-prompting-strategies.md` (lido na íntegra na fase de arquitetura): instruções claras/específicas com termos ambíguos definidos; **few-shot sempre** com formatação consistente com os exemplos já existentes no arquivo; delimitadores XML consistentes com os já usados; instruções críticas no início da seção correta; contexto antes/tarefa no fim (`<final_instruction>` permanece a ÚLTIMA tag — NUNCA inserir nada depois dela); decomposição por componente (cada regra no arquivo de estágio mais estreito; só vai ao `base` o que vale para todos os estágios).

**Goal:** Fechar as falhas de comportamento da janela 01–02/07 que são de prompt/tool: rigidez da triagem diante de pergunta concreta (Javier: "12 pacotes de 250g, quanto fica?" → recebeu questionário; Melina: pergunta de desconto ignorada; saimon: saca de 60kg nunca endereçada), promessa sem entrega (Melina: "vou te passar um cupom" e o cupom nunca veio; Javier ganhou o dele inline), confusão de catálogo exposta ao cliente (Edgar: "o sistema não achou o Suave em grãos de 500g" — produto errado, 2×, com substituição silenciosa de item), nomes-lixo da LP cascateando para templates ("olá Olá," / "Olá, Olá,!"), e `marcar_interesse` nunca disparado na janela (0 follow-ups agendados).

**Architecture:** Prompts em `backend/app/agent/prompts/` (base compartilhado + estágio por arquivo). Tools/serviços: `pricing.py::match_products`, `tools.py::calcular_orcamento` (mensagens de retorno), `lp_webhook/service.py::_sanitize_lead_name`, `leads/service.py::sanitize_display_name`, renderizadores de template (`follow_up/scheduler.py::_build_joao_handoff_components`/`_render_joao_handoff_text` e o caminho do disparo lp_welcome/broadcast que injeta `{{primeiro_nome}}` — localizar por grep `primeiro_nome|nome_do_lead`). Nenhuma migração de banco.

## Global Constraints

- Testes de `backend/` com `python -m pytest ...`; suíte ampla com `-m "not integration"`; baseline = número verde vigente ao iniciar (confirmar). Nenhum teste existente pode quebrar.
- Prompts: NUNCA remover regras existentes sem mandato explícito desta frente; inserções seguem numeração/formato vigentes; few-shots novos no MESMO formato dos vizinhos do arquivo (ex.: ❌/✅ quando o arquivo já usa; "User:/Assistant:" quando é o padrão local). `FINAL_INSTRUCTION` intocada e última.
- Cada task de prompt adiciona asserts estruturais em `backend/tests/test_prompts_frente_c_2026_07_03.py` (arquivo único da frente, criado na Task 1 e estendido pelas seguintes): presença dos blocos novos, ausência dos textos removidos, e invariantes (ex.: a string do prompt de estágio contém a tag/número esperado). Não são testes de comportamento de LLM — são pinos de regressão de edição.
- Tools: mensagens de retorno para o LLM em pt-BR, curtas, SEM stack/detalhe técnico; nunca instruir o modelo a citar "sistema" ao cliente.
- Voz da Valéria em qualquer texto de exemplo destinado ao lead (minúsculas, sem ".", 1 pergunta, sem promessa vazia).
- Comentários de código pt-BR citando os casos reais.

---

## Task 1 (C-1): Fast-path de demanda concreta na triagem

**Declaração:** fluxo **inbound** · perfis **secretaria** (`valeria_inbound/secretaria.py`) e **base** (`prompts/base.py` — compartilhado inbound+outbound; a emenda vale para os dois fluxos por design, declarar assim no commit).

**Files:** Modify `backend/app/agent/prompts/valeria_inbound/secretaria.py`, `backend/app/agent/prompts/base.py`; Create `backend/tests/test_prompts_frente_c_2026_07_03.py`.

**Design:**
1. `secretaria.py`, dentro de `<triage_flow>`, ANTES da "ETAPA 1", inserir o bloco (verbatim, ajustando apenas indentação/estilo local):

```
## ETAPA 0.5: DEMANDA CONCRETA NA ABERTURA (fast-path — prioridade sobre as Etapas 1-3)

Definicao: "demanda concreta" = a mensagem do lead ja contem pedido objetivo com
quantidade, produto, preco, frete ou formato (ex: "quero 12 pacotes de 250g, quanto fica?",
"tem desconto pra compra maior?", "quero saca de 60kg").

Se a mensagem do lead ja traz demanda concreta:
1. RECONHECA o pedido especifico em UMA bolha curta — o lead precisa ouvir que a pergunta
   dele foi registrada (ex: "sobre os 12 pacotes de 250g, ja te passo o caminho certinho").
2. NAO rode a triagem completa. Faca no maximo UMA pergunta de classificacao — apenas a que
   falta para rotear (em geral: uso proprio, negocio ou marca propria).
3. Ao identificar o stage, execute mudar_stage IMEDIATAMENTE. A pergunta concreta do lead
   sera respondida no primeiro turno do novo stage — nunca a deixe sem resposta.
4. PROIBIDO responder pedido objetivo apenas com "vou te explicar tudo isso ja ja" sem o
   passo 1 (reconhecimento do pedido especifico).

PRECEDENCIA SACA/GRAO VERDE (multi-intencao): se o lead menciona saca/grao verde JUNTO de
outra demanda (ex: "saca de 60kg OU cafe com minha marca"), NUNCA ignore a parte da saca:
diga em uma bolha que saca/grao verde e direto com o Joao Bras, e ENTAO conduza a outra
demanda. Nenhuma das duas intencoes pode ficar sem resposta.
```

2. `secretaria.py`, `<critical_constraints>`: emendar a linha da deflexão ("Se o cliente perguntar sobre precos... 'vou te explicar tudo isso ja ja...'") para exigir o reconhecimento específico primeiro: `"Se o cliente perguntar sobre precos ou produtos antes do redirecionamento: RECONHECA o pedido especifico (ETAPA 0.5, passo 1) e diga que ja te explica assim que entender UMA coisa — nunca use a frase generica sozinha."`
3. `secretaria.py`, `<few_shot_examples>`: 3 exemplos novos no formato local (User/Assistant), derivados dos casos reais:
   - **Javier:** User "Preciso de café especial em embalagem de 250g. Precisamos de 12 pacotes. Quanto fica o total?" → Assistant reconhece os 12 pacotes em 1 bolha + UMA pergunta de classificação (uso próprio/negócio/marca própria) — SEM "com quem eu tô falando?" como primeira reação.
   - **Melina:** User "vcs têm desconto pra compras maiores? quanto seria?" → Assistant reconhece a pergunta de volume + 1 pergunta de classificação, prometendo a resposta logo após ("já te respondo certinho, só me diz uma coisa" é PROIBIDO? — "já te respondo" é promessa vazia banida; usar forma sem promessa: "pra te dizer certinho de desconto por volume, me diz só: é pro seu negócio ou consumo próprio?").
   - **saimon (precedência saca):** User "Quero saca de 60kg em grãos, ou o café moído com minha marca" → Assistant: 1 bolha "saca de 60kg quem fecha direto é o Joao Bras, já te deixo com ele no fim" + segue UMA pergunta sobre a marca própria.
4. `base.py`, seção "# ORDEM DE EXECUÇÃO (TEXTO E FERRAMENTAS)": acrescentar parágrafo: `"Se houver uma PERGUNTA CONCRETA do lead ainda nao respondida (quantidade, preco, frete, formato), a primeira resposta apos mudar_stage RESPONDE essa pergunta ANTES do hook de descoberta do novo estagio — a pergunta do cliente nunca fica para depois do questionario."`
5. Testes estruturais: prompt de secretaria contém "ETAPA 0.5" e "PRECEDENCIA SACA"; NÃO contém a deflexão antiga isolada (`"responda: \"vou te explicar tudo isso ja ja"`); base contém a frase da ordem de execução; `build_system_prompt(..., stage="secretaria")` monta sem erro e `<final_instruction>` é o último bloco.

- [ ] Step 1: testes estruturais que falham → Step 2: rodar → Step 3: implementar → Step 4: `-k "prompts or secretaria"` + suíte → Step 5: commit `feat(prompts): fast-path de demanda concreta na secretaria [inbound/secretaria+base] (Frente C1, casos Javier/Melina/saimon)`.

---

## Task 2 (C-2): Promessa de envio = entrega no mesmo turno + consumo atômico + anti-eco de despedida

**Declaração:** fluxo **ambos-via-base** (regra e checklist no `base.py` compartilhado) · perfis **base** e **consumo** (`valeria_inbound/consumo.py`, inbound).

**Files:** Modify `backend/app/agent/prompts/base.py`, `backend/app/agent/prompts/valeria_inbound/consumo.py`; extend teste da frente.

**Design:**
1. `base.py`, `<constraints>` após a regra 31 (seguir numeração real do arquivo — conferir; se 32 já existir, usar o próximo número livre):

```
32. PROMESSA DE ENVIO = ENTREGA NO MESMO TURNO:
    Se voce disser que vai passar/enviar/mandar algo entregavel por texto (cupom, link,
    valores, endereco), a MESMA resposta DEVE conter o item prometido. Se a entrega depende
    de ferramenta (fotos, contato), chame a ferramenta NESTE turno. PROIBIDO encerrar um
    turno com "vou te passar X" sem X (falha real 02/07: lead recebeu "vou te passar um
    cupom de 10%" e o cupom nunca veio — promessa sem entrega e pior que nao prometer).
```

2. `base.py`, "# CHECKLIST ANTES DE RESPONDER": novo item (número sequencial): `"Prometi enviar/passar algo NESTA mensagem? O item prometido esta NESTE turno (ou a ferramenta foi chamada)?"`
3. `consumo.py`: reescrever a "Etapa 1" para tornar anúncio+link+cupom UM turno atômico e indivisível, com few-shot negativo do caso real:

```
### REGRA ATOMICA DO CUPOM (falha real 02/07 — lead ficou sem o cupom prometido):
O anuncio do cupom e a entrega SAEM NO MESMO TURNO, sempre nesta forma (3 bolhas):
"vale a pena conhecer, vou te passar um cupom de 10% de desconto pra nossa loja online"
"link: https://loja.cafecanastra.com\n\ncupom: ESPECIAL10"
"qualquer duvida sobre os cafes, me chama aqui"
PROIBIDO enviar a 1a bolha sem as demais no mesmo turno.
```

   Few-shot: ❌ turno só com "vou te passar um cupom de 10% de desconto pra primeira compra la" / ✅ turno completo com link+cupom.
4. `consumo.py`: regra anti-eco de despedida (caso Javier — "bom café pra você" 2×): `"Se o lead reagir com emoji/agradecimento DEPOIS da sua despedida, NAO repita a mesma despedida: responda com um ack curto DIFERENTE ('valeu' / 'to por aqui') ou nada de novo alem do ack — nunca o mesmo texto 2x."` + few-shot.
5. Testes estruturais: base contém a regra nova e o item de checklist; consumo contém "REGRA ATOMICA" e o anti-eco; numeração não colide (assert de que não há regra duplicada "32." se já existir outra — o implementer confere o arquivo real).

- [ ] Steps 1–5 (TDD estrutural; commit `feat(prompts): promessa=entrega no turno + cupom atomico + anti-eco [ambos-via-base/base+consumo-inbound] (Frente C2, casos Melina/Javier)`).

---

## Task 3 (C-3): match_products por tokens + not-found com opções + reação a erro de tool no atacado

**Declaração:** código transversal (`pricing.py`/`tools.py`) + prompt fluxo **inbound** · perfil **atacado** (`valeria_inbound/atacado.py`) + 1 emenda no **base** (motivo analítico do handoff — vale ambos os fluxos).

**Files:** Modify `backend/app/agent/pricing.py`, `backend/app/agent/tools.py`, `backend/app/agent/prompts/valeria_inbound/atacado.py`, `backend/app/agent/prompts/base.py`; Test `backend/tests/test_match_products_tokens_2026_07_03.py` + extend teste da frente.

**Design:**
1. `pricing.py::match_products` → match por TOKENS (AND, ordem livre): normalizar consulta e nome (função `_normalize_text` existente) + tokenizar; normalização de peso antes da tokenização (`"500 g"→"500g"`, `"1 kg"→"1kg"`); stopwords de preposição removidas da CONSULTA (`de`, `em`, `com`, `do`, `da`, `o`, `a`) — "Suave em grãos 500g" → tokens `{suave, graos, 500g}`; produto casa se TODOS os tokens da consulta aparecem no nome normalizado (substring por token). Preservar `MAX_DISAMBIGUATION`. Manter comportamento para consulta vazia ([]).
2. `tools.py::calcular_orcamento`: retorno de 0 matches passa a listar opções: `f"Produto '{item.produto}' não encontrado no catálogo de atacado. Disponíveis: {', '.join(nomes[:MAX_DISAMBIGUATION])}. Confirme com o cliente qual ele quer."` (nomes = produtos ativos do setor, ordem estável).
3. `atacado.py`, novo `<critical_constraints>` (inserir junto dos demais constraints, ANTES das instructions):

```
## Reacao a erro de ferramenta — o cliente NUNCA ve a cozinha
O retorno das ferramentas (calcular_orcamento, enviar_fotos) e INTERNO. PROIBIDO dizer ao
cliente "o sistema nao achou", "deu erro aqui", "o sistema travou" ou nomear qual item o
sistema supostamente nao encontrou.
- Se calcular_orcamento devolver "produto nao encontrado": confirme a variacao com o cliente
  usando os nomes DISPONIVEIS que a propria ferramenta listou — em tom de vendedora
  ("o Microlote vem so em 250g, mantenho 4 unidades de 250g?"), nunca em tom de sistema.
- Se o cliente pedir uma variacao que NAO existe no catalogo: DIGA que nao existe e ofereca
  a mais proxima. PROIBIDO substituir silenciosamente no orcamento um item por outro.
- Persistencia com limite: na 2a falha consecutiva de ferramenta sobre o MESMO pedido, pare
  de tentar e chame encaminhar_humano com motivo especifico (ex: "orcamento com variacao
  fora do catalogo — fechar manualmente"), nunca motivo generico.
```

   Few-shot (formato local): ❌ `"opa, parece que o sistema não achou o Suave em grãos de 500g"` / ✅ `"o Microlote em grãos vem só em pacotes de 250g\n\nmantenho as 4 unidades de 250g e fecho a conta pro frete grátis?"` (caso real Edgar 02/07 17:15).
4. `base.py`, regra 16 (ENCAMINHAR_HUMANO): acrescentar 1 linha estendendo a exigência analítica do 18b ao `motivo`: `"O motivo segue a regra 18b (analitico, nunca generico): PROIBIDO 'handoff por tempo'/'lead qualificado' secos — diga o gatilho real (ex: 'pediu quantidade acima do lote', 'objecao de preco apos 2 contornos')."`
5. Testes: `test_match_products_tokens_2026_07_03.py` — casos Edgar: consulta "Suave em grãos 500g" casa nome "Café Suave 500g (grãos)"; "suave 500 g" idem; "Microlote em grãos 500g" → 0 matches e a mensagem da tool lista os disponíveis; ">1 match" continua desambiguando; consulta vazia → []. Estruturais: atacado contém "NUNCA ve a cozinha" e o few-shot ❌ do Edgar; base contém a emenda do motivo.

- [ ] Steps 1–5 (o RED principal é o caso Edgar no match; commit `fix(pricing+prompts): match por tokens + not-found com opcoes + erro de tool invisivel ao cliente [inbound/atacado+base] (Frente C3, caso Edgar)`).

---

## Task 4 (C-4): Higiene de nome (LP → CRM → templates)

**Declaração:** código (`lp_webhook`, `leads/service`, renderizadores de template) + prompt fluxo **ambos-via-base** · perfil **base** (só 1 linha no ramo sem-nome).

**Files:** Modify `backend/app/lp_webhook/service.py`, `backend/app/leads/service.py` (`sanitize_display_name`), `backend/app/follow_up/scheduler.py` (`_build_joao_handoff_components`/`_render_joao_handoff_text`) e o(s) renderizador(es) do disparo lp_welcome/broadcast que injeta(m) `{{primeiro_nome}}` (localizar por grep `primeiro_nome`/`nome_do_lead`/`lead_name` nos workers); `backend/app/agent/prompts/base.py` (1 linha); Test `backend/tests/test_name_hygiene_2026_07_03.py`.

**Design:**
1. Helper compartilhado `strip_greeting_prefix(name) -> str | None` (em `leads/service.py`, exportado): remove prefixos de saudação + pontuação/reticências iniciais, case/acento-insensitive: `olá, oi, bom dia, boa tarde, boa noite, tudo bem, e aí`; iterativo (remove múltiplos: "Olá, boa tarde" → ""); retorna o restante title-case-preservado ou None se vazio. Casos reais: `"Boa tarde.... Luiz"` → `"Luiz"`; `"Olá, boa tarde"` → None; `"Boa tarde."` → None; `"Maycon"` → `"Maycon"` (intocado).
2. `lp_webhook/service.py::_sanitize_lead_name`: aplicar `strip_greeting_prefix` ANTES das heurísticas atuais (`?`/`\n`/`@`/>4 palavras): nome que vira None vai para `lp_message` como hoje (preserva o texto cru).
3. `leads/service.py::sanitize_display_name`: também rejeitar (retornar None) nomes cujo strip resulte vazio E usar o restante quando houver ("Boa tarde.... Luiz" exibe/usa "Luiz") — isso ativa automaticamente o ramo "você NÃO sabe o nome" do base prompt (que já instrui perguntar + `salvar_nome`).
4. Renderizadores de template: passar o nome por `strip_greeting_prefix` antes de injetar; quando None/vazio → **fallback neutro `"tudo bem"`** (decisão registrada: a Meta rejeita parâmetro vazio; "olá tudo bem" / "Olá, tudo bem!" são leituras naturais em WhatsApp; documentar em comentário que é fallback deliberado). Aplicar em: `_build_joao_handoff_components` (param `nome_do_lead`), `_render_joao_handoff_text` (persistência coerente com o enviado), e o caminho do lp_welcome/broadcast que injeta `{{primeiro_nome}}`.
5. `base.py`, ramo sem-nome da `name_instruction`: acrescentar: `"Se o cadastro tiver um nome que parece saudacao ('Olá, boa tarde'), trate como SEM nome — descubra o nome real e chame salvar_nome."`
6. Testes: helper (casos reais acima + acentos/caixa); `_sanitize_lead_name` integrando o strip; `sanitize_display_name`; componentes do template do João com nome-lixo → param `"tudo bem"`; render persistido idem; lp_welcome com nome-lixo → `"tudo bem"` (ou o fallback no ponto certo do worker); estrutural do base.

- [ ] Steps 1–5 (commit `fix(leads+templates): higiene de nome com strip de saudacao + fallback neutro em templates [base] (Frente C4, casos "Olá, boa tarde"/"Boa tarde.... Luiz")`).

---

## Task 5 (C-5): Reforço do marcar_interesse no momento-preço

**Declaração:** fluxo **ambos-via-base** (checklist) + few-shots fluxo **inbound** · perfis **base**, **atacado**, **private_label**.

**Files:** Modify `backend/app/agent/prompts/base.py`, `valeria_inbound/atacado.py`, `valeria_inbound/private_label.py`; extend teste da frente.

**Design:**
1. `base.py`, checklist: novo item: `"O lead perguntou preco/condicoes ou pediu orcamento NESTE turno? Se sim: ja chamei marcar_interesse? (regra 19 — sem isso o follow-up automatico nao arma)"`.
2. `atacado.py` few-shot: User pergunta preço → Assistant (nota do exemplo: chama `calcular_orcamento` E `marcar_interesse` no mesmo turno; o exemplo mostra a resposta textual e a nota explica as tools — seguir o formato de notas que o arquivo já usa).
3. `private_label.py`: few-shot análogo (lead pergunta valores do private label → nota: `marcar_interesse(nivel="quente"...)` junto da resposta de preço). LER o arquivo antes (não foi lido na arquitetura) e seguir sua estrutura/formatos.
4. Estruturais: os três arquivos contêm as inserções; nota de que B3 (gatilho determinístico) é a rede primária e isto é reforço (comentário no teste).

- [ ] Steps 1–5 (commit `feat(prompts): reforco marcar_interesse no momento-preco [base+atacado+private_label inbound] (Frente C5)`).
