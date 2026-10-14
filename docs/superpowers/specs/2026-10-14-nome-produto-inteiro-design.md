# Nome do produto inteiro no orçamento e na venda — design

Cartão: "Aumentar caixa onde aparece o nome dos produtos tanto no momento de fazer orçamento quanto no momento de fazer a venda" (7615bf70, URGENTE).

## Problema

Nas palavras do Rafael: aumentar a caixa onde aparece o nome dos produtos ao fazer orçamento e ao fazer a venda.
O que acontece hoje (confirmado com ele): o nome do produto aparece **cortado com "…"**, tanto na linha do item já escolhido quanto na lista de busca de produtos, e não dá para saber qual item está escolhido.

Causa: os dois painéis (Novo orçamento e Registrar venda) usam o mesmo componente `BlingOrderForm`. O painel tem 42rem (672 px, decisão anterior para não cobrir o chat); as colunas fixas Qtd/Valor/Desc/Total/lixeira ocupam ~360 px, sobrando ~250 px para Produto. O nome usa `truncate` (uma linha só) no botão e na lista; a lista tem a largura do botão (mínimo 280 px).

## O que muda (opção A, escolhida pelo Rafael)

1. **Linha do item:** o nome do produto quebra em quantas linhas precisar e aparece inteiro, sem "…". O botão deixa de ter altura fixa (`h-[34px]` → `min-h-[34px]`, texto com quebra de palavra) e a linha da grade alinha os campos ao topo para não ficar desencontrada quando o nome ocupa 2–3 linhas.
2. **Lista de busca de produtos:** o nome também quebra e aparece inteiro. A lista fica mais larga que a coluna (mínimo ~420 px, limitada à largura da tela), para caber mais texto por linha.
3. Vale para o orçamento e para a venda de uma vez, porque é o mesmo componente. Os painéis **não** mudam de largura (continuam 42rem para não cobrir o chat).

## Onde

- Repo: `ValerIA`, branch `agente/7615bf70` (worktree `ValerIA/.claude/worktrees/agente-7615bf70`).
- Arquivo: `frontend/src/components/sales/bling-order-form.tsx` (botão do produto na linha, grade, `PopoverContent` e item da lista de busca).
- Teste: `frontend/src/components/sales/bling-order-form.test.tsx`.
- Serviço afetado: `crm_crm` (imagem `canastra-crm`). Backend, banco e Bling não mudam.

## Como testar em modo teste

- Teste automatizado (TDD) em `bling-order-form.test.tsx`: com um produto de nome longo selecionado, o nome aparece inteiro no botão sem a classe `truncate` e com quebra de linha; na lista de busca, idem. Rodar a suíte do frontend (`npm test`) + `npm run lint` + `npm run build` no worktree.
- Visual: `next dev` local a partir do worktree (usando o `.env.local` do frontend, sem imprimir o conteúdo), login com o usuário de teste, abrir **Novo orçamento** e **Registrar venda**, escolher um produto de nome longo do catálogo e abrir a lista de busca. Prints dos dois painéis (linha do item + lista aberta). **Não salvar** nada: só abrir, escolher e fechar — a busca de produtos é só leitura no Bling.

## Como publicar

- Seguindo o CLAUDE.md do ValerIA: `git pull origin master` no branch, resolver conflitos se houver, merge em `master` e `git push origin master` (equivalente a `agente/7615bf70:master`). Sem force-push.
- O push dispara o GitHub Actions (`deploy.yml`, job `deploy-crm`): roda lint/testes/build do frontend, gera `canastra-crm:latest` na VPS e atualiza `crm_crm`. Acompanhar o run e conferir `docker service ps crm_crm` / `docker service logs crm_crm`.
- Voltar atrás: `git revert` do commit de merge + push em `master` (novo deploy com o código anterior). Nada de reset/force.

## Como testar em produção

- Abrir https://crm.canastrainteligencia.com com o usuário de teste, abrir os painéis **Novo orçamento** e **Registrar venda**, escolher um produto de nome longo, abrir a lista de busca e tirar print. Fechar sem salvar.
- **Sem ação real com efeito externo:** nenhum orçamento, venda, pedido ou NF é criado no Bling, nenhuma mensagem a cliente, nenhuma cobrança. Só leitura do catálogo.

## Fora do escopo

- Mudar a largura dos painéis laterais (decisão anterior de não cobrir o chat).
- Tooltip ou outras telas que mostram nome de produto (tabela de orçamentos, PDF, resumo, listagem de vendas).
- Qualquer mudança em backend, Bling ou banco.
