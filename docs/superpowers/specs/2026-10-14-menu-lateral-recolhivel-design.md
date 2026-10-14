# Menu lateral recolhível para o painel de orçamento/pedido caber ao lado do chat

Cartão: "Aba de preencher orçamento ou pedido tampa o chat e não consigo dar control V nas informações para preencher (POR RECOLHER BARRA LATERAL ESQUERDA DE MENU)" — id a22d0f72.

## Problema

Nas palavras do Rafael: a aba de preencher orçamento ou pedido **tampa o chat** e ele não consegue dar Ctrl+V nas informações. A solução que ele mesmo indica é **recolher a barra lateral esquerda de menu**.

Como está hoje (`origin/master`, já em produção):
- Em /conversas, o painel de venda/orçamento (`components/sales/painel-lateral.tsx`) só vira coluna **ao lado** do chat com tela de no mínimo 1280 px (`QUERY_PAINEL_ACOPLADO` em `app/(authenticated)/conversas/page.tsx`). A conta é: menu 220 + painel 672 + chat ~360.
- Abaixo de 1280 px (notebook 1366 com zoom, 1280×720, janela não maximizada), o painel volta a ficar **por cima** do chat e esconde as mensagens de onde se copiam CPF, endereço e e-mail.
- O menu da esquerda (`components/sidebar.tsx`) tem 220 px fixos e não recolhe.

## O que muda

1. **Menu recolhível (desktop, todas as telas do CRM).**
   - Botão no topo do menu, ao lado do logo, alterna entre:
     - aberto: 220 px, igual a hoje;
     - recolhido: ~56 px, só os ícones.
   - Recolhido, cada item mostra o nome no `title` (dica ao passar o mouse). Os rótulos dos grupos somem e o rodapé mostra só o avatar e o botão de sair.
   - O estado fica salvo no `localStorage` (`valeria:menu-recolhido`) e vale ao recarregar e ao trocar de tela.
   - Mobile (drawer) não muda.
2. **Recolher sozinho ao abrir o painel em /conversas.**
   - Ao abrir **Registrar venda** ou **Novo orçamento** no desktop, o menu recolhe automaticamente.
   - Ao fechar o painel, o menu volta como estava, mas só se foi o painel que o recolheu. Se o vendedor já tinha recolhido à mão, continua recolhido.
   - Se o vendedor reabrir o menu com o painel aberto, a vontade dele prevalece até o painel fechar.
3. **Painel ao lado do chat em telas menores.**
   - Com o menu recolhido, o painel acoplado precisa de 56 + 672 + 360 ≈ 1090 px. O corte de `QUERY_PAINEL_ACOPLADO` passa de 1280 para **1100 px**.
   - Para o chat não ficar espremido quando o menu estiver aberto numa tela entre 1100 e 1280, a regra passa a ser:
     - acoplar quando a tela tem pelo menos 1100 px e o menu está recolhido;
     - ou quando a tela tem pelo menos 1280 px, com qualquer estado do menu.
   - Como o menu recolhe ao abrir o painel, na prática o painel fica ao lado do chat a partir de 1100 px.
   - Trocar entre acoplado e sobreposto com o painel aberto não pode perder o que já foi digitado no formulário. O plano verifica como o painel é montado e garante isso, mantendo o estado no `ContactDetail`/form e não no casco.

## Onde

- Repositório: `ValerIA`, pasta `frontend/`, worktree `ValerIA/.claude/worktrees/agente-a22d0f72`, branch `agente/a22d0f72`.
- Arquivos:
  - `components/sidebar.tsx`: modo recolhido e botão;
  - `components/authenticated-shell.tsx`: dono do estado do menu, exposto por um contexto (ex.: `MenuLateralContext` com `recolhido`, `alternar`, `recolherPeloPainel`/`restaurar`);
  - `app/(authenticated)/conversas/page.tsx`: novo corte e regra de acoplar;
  - `components/conversas/contact-detail.tsx` ou `painel-lateral.tsx`: aviso de abrir/fechar o painel, que já existe para recolher a lista.
- Serviço afetado no deploy: só `crm_crm` (frontend Next.js). Sem backend, banco, Bling ou máquina de vendas.

## Como testar em modo teste

- **Testes automatizados (TDD), no worktree, com a suíte do frontend:**
  - o menu alterna entre aberto e recolhido e lembra o estado no `localStorage`;
  - recolhido, os itens continuam como links com `title`;
  - abrir o painel recolhe o menu e fechar restaura;
  - fechar não restaura se o menu já estava recolhido à mão;
  - a regra de acoplar: 1100 + recolhido acopla, 1100 + aberto não acopla, 1280 + aberto acopla.
- Rodar `npm test`, `npm run lint` e `npm run build` em `frontend/`.
- **Visual:** `next dev` local a partir do worktree, usando o `.env.local` do frontend sem imprimir o conteúdo, e login com o usuário de teste.
  - Prints em /conversas com uma conversa aberta, nas larguras **1180 px** e **1366 px**:
    - menu aberto, sem painel;
    - após clicar em **Novo orçamento**: menu recolhido e painel ao lado do chat, com as mensagens visíveis;
    - após fechar: menu de volta.
  - Print de outra tela (ex.: /dashboard) com o menu recolhido.
  - Selecionar texto no chat com o painel aberto, para confirmar que a seleção funciona.
- **Não salvar nada:** só abrir e fechar os painéis. Nenhum orçamento ou venda é criado.

## Como publicar

- Seguindo o CLAUDE.md do ValerIA:
  - `git pull origin master` no branch e resolver conflitos se houver;
  - merge em `master` e `git push origin master`, sem force-push.
- O push dispara o GitHub Actions (`deploy.yml`, job `deploy-crm`): lint, testes e build do frontend, imagem `canastra-crm:latest` na VPS e atualização de `crm_crm`.
  - Acompanhar o run e conferir `docker service ps crm_crm` e `docker service logs crm_crm`.
- **Voltar atrás:** `git revert` do commit de merge + push em `master`, o que gera novo deploy com o código anterior. Nada de reset ou force.

## Como testar em produção

- Abrir https://crm.canastrainteligencia.com com o usuário de teste e ir a /conversas em janela de ~1180 px e de 1366 px.
  - Abrir **Novo orçamento** e **Registrar venda**: conferir que o menu recolhe e o painel fica ao lado do chat.
  - Fechar sem salvar e conferir que o menu volta.
  - Recolher e abrir o menu à mão em outra tela.
  - Prints de cada passo.
- **Sem ação real com efeito externo:** nenhum orçamento, venda, pedido ou NF no Bling, nenhuma mensagem a cliente, nenhuma cobrança. O único dado gravado é a preferência do menu no `localStorage` do navegador de teste.

## Fora do escopo

- Mudar a largura do painel de venda/orçamento ou o conteúdo dos formulários.
- Telas abaixo de 1100 px: o painel continua sobreposto (sem overlay, como hoje).
- Menu mobile (drawer).
- Recolher a coluna de detalhe do contato ou mudar a lista de conversas além do que já existe.
