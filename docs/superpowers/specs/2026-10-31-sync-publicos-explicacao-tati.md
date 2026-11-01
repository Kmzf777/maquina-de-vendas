# Tati: os públicos de Private Label e Atacado agora se atualizam sozinhos

## O que muda

Você não precisa mais subir a planilha. Todo dia, à 01:00, o sistema atualiza estes 4 públicos com quem comprou nos últimos 12 meses:

- Meta: **Lista | Private Label** e **Lista | Atacado | v3**
- Google: **Lista Bling Private Label** e **Lista Bling Atacado**

Os nomes e IDs continuam os mesmos e nenhuma campanha precisa ser mexida.

## Por que o sistema só acrescenta (e não substitui)

Hoje os públicos do Meta têm cerca de **1.000 pessoas**, por causa das planilhas que você já subiu. Pela regra nova (comprou nos últimos 12 meses), a lista atual tem:

| Público | Pessoas |
|---|---|
| Private Label | 78 |
| Atacado | 412 |

Se o sistema **substituísse** o conteúdo, o público de Private Label cairia de ~1.000 para 78 de uma vez. Um público pequeno assim costuma travar ou encarecer a entrega das campanhas que já estão rodando com ele.

Por isso, o sistema faz assim:

1. **Acrescenta** todo dia os compradores atuais. Quem comprou ontem entra hoje à noite.
2. **Tira só quem ele mesmo colocou** e deixou de se encaixar, por exemplo quem passou de 12 meses sem comprar.
3. **Não mexe** no que você subiu à mão. Isso continua lá, do jeito que está hoje.

Na prática, o público só cresce na estreia e nenhuma campanha perde alcance.

## O que fica com você

- **Base antiga das planilhas:** continua dentro dos públicos. Se um dia você quiser que eles tenham **só** os compradores dos últimos 12 meses, avise o Rafael. Dá para fazer uma limpeza única, num momento que não atrapalhe as campanhas.
- **Quem entra em cada lista:**
  - **Private Label:** quem tem negócio num funil de Private Label, a tag "Marca Própria", compra de fotolito ou está marcado como Private Label no CRM.
  - **Atacado:** quem tem negócio num funil de Atacado, a tag "Revenda" ou está marcado como Atacado no CRM. Também entra o comprador com CNPJ que não caiu em nenhuma das duas.
  - **Nas duas:** quem se encaixa nas duas regras.
  - **Fica fora:** o consumidor final (CPF sem classificação).
- **Dados enviados:** e-mail, celular (nunca telefone fixo), nome, cidade e CEP, sempre criptografados (hash), como o Meta e o Google exigem. No Meta vai também quanto a pessoa comprou em 12 meses, porque os públicos são "com base em valor".
