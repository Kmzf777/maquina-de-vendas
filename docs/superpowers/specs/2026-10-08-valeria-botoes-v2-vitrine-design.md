# ValerIA de Botões v2: vitrine primeiro, texto livre entendido

**Data:** 2026-10-08
**Branch:** `feat/valeria-botoes-v2-vitrine` (nascida de `master` em `f9cff5de`)
**Antecessora:** `2026-09-29-valeria-botoes-design.md` (v1, em produção desde 30/09/2026)
**Evidência:** [comparativo v1 × IA antiga](https://claude.ai/artifact/MfayN5EYhLppFdKe9icyhP)

---

## 1. Problema

A v1 resolveu o que se propunha: os repasses ruins ao João caíram de 20% para 3%. Mas no saldo
o João passou a receber **38% menos leads bons**. Comparação de leads Meta: 24–30/09 com a IA
antiga e 01–06/10 com a v1, 374 conversas auditadas uma a uma.

| | IA antiga | v1 botões |
|---|---|---|
| Leads bons entregues a cada 100 leads | 29,5 | 18,4 |
| Repasses que não deviam ter ido | 20% | 3% |
| Lead nem toca no 1º menu (N0) | — | 41% |
| Conversa com atrito forte | 3% | 14% |

Causas, das 23 perdas de lead bom na v1:

- **9 — texto livre rebatido.** O lead escreve uma pergunta real e recebe "é só tocar numa das opções 👇".
- **6 — pararam na oferta final.** Responderam tudo e não clicaram "Sim, quero falar". A v1 não tem repasse automático, e na IA antiga ele entregou 19 dos 52 leads bons.
- **4 — clicaram "Não agora".**
- **4 — abandonaram no meio das 5 perguntas.**

E a leitura das **1.492 conversas da IA antiga** com resposta do lead (maio–outubro) mostra o que
o lead quer:

- **Preço é a pergunta de 55% dos leads**, e 38% nunca chegaram a ver preço.
- **Foto e preço juntos** tiveram 38% de reação positiva. Só foto teve 18% e só preço teve 16%.
- O **Kit Amostra** gerou 20 das 33 vendas originadas no número da ValerIA.
- A IA antiga errava regras fixas: pedido mínimo, preço do kit, prazo do PL, preços inventados.

A v1 faz o oposto do que o lead pede. Mostra **uma** foto, **depois** de 5 perguntas, e às
vezes sem preço (`preco_do_no` exige 1 SKU).

## 2. Objetivo

1. Mostrar **produtos com foto e preço na 2ª mensagem**, por um carrossel, mais a tabela completa e as regras comerciais.
2. **Entender texto livre** sem deixar a IA escrever ao cliente.
3. Encurtar a qualificação para **2 perguntas depois da vitrine**.
4. Repassar automaticamente quem mostrou intenção e parou.
5. Manter os textos fixos e confirmados, que eliminaram os repasses ruins.

**Meta de sucesso**, medida 7 dias após a ativação, com o mesmo recorte e a mesma régua do comparativo:

| Indicador | v1 | Meta |
|---|---|---|
| Leads bons entregues a cada 100 leads | 18,4 | ≥ 29 |
| Repasses que não deviam ter ido | 3% | ≤ 5% |
| Lead viu preço | ~25% | ≥ 80% |
| Conversa com atrito forte | 14% | ≤ 5% |

**Não-objetivos:**
- Mudar os leads do Google/LP. Eles seguem na IA antiga, porque `lp_webhook` grava o perfil `674beb13` na conversa, e servem de grupo de controle.
- Mudar o atendimento do João.
- Mudar os ramos Consumo (C1) e Exportação (E1–E4).

---

## 3. Decisões

| Decisão | Alternativa recusada | Por quê |
|---|---|---|
| **Vitrine logo após o ramo** | Manter as 5 perguntas e trocar só o N5 por vitrine | 41% param no N0 e mais 15% no meio das perguntas. Mostrar valor no fim não alcança quem sai antes. O mercado (Arbor, Artefato) mostra preço, mínimo e frete no 1º contato. |
| **Carrossel interativo** (`interactive.type = "carousel"`) | 3 imagens soltas + texto; catálogo do Commerce Manager | O carrossel é uma mensagem só, roda em sessão sem template nem catálogo (doc da Meta, conferida em 07/10), e cada card tem botão. O catálogo cobra um preço por item, e isso encaixa mal com a tabela por formato. |
| **IA só classifica; nunca escreve** | Zero IA (como na v1); IA conversando com fatos travados | A v1 decidiu "zero IA, inclusive no texto livre". **Esta spec reverte essa decisão, com aprovação do dono em 08/10/2026**, porque o texto rebatido é a maior perda medida. A IA antiga mostrou o risco de deixar o modelo escrever: todo texto ao cliente continua fixo. |
| **Fluxo novo `valeria_botoes_v2` ao lado do v1** | Editar a v1 no lugar | Ativar e reverter é apontar o perfil do canal, sem deploy. Conversas da v1 em andamento terminam na v1. O comparativo v1 × v2 fica limpo. |
| **Ramo pela mensagem pronta do anúncio** | Sempre perguntar o ramo no N0 | As 4 mensagens prontas dos anúncios abrem 588 das ~650 conversas dos últimos 30 dias e já dizem o ramo. Pular o N0 tira um passo de onde 41% param. **Decisão nova desta spec: precisa do ok do dono na revisão.** |
| **Preços sempre do catálogo `products`** | Preço escrito no texto | Mesmo princípio da v1 (incidente Ritz): preço no texto envelhece em silêncio. O card some se o SKU sumir. |
| **Repasse de parados por varredura própria** | Usar o motor de follow-up | O follow-up gerou ~1M jobs duplicados em 03–04/10. Uma varredura idempotente com trava no `flow_state` é menor e auditável. |

---

## 4. Fatos de negócio (fonte: dono, 08/10/2026)

São os únicos números que o funil pode afirmar. Eles entram como **conteúdo editável**
(`valeria_flow_content`), não como código.

| Fato | Valor |
|---|---|
| Pedido mínimo atacado | **R$ 500,00**, compondo livremente produtos e quantidades |
| Frete atacado | **Grátis acima de R$ 2.000,00**; até esse valor, calculado pelo CEP |
| Pedido mínimo PL | **100 unidades** (inclusive Microlote) |
| Frete PL | Sempre calculado à parte |
| Pagamento | PIX · cartão em até 2x sem juros · boleto à vista (pedido enviado após a confirmação) |
| Prazo de produção PL | **Até 15 dias úteis** |
| Fotolito PL | **R$ 100,00**, só no 1º pedido |
| Preço de revenda (referência ao consumidor) | 250g: R$ 35–50 · 500g: R$ 50–65 (atacado e PL) |

**Pendentes com o João.** O funil não pode afirmar nenhum destes números até a confirmação:

- **Kit Amostra:** composição e valores por região, incluindo GO e MS.
- **Microlote PL:** preço.

O catálogo do CRM também está divergente: diz `min_lot = 50 un` no Microlote PL e precisa ser
corrigido para 100 pelo modal de Preços.

Enquanto houver pendência, o fluxo se comporta assim:

- **Kit:** o texto não traz preço nem composição ("temos um kit pra você provar nossos cafés antes do pedido; o João te passa o valor e o frete pro seu CEP"), e "Quero o kit" repassa ao João com a tag `Botões: Kit amostra`. Quando o João confirmar, alguém edita o texto na tela "Fluxo da Valéria", sem deploy.
- **Microlote PL:** o card existe no registry, mas só é enviado quando o SKU `Microlote 250g — c/ embalagem Canastra` está ativo, com preço e com `min_lot = 100 un`.

---

## 5. Fluxo v2

```
1ª mensagem do lead
  ├─ é a mensagem pronta de ATACADO ─────────────────────────────┐
  ├─ é a mensagem pronta de PL ───────────────────────────┐      │
  └─ qualquer outra → N0 (lista: Revender ou servir |     │      │
                         Minha marca | Consumo próprio |  │      │
                         Exportação)                      │      │
                                                          ▼      ▼
                                                         VP     VA   (vitrines, §6)
                                                          │      │
       botões após a vitrine:  Fazer pedido/orçamento · Provar antes · Tenho dúvida
                                       │                    │             │
                          QA1→QA2 / QP1→QP2                VK            VD (lista de dúvidas)
                                       │                    │             │
                          T_HANDOFF / T_HANDOFF_PL     T_KIT (João)   resposta fixa → volta
                          ou T_PL_ABAIXO                              à tela de onde veio
```

Consumo (`C1`) e Exportação (`E1`→`E4`→`T_HANDOFF_ARTHUR`) são copiados da v1 sem mudança, e os
terminais `T_ADIAR`, `T_ADIADO`, `T_HUMANO`, `T_FIM` e `T_OPTOUT` também.

### 5.1 Roteamento pela mensagem pronta

A comparação é por igualdade depois de `engine.normalizar` (minúsculas, sem acento e sem
pontuação), contra uma tupla fechada no registry:

| Mensagem pronta (texto exato) | Vai para |
|---|---|
| `Olá! Tenho um comércio e quero revender café especial.` | `VA` |
| `Olá! Quero saber mais sobre compra por atacado.` | `VA` |
| `Olá! Quero café com a minha marca — já tenho CNPJ` | `VP` |
| `Olá! Quero saber mais sobre ter a Marca Própria de Café.` | `VP` |

Qualquer outro texto, inclusive uma variação editada pelo lead, vai para `N0`. Nenhuma IA entra
nesse ponto.

### 5.2 Nós novos

Os textos abaixo são os defaults do registry. Todos os corpos e rótulos são editáveis na tela,
como na v1, e cada rótulo de botão tem no máximo 20 caracteres.

**N0 · Ramo** (`lista`, igual à v1, com novos destinos)
> oi! aqui é a Valéria, do comercial da Café Canastra ☕ me diz: o café é pra qual caso?

| id | Rótulo | Destino |
|---|---|---|
| `negocio` | Revender ou servir | `VA` |
| `marca` | Com a minha marca | `VP` |
| `consumo` | Pra consumo próprio | `C1` |
| `exportacao` | Pra exportação | `E1` |

**VA · Vitrine atacado** (`carrossel`, ver §6.1). Os botões de ação são enviados na 3ª mensagem:

| id | Rótulo | Destino | Grava |
|---|---|---|---|
| `card:<sku>` (em cada card) | Quero esse | `QA1` | `produto_interesse=<sku>`, `purchase_intent=clear` |
| `pedido` | Fazer pedido | `QA1` | `purchase_intent=clear` |
| `provar` | Provar antes | `VK` | — |
| `duvida` | Tenho dúvida | `VD` | — |

**QA1 · Tipo de negócio** (`botoes`)
> boa! pra eu já te passar pro João com tudo certo: que tipo de negócio você tem?

`Cafeteria` (segment=cafeteria) · `Loja ou empório` (segment=emporio) · `Outro tipo` (segment=other). Todos vão para `QA2`.

**QA2 · Volume** (`botoes`)
> e quanto café você usa ou vende por mês, mais ou menos?

`Até 30 kg` (30) · `30 a 100 kg` (65) · `Mais de 100 kg` (150) → `T_HANDOFF`. Grava `monthly_volume_kg`, com os mesmos valores da v1.

**VP · Vitrine PL** (`carrossel`, ver §6.2). Ações:

| id | Rótulo | Destino |
|---|---|---|
| `card:<sku>` | Quero esse | `QP1` (grava `produto_interesse`) |
| `orcamento` | Fazer orçamento | `QP1` |
| `provar` | Provar antes | `VK` |
| `duvida` | Tenho dúvida | `VD` |

**QP1 · Marca** (`botoes`)
> pra montar seu orçamento: você já tem a marca?

`Já tenho a marca` → `QP2` · `Vou criar do zero` → `QP2` · `Já tenho os grãos` → `T_HANDOFF_PL`. O último é igual à v1: quem só quer torra vai direto ao João.

**QP2 · Quantidade** (`botoes`)
> e quantos pacotes no primeiro pedido?

`Menos de 100` · `100 a 500` · `Mais de 500`.

Regra de destino, avaliada pelo motor a partir do que foi gravado em `QP1`. É a única regra
condicional do fluxo, e é declarada no registry como tabela, não como `if`:

| QP1 | QP2 | Destino |
|---|---|---|
| criar do zero | Menos de 100 | `T_PL_ABAIXO` |
| qualquer outro | qualquer | `T_HANDOFF_PL` |

**T_PL_ABAIXO** (terminal com botões; não repassa)
> o mínimo pra marca própria é 100 pacotes. pra quem tá começando, um bom primeiro passo é provar nossos cafés com o kit amostra 😊

`Quero o kit` → `T_KIT` · `Mais pra frente` → `T_ADIAR`, que agenda recontato em 30 dias como a v1.

**VK · Kit amostra** (`botoes`)
> (corpo pendente de confirmação; ver §4)

`Quero o kit` → `T_KIT` · `Ver preços de novo` → volta à vitrine do ramo, reenviando só a tabela e os botões, sem o carrossel · `Falar com vendedor` → `T_HANDOFF` ou `T_HANDOFF_PL`, conforme o ramo.

**T_KIT** (terminal de handoff ao João): tag `Botões: Kit amostra` + `Botões: Qualificado`.

**VD · Dúvidas** (`lista`, até 10 linhas, conteúdo por ramo)

| id | Linha | Atacado | PL |
|---|---|---|---|
| `faq_grao` | Grão ou moído? | ✓ | ✓ |
| `faq_minimo` | Pedido mínimo | ✓ | ✓ |
| `faq_frete` | Frete | ✓ | ✓ |
| `faq_pagamento` | Formas de pagamento | ✓ | ✓ |
| `faq_revenda` | Preço de revenda | ✓ | ✓ |
| `faq_capsula` | Cápsula e drip | ✓ | — |
| `faq_prazo_pl` | Prazo de produção | — | ✓ |
| `faq_fotolito` | Arte e fotolito | — | ✓ |
| `faq_outra` | Outra pergunta | ✓ | ✓ |
| `faq_vendedor` | Falar com vendedor | ✓ | ✓ |

Cada `faq_*` (exceto `outra` e `vendedor`) envia a resposta fixa de §6.4 e **volta à tela de
onde o lead veio**, reenviando só os botões, sem carrossel. A tela de origem fica guardada em
`flow_state.retorno`. `faq_outra` responde "pode escrever sua pergunta 🙂" e espera o texto, que
vai ao classificador (§7). `faq_vendedor` vai ao terminal de handoff do ramo.

### 5.3 Nota de handoff ao João

A nota da v1 diz "Nenhuma qualificação por conversa — abordar direto". A v2 envia um resumo
montado do `flow_state` e dos critérios gravados:

```
[ValerIA botões v2] Atacado · interesse: Canastra Clássico 250g
Negócio: cafeteria · Volume: 30 a 100 kg/mês
Viu: vitrine + tabela · Perguntou: frete, pagamento
Mensagens escritas pelo lead: "tenho 2 lojas em BH" / "aceita boleto?"
Origem do repasse: clicou "Fazer pedido"   (ou: repasse automático — parado há 2h em QA2)
```

---

## 6. Vitrine

### 6.1 Atacado: 3 mensagens

**Mensagem 1: carrossel**, corpo ≤ 1024 caracteres:
> esses são os mais pedidos por cafeterias e empórios ☕ preço por pacote, direto da nossa fazenda na Serra da Canastra 👇

| Card | Foto | Texto (≤ 160 caracteres, ≤ 2 quebras de linha) | SKUs |
|---|---|---|---|
| Clássico | `atacado/foto_1_classico.jpg` | `Clássico · torra escura, caramelo e chocolate · 84 pts`<br>`250g: moído {preco:Clássico Moído 250g} · grão {preco:Clássico Grãos 250g}`<br>`500g {preco:…Moído 500g} · {preco:…Grãos 500g} · 1kg grão {preco:…Grãos 1kg}` | 5 SKUs Clássico |
| Suave | `atacado/foto_2_suave.jpg` | idem, com notas "torra média, achocolatado" | 5 SKUs Suave |
| Microlote | `atacado/foto_4_microlote.png` | `Microlote · 86 pts, cacau, melaço e cítrico`<br>`250g moído ou grão: {preco:Microlote 250g}` | 2 SKUs Microlote |

Cada card tem 1 botão de resposta rápida, `Quero esse` (`card:<sku-base>`). A Meta exige que
todos os cards tenham o mesmo número de botões.

**Mensagem 2: tabela completa (texto)**, gerada no envio pelo `valeria_tabela.py`:

```
tabela atacado — preço por pacote 📋

☕ Clássico · Suave
250g  moído R$28,70 · grão R$31,70
500g  moído R$52,70 · grão R$54,70
1kg   grão R$97,70
☕ Canela  250g moído R$28,70
☕ Microlote  250g R$32,70
☕ Néctar de Minas  Gourmet 1kg R$88,70 · moído 500g R$39,70 · Blend 1kg R$79,70
📦 Granel 2kg em grão  Clássico/Suave R$169,70 (R$84,85/kg) · Néctar R$166,70
☕ Cápsulas (10 un) R$22,90 · Drip (10 sachês) R$24,90
⚙️ Moedor profissional R$949 · Moedor + 10 granel R$599

✅ pedido mínimo R$500 — pode misturar os cafés
🚚 frete grátis acima de R$2.000; abaixo, pelo CEP
💳 PIX, cartão em 2x sem juros ou boleto à vista
💰 revenda ao consumidor: 250g R$35–50 · 500g R$50–65
```

As linhas de produto vêm de `products` (setor Atacado, `is_active`). Os agrupamentos são
declarados no registry como uma lista de `(rótulo, [SKUs])`, e um SKU inativo some da linha. As
4 linhas de regra são um nó de conteúdo editável (`REGRAS_ATACADO`).

**Mensagem 3: botões**
> como você quer seguir?
> `Fazer pedido` · `Provar antes` · `Tenho dúvida`

### 6.2 Private label: 3 mensagens

**Mensagem 1: carrossel**
> a gente torra o café na nossa fazenda e entrega com a sua marca ☕ escolhe o formato 👇

| Card | Foto | Texto | Condição de envio |
|---|---|---|---|
| Embalagem Canastra | `private_label/foto_3.jpg` (silk) | `Sua marca na embalagem Canastra`<br>`250g {preco} · 500g {preco}`<br>`mínimo 100 pacotes` | SKUs ativos |
| Embalagem do cliente | `private_label/foto_1.jpg` (embalagem) | `Sua própria embalagem, a gente enche`<br>`250g {preco} · 500g {preco}`<br>`mínimo 100 pacotes` | SKUs ativos |
| Microlote | `private_label/foto_4.jpg` | `Microlote 86 pts com a sua marca`<br>`250g {preco} · mínimo 100 pacotes` | SKU ativo **e** `min_lot = "100 un"` (§4) |

A atribuição foto ↔ card será conferida visualmente na implementação: `foto_3` é o silk e
`foto_1` é a embalagem, segundo `agent/tools.py:214-216`.

**Mensagem 2: como funciona (texto)**
```
como funciona a marca própria 📦

exemplo: 100 pacotes de 250g na embalagem Canastra
= {total} + fotolito R$100 (só no 1º pedido) + frete

1️⃣ você manda a arte  2️⃣ aprovamos juntos
3️⃣ produção em até 15 dias úteis  4️⃣ envio (frete calculado à parte)

💳 PIX, cartão em 2x sem juros ou boleto à vista
💰 revenda ao consumidor: 250g R$35–50 · 500g R$50–65
```
`{total}` é calculado como `100 × preço(Café Canastra 250g — c/ embalagem Canastra)`, formatado
em reais.

**Mensagem 3: botões** `Fazer orçamento` · `Provar antes` · `Tenho dúvida`

### 6.3 Degradação

| Situação | Comportamento |
|---|---|
| Menos de 2 cards enviáveis (SKU inativo ou sem preço) | A mensagem 1 vira texto com as linhas dos cards; a 2 e a 3 seguem. Log `warning`. |
| A Meta recusa o carrossel (erro da API) | Reenvio como 1 mensagem de botões com a foto do 1º card no header, mais as mensagens 2 e 3. Log `error` com o código da Meta. |
| Catálogo indisponível | Sem preço nenhum, a tabela não é enviada. O lead recebe "nossa tabela tá sendo atualizada; o João te manda agora" e vai para o handoff do ramo. Preço errado é pior que preço nenhum. |

### 6.4 Respostas fixas da lista de dúvidas (defaults editáveis)

| id | Atacado | PL |
|---|---|---|
| `faq_grao` | Clássico, Suave e Microlote vêm em grão ou moído. Canela só moído. 1kg e granel só em grão. | Você escolhe: grão ou moído, no 250g ou no 500g. |
| `faq_minimo` | R$500 por pedido, misturando os cafés e as quantidades como quiser. | 100 pacotes por pedido. |
| `faq_frete` | Grátis acima de R$2.000. Abaixo disso, calculado pelo seu CEP. | Sempre calculado à parte, pelo seu CEP. |
| `faq_pagamento` | PIX, cartão em até 2x sem juros ou boleto à vista (o pedido sai depois da confirmação). | idem |
| `faq_revenda` | Referência ao consumidor: 250g de R$35 a R$50 · 500g de R$50 a R$65. | idem |
| `faq_capsula` | Cápsulas compatíveis Nespresso (display 10) {preco} · Drip (display 10 sachês) {preco}. | — |
| `faq_prazo_pl` | — | Produção em até 15 dias úteis depois da aprovação da arte. |
| `faq_fotolito` | — | Você manda a arte e a gente aprova junto. O fotolito custa R$100 e é cobrado só no 1º pedido. |

---

## 7. Texto livre: o classificador

### 7.1 Papel

A IA **lê** o texto ou a transcrição de áudio que o lead mandou e devolve **uma etiqueta**.
Clique em botão nunca passa pela IA. Nenhuma palavra gerada pelo modelo chega ao cliente: a
etiqueta escolhe uma das mensagens fixas deste documento.

### 7.2 Etiquetas

| Classe | Saída extra | O que o motor faz |
|---|---|---|
| `BOTAO` | `botao_id` (um id da tela atual) | Trata como o clique naquele botão. Um id que não existe na tela atual vira `RUIDO`. |
| `FAQ` | `faq_id` (um da tabela §5.2 válido para o ramo) | Envia a resposta fixa e reapresenta os botões da tela atual. |
| `PERGUNTA` | — | Dúvida real fora da lista: handoff do ramo, e a nota leva o texto do lead. |
| `VENDEDOR` | — | Handoff do ramo. |
| `SAIR` | — | `T_OPTOUT`. A lista fixa `FRASES_OPTOUT` continua valendo **antes** da IA. |
| `RUIDO` | — | Nudge com os botões da tela atual. No 2º `RUIDO` seguido, handoff do ramo, com a nota contendo o que foi coletado. |

Sem ramo (`N0`, consumo), `PERGUNTA` e `VENDEDOR` vão para `T_HANDOFF` (João), e não para `T_HUMANO` como na v1: o `T_HUMANO` não envia nada e não designa vendedor, então o lead que fez uma pergunta real ficava sem resposta (decisão de 08/10/2026). Dois `RUIDO` seguidos sem ramo continuam indo para `T_HUMANO`.

### 7.3 Entrada do modelo (~400 tokens)

- id e ramo da tela atual;
- os botões da tela (`id: rótulo`);
- a lista de `faq_id` válidos para o ramo, com 1 linha de descrição cada;
- a última mensagem enviada ao lead;
- o texto do lead.

Sem persona, sem catálogo e sem histórico longo.

Exemplos de casamento que entram no prompt (todos tirados das conversas reais):
- "tenho uma cafeteria" → `BOTAO cafeteria`
- "uns 200 kgs" → `BOTAO mais100`
- "qual o valor do quilo?" → `FAQ` (reapresenta a tabela)
- "tem frete grátis?" → `FAQ faq_frete`
- "vocês fazem café com açaí?" → `PERGUNTA`
- "bom dia" → `RUIDO`

Pergunta de preço no meio da qualificação recebe a resposta "tabela": a mensagem 2 da vitrine
do ramo, sem carrossel.

### 7.4 Implementação

O módulo novo `button_flow/valeria_classifier.py` reaproveita os mecanismos do
`classifier.py`, que já roda em produção na Recuperação:

| Mecanismo | Configuração |
|---|---|
| Modelo | `gemini_client.generate` com `json_mode=True` |
| Teto de gasto | `budget_guard`; estourado, devolve `RUIDO` |
| Registro de uso | `token_usage` com `call_type='valeria_botoes_classify'` |
| Timeout | `VALERIA_CLASSIFIER_TIMEOUT_S`, default 12s |
| Variável de modelo | `VALERIA_CLASSIFIER_MODEL`, default `gemini-2.5-flash-lite`, lida por `os.getenv`, não por `Settings` (ver o cabeçalho do `classifier.py`) |

Os helpers comuns (`_contabilizar`, `_budget_estourado`, chamada com timeout) são extraídos para
`button_flow/_llm_comum.py`, e os dois classificadores passam a importar de lá. O
comportamento da Recuperação não muda, e o teste dela deve seguir verde.

**Nunca levanta.** Timeout, quota, JSON inválido, classe ou id inventado: tudo vira `RUIDO`. A
saída é validada contra os ids da tela atual e do ramo antes de chegar ao motor.

---

## 8. Repasse automático de parados

Um job periódico do worker (`valeria_repasse_parados`, a cada 600s, via `run_periodic`) faz a
seleção abaixo.

**Seleciona** conversas com estas condições:
- `flow_state.flow = 'valeria_botoes_v2'`;
- `flow_state.node` em `{QA1, QA2, QP1, QP2, VK}`, ou seja, o lead clicou "Quero esse", "Fazer pedido", "Fazer orçamento" ou "Provar antes";
- última mensagem do lead há **mais de 2h**;
- `last_customer_message_at` há **menos de 22h**, para o João ainda pegar a janela de 24h;
- `flow_state.repasse_auto` ausente;
- `leads.human_control` falso.

**Executa:**
- o terminal de handoff do ramo;
- a nota com `Origem do repasse: automático — parado há Xh em <nó>`;
- a mensagem ao lead: "vou deixar o João te chamando por aqui pra seguir com você 🙂" + cartão do João.

**Idempotência:** o UPDATE de `flow_state` é condicional a `node` e a `repasse_auto` ainda
ausente. Duas réplicas do worker não repassam o mesmo lead duas vezes. Cada rodada processa
no máximo 50 conversas, e a leitura é paginada por causa do teto de 1000 do PostgREST.

**Kill switch próprio:** `VALERIA_REPASSE_AUTO_ENABLED`, desligado por default, ligado na
ativação.

Quem só viu a vitrine e não clicou nada **não** é repassado: não demonstrou intenção.

---

## 9. Código

| Arquivo | Mudança |
|---|---|
| `button_flow/valeria_registry_v2.py` (novo) | Dado puro: nós, cards, agrupamentos da tabela, mensagens prontas, tabela de destino do QP2, FAQ por ramo. Reusa `Botao`, `No` e `Terminal` da v1 e adiciona `Card` e `tela="carrossel"`. |
| `button_flow/valeria_registry.py` | Sem mudança de comportamento; só exporta os tipos. |
| `button_flow/valeria_engine.py` | Recebe o registry como parâmetro. Trata `Classificado` (§7.2), `retorno` da FAQ e a regra do QP2. Continua função pura. |
| `button_flow/valeria_runner.py` | Escolhe o registry por `flow_state.flow` (conversa em andamento) ou pelo `flow_id` do perfil (conversa nova). Renderiza o carrossel, a tabela e os botões. Chama o classificador para `Texto`. Monta a nota (§5.3). |
| `button_flow/valeria_tabela.py` (novo) | Monta a tabela atacado e o texto PL a partir de `products` + conteúdo. Função pura sobre a lista de produtos. |
| `button_flow/valeria_classifier.py` (novo), `_llm_comum.py` (novo), `classifier.py` | §7.4 |
| `button_flow/valeria_repasse.py` (novo), `worker/main.py` | §8 |
| `button_flow/config.py` | `valeria_botoes_v2` responde a `VALERIA_BOTOES_ENABLED`. |
| `button_flow/runner.py`, `buffer/processor.py` | O despacho aceita `{v1, v2}` e chama o runner com o flow id. |
| `button_flow/valeria_flow_router.py` | `GET`/`PUT` por `flow_id`. `activate` recebe `flow_id` (v1 ou v2). Validação de card: ≤160 caracteres e ≤2 quebras **depois** de resolver `{preco}`. |
| `whatsapp/base.py`, `meta.py`, `mock_provider.py` | `send_interactive_carousel(to, body, cards)`, com `cards = [{image_url, body, buttons: [(id, rótulo)]}]` e validação de 2–10 cards com o mesmo número de botões. |
| `webhook/meta_parser.py` | Conferir no envio de teste o formato da resposta de quick-reply do carrossel. Se não chegar como `button_reply`, adicionar o caso. |
| Frontend, modal "Fluxo da Valéria" | Seletor de versão (v1/v2) e edição dos corpos de card e das regras. Precisa de leitura do componente atual antes de estimar. |

**Migração de banco:** nenhuma. `valeria_flow_content` já é chaveada por `flow_id`.
**Dados:** corrigir `min_lot` do Microlote PL para `100 un`, pelo modal de Preços.

---

## 10. Ativação e reversão

1. Deploy com `VALERIA_REPASSE_AUTO_ENABLED` desligado. A v2 existe, mas nenhum canal aponta para ela.
2. **Envio de teste** de um carrossel real ao número interno, pelo endpoint de dev. Confere renderização, toque no card e formato do webhook (§9).
3. Rodar um lead de teste pelos dois ramos, cobrindo FAQ, texto livre e kit.
4. "Fluxo da Valéria" → Ativar **v2** no NUMERO VALERIA e ligar `VALERIA_REPASSE_AUTO_ENABLED`.
5. **Conversas da v1 em andamento** continuam na v1, porque `flow_state.flow` é lido primeiro. Conversas novas entram na v2.
6. **Reversão:** Ativar **v1** de novo. É uma troca de perfil, sem deploy. Conversas da v2 em andamento terminam na v2. Para cortar também essas, desligar `VALERIA_BOTOES_ENABLED`.

---

## 11. Testes

| Camada | Cobertura |
|---|---|
| Registry v2 | Todo rótulo ≤ 20 caracteres. Todo card ≤ 160 caracteres e ≤ 2 quebras após resolver `{preco}` com o catálogo de produção (fixture). Todos os cards de um carrossel com o mesmo número de botões. Todo destino existe. Todo nó é alcançável. Lista ≤ 10 linhas. |
| Roteamento | As 4 mensagens prontas vão a VA/VP. Variação e texto qualquer vão ao N0. |
| Motor | Cada botão de cada nó. Regra do QP2 (4 combinações). Ida e volta da FAQ (`retorno`). Cada classe do classificador em cada tipo de nó. 2º `RUIDO` vai ao handoff. Opt-out por frase fixa vence tudo. |
| Tabela | SKU inativo some. Agrupamento correto. Total do PL = 100 × preço. Catálogo vazio dispara a degradação de §6.3. |
| Classificador | Parse tolerante. Id inventado vira `RUIDO`. Timeout e budget estourado viram `RUIDO`. Contabilização em `token_usage`. Os casos do §7.3 com resposta simulada. |
| Repasse de parados | Seleção (6 condições). Idempotência (duas execuções, um repasse). Janela de 22h. Kill switch. |
| Provider | Payload do carrossel conforme a doc da Meta. Validação 2–10 cards. |
| Regressão | Suítes atuais de `button_flow` e da Recuperação verdes. |

Os testes rodam no container da imagem `canastra-api`, com o repo inteiro e sem `.env` (ver a
memória de testes do backend).

---

## 12. Medição

Em 7 dias, repetir o comparativo de 07/10 (artefato acima), com 3 grupos:
- **v2:** leads Meta, a partir da ativação;
- **v1:** 01–06/10;
- **IA antiga:** 24–30/09.

Mesma régua de auditoria e mesmos indicadores de §2, mais:
- % de leads que tocaram no carrossel;
- uso de cada FAQ;
- distribuição das classes do classificador;
- repasses automáticos e quantos deles o João respondeu.

---

## 13. Riscos

| Risco | Mitigação |
|---|---|
| O carrossel não renderiza em algum cliente do WhatsApp ou o número não tem acesso | Envio de teste antes de ativar e degradação automática (§6.3). |
| 3 mensagens de vitrine viram 3 cobranças | Leads de anúncio CTWA têm janela de entrada grátis de 72h. Fora disso, o custo de 2 mensagens a mais é menor que o de 38% de leads bons perdidos. |
| A IA classifica mal | Ela só escolhe entre mensagens fixas, e o pior caso é um nudge ou um repasse. As classes ficam logadas para auditoria (§12). |
| Mostrar preço cedo afasta lead | É a hipótese contrária à medida: com foto e preço, 38% de reação positiva contra 18% só com foto. O teste de 7 dias decide. |
| Consumidor final vindo do anúncio de atacado vê preço de atacado | A tabela é de atacado; com o mínimo de R$500 ele se desqualifica sozinho, e a FAQ e o `N0` continuam com "Pra consumo próprio". Medir em §12. |
| Kit e Microlote PL sem confirmação | O fluxo não afirma esses números (§4). |

---

## 14. Decisões tomadas na implementação (08/10/2026)

- **Chave de card:** `card:<nó>:<id>`. O id sozinho é ambíguo, porque `microlote` existe em VA e em VP. O toque no card continua chegando como `card:<id>`.
- **Conversa em andamento na troca v1 ↔ v2:** fica no fluxo antigo só se o nó não for terminal encerrado e o `flow_state.updated_at` tiver menos de 7 dias.
- **Opt-out:**
  - O motor só aceita a lista exata `FRASES_OPTOUT` e a classe `SAIR`.
  - O classificador tem a saída determinística `pediu_para_sair_v2`. Frases de venda ("não quero receber o kit") não viram opt-out. Marcadores inequívocos ("receber mensagens", "me tira da lista") vencem essa trava.
  - Um `SAIR` do modelo em cortesia ou num "não" isolado é rebaixado para `RUIDO`.
- **Catálogo vazio:** uma mensagem só ("nossa tabela tá sendo atualizada; já chamei o João Brás aqui pra te passar os valores") e o cartão. A vitrine só cai quando o setor não tem preço nenhum: um SKU faltando derruba só o card ou a mensagem 2.
- **Nota de repasse:** a v2 não grava a linha "Nenhuma qualificação por conversa" da v1 (`effects.aplicar(nota_sem_qualificacao=False)`).
- **`T_KIT`:** marca só `Botões: Kit amostra`.
- **Pergunta de preço:**
  - Sem ramo: a lista do N0 sai com texto próprio.
  - Durante a qualificação: o lead recebe a tabela, e o nó atual é mantido.
- **Card antigo do carrossel:** é aceito de qualquer tela do mesmo ramo.
- **Lead que reenvia a mensagem pronta do anúncio no meio do fluxo:** volta para a vitrine.
- **Lead da v1 parado em `T_HUMANO` ou `T_FIM`:** não é reiniciado pela v2.
