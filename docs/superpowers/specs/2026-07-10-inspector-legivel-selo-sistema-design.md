# Inspetor de nó legível + selo "Sistema" para a campanha-espelho

## Problema 1 — inspetor confuso
Ao clicar num nó do builder, o painel lateral mostra só o FORMULÁRIO de edição; o
operador não tem uma frase que diga o que o nó faz com a configuração atual.

**Solução:** helper puro `describeNode(type, config)` em
`cadence-flow/describe-node.ts` — uma sentença em linguagem de operador por tipo
(gatilho com dias/stage/keywords; envio de template com nome+idioma+reação à
resposta; texto livre com prévia da mensagem; espera com dias e janela de horário;
condição com a regra e a menção aos ramos SIM/NÃO; ação com o rótulo de
ACTION_LABELS; fim com o rótulo). Renderizada num cartão destacado "O QUE ESTE NÓ
FAZ" no topo do corpo do inspetor, calculada do RASCUNHO (atualiza ao vivo enquanto o
operador edita, antes de salvar). Testes vitest cobrem os sete tipos e as variações
principais de config.

## Problema 2 — espelho do motor exibe "Rascunho"
`status='draft'` é proteção de backend (imutável — engine só executa `active`), mas o
rótulo "Rascunho" sugere fluxo inacabado.

**Solução (só apresentação):** onde o status é exibido, o UUID de sistema
(`isSystemCampaign`) troca o selo por **"Sistema"** em âmbar/laranja (coerente com o
selo "MOTOR DA VALÉRIA" do builder): `cadence-card.tsx` (lista de cadências),
`StatusBadge` da visão geral em `campanhas/page.tsx` e o chip de status do cabeçalho
do builder (`cadence-flow/index.tsx`). Campanhas convencionais permanecem idênticas.
Backend inalterado.

## Testes
vitest: `describe-node.test.ts` (7 tipos + variações); suíte completa + type-check +
build. Smoke pós-deploy: CRM redeployado e rotas gated.
