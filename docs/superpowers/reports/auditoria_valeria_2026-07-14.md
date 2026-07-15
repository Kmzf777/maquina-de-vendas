# Auditoria de Qualidade — Atendimentos "Valéria" · 14/07/2026

> Fonte: Supabase **produção** (`tshmvxxxyxgctrdkqvam`), read-only. Período: 14/07/2026
> 00h–23h59 (America/Sao_Paulo). Universo: 683 mensagens · 63 conversas · 51 leads.
> Recorte auditado: **24 conversas** com atuação da Valéria (`valeria_inbound` 169 msgs +
> `valeria_outbound` 58 msgs). Cada preço/SCA/lote/frete foi conferido contra a tabela
> `products` (fonte única) e contra as regras em `backend/app/agent/prompts/`.

## Resumo executivo

- **2 falhas ALTAS**, **3 MÉDIAS**, **3 BAIXAS**.
- Preços e SCA citados: factualmente **corretos** em 100% dos casos conferidos.
- 2 "erros" aparentes foram **descartados após verificação** (a Valéria estava certa).

---

## 🔴 ALTAS

### #1 — Thiago Romanini (`2c2f0ea4…`): vazou erro interno de sistema, repetido 2×
Frase (11:29 e 11:31, idêntica):
> "opa, o sistema não encontrou o 'Café Canastra 250g — embalagem do cliente' no catálogo
> de atacado, ele tem as opções de moído ou em grãos, e os tamanhos de 250g, 500g ou 1kg"

É a saída bruta de `calcular_orcamento` (`tools.py:1554`). O prompt de atacado
(`valeria_inbound/atacado.py:80-83`) **proíbe explicitamente** expor "o sistema não achou"
ou nomear o item não encontrado. Violação direta, além de repetição.
Secundário: no handoff cotou "café canastra clássico **em grãos** de 250g … R$25,70" —
R$25,70 é preço de **Private Label**; grãos 250g no atacado é **R$31,70**.

### #2 — Marcelo J. Dummel (`67e8b921…`): prometeu fotos e não enviou nenhuma
Lead pediu textualmente "Quero ver imagens". No handoff a Valéria escreveu
"to te mandando aqui as fotos do nosso portfolio" — **nenhuma imagem foi enviada** em toda a
conversa (sem marcador `[enviar_fotos]`, sem `<image>`). Causa-raiz: o modelo chamou
`enviar_foto_produto` para um produto inexistente (retorno "foto do produto '…' nao
encontrada", `tools.py:1452`), o que marcou `media_tool_used=True` **sem enviar nada** e
pulou a guarda de fotos verbalizadas; o handoff-verbalizado então despachou o texto (com a
promessa) sem foto.

---

## 🟠 MÉDIAS

### #3 — Gilberto Medeiros (`790906f4…`): pergunta tratada como "sem interesse"
> LEAD: "Estou pensando em começar do zero. **Tenho que investir? Se sim não tenho como fazer isso**"
> VALERIA: "sem problema, fico a disposição…" → `[registrar_sem_interesse_atual]`

O lead fez uma pergunta genuína e foi descartado sem resposta. A entrada é enxuta
(Microlote 250g emb. cliente: **50 un / R$27,70**) — informação que poderia mudar a decisão.

### #4 — Roberto (`e0b76720…`): presumiu que "Arthur" é da equipe → desengajou lead quente
> LEAD: "tive uma visita com o Arthur … para fecharmos uma parceria"
> VALERIA: "então você já está em boas mãos com o Arthur … chama ele por lá"

Não há nenhum "Arthur" cadastrado. Se o Arthur for de outra empresa, dispensou um lead B2B
que confirmou que café "faz parte do seu negócio".

### #5 — lead `5564999289099` (`c2216a18…`): reset de contexto no re-trigger da LP
Lead já havia conversado (11/07 e 13/07, recebeu fotos). Ao reenviar o template da LP em
14/07, a Valéria reiniciou a qualificação do zero ("você já tem marca ou lançar do zero?"),
repetindo pergunta já respondida.

---

## 🟡 BAIXAS

- **#6 Fenelon (`925ffc1b…`)**: prova social incoerente ("o café que vendiam") para quem
  ainda não vende café.
- **#7 Noelson (`7793d216…`)**: vazou string de UI "[Foto enviada por você: …]" como mensagem.
- **#8 Green House (`ecdaad5f…`)**: presunção de gênero ("você tá super certa") sem confirmação.

---

## ✅ Falsos alarmes descartados (verificados, Valéria correta)

- **Leila Nobre (CONV 07)**: disse "Nunca fiz cadastro", mas tem **36 msgs anteriores (13
  inbound) desde 08/05** — a afirmação de conversa prévia da Valéria estava correta.
- **Felipe (CONV 24)**: "como você já é nosso cliente" — Felipe **comprou em 26/05**. Correto.
- **Néctar de Minas 75 SCA / R$88,70 (CONV 03)**: bate com o catálogo exatamente.
- **Fretes citados (CONV 03/05)**: há a tool real `calcular_orcamento` (frete no breakdown);
  não são invenção.

---

## Escopo de correção (este ciclo)
Casos #1–#5. Ver spec `docs/superpowers/specs/2026-07-14-valeria-qa-fixes-design.md` e plano
`plans/2026-07-14-valeria-qa-fixes-plan.md`. #6–#8 ficam como backlog de baixa prioridade.
