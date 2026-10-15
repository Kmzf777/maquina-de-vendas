# Ficha do lead: ações no topo — design

Cartão: 3b686ee7 (BEEINSIDE CANASTRA CRM)

## Problema (palavras do Rafael)

> "na parte de lead, o 'registrar venda', 'salvar alterações' e 'orçamento' deve aparecer no topo da pop up quando se abre a ficha do lead"

Hoje, na ficha do lead (`/leads` → clicar num lead → pop-up `LeadDetailModal`):

- **Salvar alterações** está no cabeçalho, mas só aparece depois que algum campo é editado.
- **Registrar Venda** fica no fim da aba "Dados Gerais"; só se vê rolando.
- **Orçamento** não existe na ficha (só na tela de Conversas, "Fazer Orçamento").

## O que muda

Uma barra de ações logo abaixo do cabeçalho (nome/telefone), acima das abas, visível em todas as abas e fora da área que rola:

| Botão | Visual | Comportamento |
|---|---|---|
| Registrar Venda | verde (igual ao atual) | abre o `SaleCreateModal` do lead (mesmo de hoje) |
| Fazer Orçamento | contorno (padrão de Conversas) | abre o `QuoteCreateModal` com `leadId` do lead e `currentUserEmail`; sem `conversationId` |
| Salvar alterações | preto | **sempre visível** (decisão do Rafael: opção A); desabilitado quando não há edição; "Salvando..." enquanto salva; mesmo `handleSave` de hoje |

- O botão "Salvar alterações" sai do cabeçalho (fica só na barra). O texto de status do endereço no Bling (`lead-bling-endereco-status`) continua no cabeçalho.
- O bloco "Vendas" com o botão "Registrar Venda" no fim da aba "Dados Gerais" é removido (o botão foi para o topo; sem duplicata).
- O `QuoteCreateModal` é envolvido no mesmo `<div onClick={stopPropagation}>` usado pelo `SaleCreateModal`, para cliques nele não fecharem a ficha.
- Temperatura, deletar e fechar continuam no cabeçalho, como hoje.

## Onde

- Repo: `ValerIA` (CRM Next.js em `frontend/`).
- Arquivo: `frontend/src/components/leads/lead-detail-modal.tsx`.
- Testes: `frontend/src/components/leads/lead-detail-modal.test.tsx`.
- Serviço: `crm_crm` (Docker Swarm na VPS). Backend/worker não mudam.

## Como testar em modo teste

No worktree `ValerIA-agente-3b686ee7`, branch `agente/3b686ee7`:

1. Testes de componente (TDD) em `lead-detail-modal.test.tsx`:
   - os 3 botões aparecem na barra do topo ao abrir a ficha, em qualquer aba;
   - "Salvar alterações" desabilitado sem edição e habilitado após editar um campo;
   - "Registrar Venda" abre o modal de venda; "Fazer Orçamento" abre o modal de orçamento com o `leadId` do lead;
   - o botão "Registrar Venda" não existe mais no fim de "Dados Gerais".
2. `npm run type-check`, `npm run test` e `npm run build` no `frontend/` (mesmos passos do CI).
3. Print: subir `npm run dev` local do worktree e printar a ficha aberta, se o login automático do print funcionar nessa origem; se não funcionar, o print visual fica para a etapa de produção (os testes de componente acima são a prova em modo teste).

Nada é gravado: nenhum botão é clicado até o fim (sem salvar lead, sem criar venda/orçamento).

## Como publicar

1. Fluxo do CLAUDE.md do repo (sem PR): `git pull origin master` no branch `agente/3b686ee7` (merge da master remota) + `git push origin agente/3b686ee7:master` (sem force).
2. O push dispara `.github/workflows/deploy.yml`, que roda type-check, testes, build e faz o deploy do CRM na VPS (só o job do CRM roda, pois só `frontend/` mudou).
3. Acompanhar o Action até ficar verde e conferir `docker service ps crm_crm` / `docker service logs crm_crm` na VPS.
4. Voltar atrás: `git revert` do merge em `master` + push (o deploy roda de novo com a versão anterior).

## Como testar em produção

- Abrir `/leads` no CRM de produção, abrir a ficha de um lead existente e printar: barra do topo com os 3 botões, "Salvar alterações" desabilitado. Trocar de aba e printar de novo.
- Abrir "Fazer Orçamento" e "Registrar Venda" só para ver o modal abrir e **fechar sem salvar**.
- Sem nenhuma ação com efeito externo: nenhuma venda, orçamento ou contato criado no Bling, nenhuma mensagem, nenhuma edição de lead salva.

## Fora do escopo

- Painel de Conversas (`crm-perfil-tab`), página `/orcamento`, página de vendas.
- Mudanças nos modais de venda/orçamento em si.
- Listar vendas/orçamentos do lead dentro da ficha.
