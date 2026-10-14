# Botão "Salvar alterações" no cabeçalho do modal de lead (/leads)

Cartão: "Implementar botão "Salvar Alterações" em /leads no cabeçalho do modal" (120939ff).

## Problema

No CRM (`crm.canastrainteligencia.com/leads`), ao abrir um lead e editar um campo da aba
"Dados", o botão "Salvar alteracoes" só aparece no fim da aba, depois de rolar por todos os
campos e pelo bloco "Registrar Venda". O Rafael quer o botão no cabeçalho do modal, para
salvar sem rolar. Confirmado por ele: mover o botão para o cabeçalho, comportamento A.

## O que muda

- Em `frontend/src/components/leads/lead-detail-modal.tsx`, o botão sai do rodapé da aba
  "Dados" e vai para o cabeçalho do modal, no grupo da direita, **antes** do selo de
  temperatura, da lixeira e do ×.
- Comportamento (opção A escolhida pelo Rafael):
  - Só aparece quando há alteração não salva (`dirty`).
  - Aparece em qualquer aba: se editar em "Dados" e trocar de aba, ele continua no topo.
  - Enquanto grava, mostra "Salvando..." e fica desabilitado; depois de gravar, some.
- Texto corrigido para "Salvar alterações" (com acento).
- Estilo: o mesmo botão preto atual (`bg-[#111111]` branco), em tamanho compatível com o
  cabeçalho (altura 32px, como a lixeira e o ×), sem o efeito `hover:scale-110` que
  desalinharia o cabeçalho.
- A lógica de `handleSave` e o `PATCH /api/leads/[id]` não mudam.
- O botão antigo do rodapé da aba é removido (fica só o do topo).

## Onde

- Repo: `ValerIA` (maquina-de-vendas), branch `agente/120939ff`, worktree
  `Agentes AI/ValerIA-agente-120939ff`.
- Arquivo: `frontend/src/components/leads/lead-detail-modal.tsx`.
- Teste novo: `frontend/src/components/leads/lead-detail-modal.test.tsx` (vitest +
  Testing Library, padrão de `lead-timeline.test.tsx`).
- Serviço afetado na VPS: só `crm_crm` (frontend). Backend não muda.

## Como testar em modo teste

1. Testes automáticos (TDD) no worktree, `frontend/`: `npm test` (vitest). Casos:
   - sem edição, não há botão "Salvar alterações";
   - ao editar um campo, o botão aparece dentro do cabeçalho do modal;
   - trocando de aba depois de editar, o botão continua visível;
   - clicar chama `onSave` com só os campos alterados, mostra "Salvando..." e o botão some
     ao terminar;
   - o botão não existe mais no rodapé da aba "Dados".
2. `npm run lint` e `npm run build` no `frontend/` (mesmos passos do GitHub Actions).
3. Teste na tela: `next dev` local no worktree (usa o `.env.local`, que aponta para o
   Supabase de produção). Abro `/leads?lead_id=8c064847-27f3-42a5-82b6-2c0ecc071a1d`
   (lead de teste "teste"), altero o campo Empresa de "teste" para "teste agente", confiro
   o botão no topo, salvo, confiro no banco (SELECT) e depois volto o valor para "teste".
   Só esse lead de teste é tocado.
4. Prints: modal com alteração pendente (botão no topo) e modal depois de salvar.

## Como publicar

Depois do [Liberar produção]:
1. No worktree: `git pull origin master` (resolver conflito, se houver, e rodar os testes de
   novo).
2. `git push origin agente/120939ff:master` (fluxo do CLAUDE.md do repo, sem PR).
3. O GitHub Actions (`deploy.yml`, job `deploy-crm`) detecta mudança em `frontend/`, roda
   lint/testes/build, gera `canastra-crm:latest` na VPS e atualiza `crm_crm`.
4. Acompanhar o run (`gh run watch`) e `docker service ps crm_crm` /
   `docker service logs crm_crm` na VPS.
5. Voltar atrás: `git revert` do commit na master + push (novo deploy pelo Actions). Sem
   force push.

## Como testar em produção

- Abrir `https://crm.canastrainteligencia.com/leads?lead_id=8c064847-27f3-42a5-82b6-2c0ecc071a1d`
  (lead de teste "teste"), repetir a edição de Empresa, salvar pelo botão do topo, conferir
  no banco e reverter o valor.
- Print do modal aberto em produção.
- Nenhuma ação com efeito externo: o PATCH só atualiza a linha do lead no Supabase (sem
  Bling, sem mensagem a cliente, sem cobrança). Só o lead de teste é alterado, e o valor
  original é restaurado.

## Fora do escopo

- Outros modais (criar lead, importar, painel lateral do chat `lead-detail-sidebar`).
- Aviso de "alterações não salvas" ao fechar o modal.
- Tratamento de erro do PATCH (hoje o modal não mostra erro; segue igual).
- Atalho de teclado (Ctrl+S).
- Layout mobile (o modal só abre em telas ≥ 768px).
