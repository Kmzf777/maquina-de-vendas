# Spec — Determinismo de catálogo, frete, nome e pontuação (Valéria inbound)

**Data:** 2026-07-15
**Branch:** `fix/valeria-determinismo-catalogo-1507`
**Origem:** Auditoria QA do fluxo `valeria_inbound` de 15/07/2026.

---

## Contexto e reconciliação da auditoria

A auditoria apontou cinco classes de falha. A investigação do código corrigiu duas premissas
antes de qualquer implementação, e isso muda o que deve ser feito.

O frete de **R$55** entregue ao Natanael **não foi alucinação**. R$55 é a constante real da
região `sul_sudeste` em `backend/app/agent/pricing.py:38`, e o CEP 92702050 (Gravataí/RS)
pertence de fato a essa região. O que diverge entre Natanael (atacado) e Renato (private label)
é política de stage: o roteiro de `atacado` **duplica a tabela de frete em prosa**
(`valeria_inbound/atacado.py:114-138`), permitindo que o modelo leia e cite o valor direto,
enquanto o `private_label` defere ao João Bras (`private_label.py:28`). O defeito real é a
duplicação da tabela (fonte de verdade paralela e sujeita a drift) somada à inconsistência
entre stages.

O **drip coffee** também não é contradição de catálogo no sentido apontado: "Drip Coffee
Canastra Suave — Display 10 sachês" (R$24,90) e "Cápsula Canastra — Display 10 cápsulas"
(R$22,90, compatível Nespresso) são produtos **ativos** no setor Atacado. A foto enviada ao
Natanael estava correta; o erro foi a Valéria **negar** o produto para o GSkamargo ("a gente
não faz ainda"). A nuance é que drip/cápsula existem só no Atacado, não como SKU de private
label — por isso a negação era meio-verdadeira no contexto de marca própria, mas factualmente
errada como frase absoluta.

As outras três falhas se confirmam. O **preço do Bruno** ("Clássico 250g emb. cliente R$27,70 /
50 un") são exatamente os números da linha *Microlote 250g emb. cliente* do banco — o modelo
transcreveu a linha errada, porque a **divulgação** de preço de item único não passa por
ferramenta nenhuma (só o total multi-item passa por `calcular_orcamento`). As **notas
sensoriais** estão triplicadas e divergentes entre banco, prosa de prompt e legendas de foto
(ex.: legenda diz "Suave — melaço e frutas amarelas", mas melaço é do Microlote; o banco diz
Suave = achocolatadas). O **"?" em afirmação** vem de `splitter.py:169-211`, cujo
`_QUESTION_STARTERS` inclui "faz sentido" e "te interessa". O **"olá meu"** vem de
`sanitize_display_name` não remover "meu nome é X" antes do `.split()[0]` em `worker.py:162`.

A abordagem de **fornecedor** (Gustavo) fica fora de escopo por decisão do usuário.

---

## Fonte de verdade canônica (extraída do banco `products`)

Notas sensoriais canônicas (descrições do setor Atacado):

- **Clássico**: torra escura, notas caramelizadas e achocolatadas, 84 SCA.
- **Suave**: torra média, notas achocolatadas, 84 SCA.
- **Canela**: torra escura, caramelizado com canela natural, 84 SCA.
- **Microlote**: 86 SCA, médio corpo, notas de cacau, melaço e finalização cítrica.

Preços/lotes de private label (fonte: banco, injetado via `<catalogo_de_produtos>`):

- Café Canastra 250g emb. Canastra — R$26,70 / 100 un
- Café Canastra 250g emb. cliente — R$25,70 / 100 un
- Café Canastra 500g emb. Canastra — R$48,70 / 100 un
- Café Canastra 500g emb. cliente — R$47,70 / 100 un
- Microlote 250g emb. Canastra — R$29,70 / 100 un
- Microlote 250g emb. cliente — R$27,70 / 50 un  *(a linha que vazou pro Clássico do Bruno)*

Frete (fonte única: `pricing.py` `FREIGHT_TABLE`): sul_sudeste R$55, centro_oeste R$65,
nordeste R$75, norte R$85; Uberlândia flat R$15. **Não é alterado** — permanece a fonte única.

---

## Mudanças por frente

### Frente A — Pontuação "?" em afirmação (`humanizer/splitter.py`)

Remover `"te interessa"` e `"faz sentido"` de `_QUESTION_STARTERS` (linhas 169-180). São
aberturas ambíguas que o roteiro usa em afirmações de acolhimento. O modelo já é instruído a
colocar "?" nas perguntas reais (`voice_card.py:36-43`), e `_ensure_question_mark` retorna cedo
quando a bolha já termina em "?", então perguntas reais ("faz sentido pra você?") não perdem o
"?". Ownership: `splitter.py` + testes de splitter. Verificar e ajustar
`test_splitter_question_guard_2026_07_11.py` e `test_valeria_rubens_interrogacao_2026_06_27.py`
se assumirem o comportamento antigo.

### Frente B — Higiene de nome ("olá meu")

Em `backend/app/leads/service.py`, estender `strip_greeting_prefix` (ou helper chamado por
`sanitize_display_name`) para remover prefixos de apresentação no início: "meu nome é/eh/e",
"me chamo", "meu nome", "sou o/a", "aqui é o/a", "pode me chamar de". Após remover, se o resto
cair em `_CONVERSATIONAL_NON_NAMES` ou ficar vazio, retornar `None`. Como `worker.py:162` e
`scheduler.py` derivam o primeiro nome a partir dessas funções, o conserto na base cobre
broadcast, follow-up e LP. Ownership de service.py/worker.py fica na Frente B; a sanitização de
ingresso em `_t_salvar_nome` fica na Frente C (dona de `tools.py`) para evitar edição
concorrente do mesmo arquivo. Testes: `sanitize_display_name("meu nome é Ricardo") == "Ricardo"`,
`_lead_first_name` → "Ricardo".

### Frente C — Legendas sensoriais e ingresso de nome (`agent/tools.py`)

Criar um dicionário canônico único de notas sensoriais no topo de `tools.py` e derivar
`PHOTO_CAPTIONS`/`PRODUTO_PHOTO_MAP` dele, corrigindo: foto_1 Clássico → "torra escura, notas
caramelizadas e achocolatadas"; foto_2 Suave → "torra média, notas achocolatadas" (remove
melaço/frutas amarelas); foto_4 Microlote → "86 SCA, notas de cacau, melaço e finalização
cítrica"; foto_5 (Drip/Nespresso) permanece (produtos reais). Aplicar `sanitize_display_name`
em `_t_salvar_nome` (tools.py:452) antes de persistir, ignorando o update quando o resultado for
`None` (não sobrescrever nome bom com lixo). Testes: consistência das legendas contra o
dicionário canônico + salvar_nome sanitiza.

### Frente D — Frete determinístico, preço de linha e política de drip (prompts + orchestrator)

Em `valeria_inbound/atacado.py`, remover a tabela de frete em prosa (linhas 114-138) e
substituir por diretriz: "frete é SEMPRE calculado via `calcular_orcamento` após o CEP — nunca
cite valores de frete de cabeça ou de tabela". Manter a regra de pedir o CEP antes e a exceção
do Kit Amostra (frete incluso). O `private_label` continua deferindo ao João.

Em `valeria_inbound/private_label.py`, adicionar regra de **casamento de linha**: ao divulgar
preço/lote de um item, casar produto + gramatura + embalagem exatos da tag
`<catalogo_de_produtos>` e nunca citar o valor de outra linha como se fosse o item pedido.
Reforçar o preâmbulo do bloco de catálogo em `orchestrator._build_catalog_block` com a mesma
regra. Adicionar a **política de drip/cápsula**: reconhecer que existem como produto Canastra
pronto (atacado/varejo), mas esclarecer que a personalização em private label ainda não é
oferecida.

Testes estruturais: atacado sem valor de frete hardcoded + com a diretriz de tool;
`pricing.py` mantém sul_sudeste=55; private_label com a regra de casamento de linha e a política
de drip.

---

## Orquestração de subagentes (propriedade de arquivo, sem colisão)

- **Agente 1 (Style):** `humanizer/splitter.py` + testes de splitter.
- **Agente 2 (Nome-base):** `leads/service.py`, `broadcast/worker.py` + testes de nome.
- **Agente 3 (tools.py):** `agent/tools.py` (legendas canônicas + `_t_salvar_nome`) + testes.
  Depende comportamentalmente da Frente B (roda após o Agente 2).
- **Agente 4 (Prompts):** `valeria_inbound/atacado.py`, `valeria_inbound/private_label.py`,
  `valeria_outbound/atacado.py` (se necessário), `orchestrator.py` + testes estruturais.

Nenhum arquivo é escrito por dois agentes. Agentes 1, 2 e 4 rodam em paralelo; o Agente 3 inicia
após o Agente 2 para respeitar a dependência comportamental do `sanitize_display_name`.

## Validação

Suíte pytest do backend (`cd backend && python -m pytest -m "not integration"`) deve permanecer
verde. Cada frente adiciona testes estruturais/unitários das novas travas. `pricing.py` e o
contrato de handoff (`handoff.py`) permanecem intocados. Sem push a master sem autorização do
usuário (fluxo git do CLAUDE.md).

## Fora de escopo

Guard de fornecedor/vendedor inbound (Gustavo); qualquer alteração em `pricing.py`,
`FREIGHT_TABLE` ou contratos persistidos de handoff; refatoração ampla dos exemplos de tom nos
prompts além dos números comprovadamente inexistentes no catálogo.
