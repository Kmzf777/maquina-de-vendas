# Auditoria Responsiva — /conversas e /campanhas (disparos)

**Data:** 2026-07-06
**Escopo:** análise a nível de código (sem browser). Viewport-alvo: 360–430px.
**Status:** proposta — nenhum arquivo-fonte foi editado.
**Breakpoint do projeto:** só existe `md:` (768px). Não há `sm:` no shell; abaixo de 768px é "mobile", acima é "desktop".

---

## Resumo executivo

O `/conversas` já tem uma máquina de estados mobile decente (`mobileView: "list" | "chat" | "contact"` em `conversas/page.tsx:48`, com paths reais para cada painel), então a navegação lista→chat→contato funciona. Os problemas ali são de **densidade da barra superior do chat** (5 controles numa linha só, sem colapso), **touch targets pequenos** e detalhes de overflow — desconforto, não quebra total.

O `/campanhas` na aba **disparos** é onde está o "horroroso": os componentes foram escritos **desktop-first com grids de colunas fixas sem variante mobile** (`grid grid-cols-2`, `grid-cols-5`, `grid-cols-[220px_1fr]`), **paddings fixos `px-8`**, um **header de página com 3 botões + título `text-[32px]`** que não colapsa, e **modais wizard densos** (create-broadcast com grid de filtro+tabela lado a lado). A `BroadcastList` renderiza cards em 2 colunas fixas em qualquer largura, e o header da página de campanhas empilha 3 botões que estouram 360px. Estes são os que dão a sensação de "nada funcional".

Prioridade: os quick wins de `/campanhas` (grids→`grid-cols-1 md:grid-cols-N`, `px-8`→`px-4 md:px-8`, header wrap) resolvem ~70% da percepção com baixo risco.

---

## Achados — /conversas

### C1. Barra do chat superlotada no mobile — ALTO
`components/conversas/chat-header.tsx:84-229`
A `ChatHeader` põe numa única `flex` row, sem wrap: back button + avatar + nome (`flex-1`) + botão "Valéria IA · Ativa" (`px-3`, texto longo) + botão "Finalizar Conversa" + menu "...". Em 360px, com nome + o pill "Valéria IA · Ativa" (linha 134, texto não abreviado no mobile) + "Finalizar Conversa" (o label some via `hidden sm:inline` na linha 158, mas o botão do IA **não** tem tratamento equivalente), o `flex-1 min-w-0` do nome é espremido a quase nada. O nome trunca (ok) mas os controles ficam colados, sem respiro. O botão de IA nunca vira ícone-only.
**Severidade:** alto (usabilidade — o header é a área mais tocada).

### C2. Touch targets abaixo de 44px — ALTO
`chat-header.tsx:88-96` (back, `w-8 h-8` = 32px), `chat-header.tsx:169-180` (menu "...", `w-8 h-8`), `chat-view.tsx:738-760` (gravar áudio / anexar, ícones `w-5 h-5` com só `pb-[9px]` de área), `chat-list.tsx` linhas de conversa são grandes (ok), mas os botões de ação do input e header ficam em ~32px. Diretriz de toque é ≥44px.
**Severidade:** alto (erros de toque no dedo).

### C3. Input de mensagem — botões apertados em 360px — MÉDIO
`chat-view.tsx:721-780`
A barra de input é `flex gap-2` com: mic + anexo + `textarea flex-1` + enviar. Em 360px cabe, mas com `gap-2` e 3 botões o textarea fica estreito. O `QuickReplyMenu` (linha 722) é posicionado `relative`/absolute dentro dessa row — conferir se não estoura a viewport à direita no mobile (menu de largura fixa).
**Severidade:** médio.

### C4. Indicador de "conversa irmã" com muitos canais — MÉDIO
`chat-view.tsx:556-568`
Quando há vários canais irmãos, renderiza `flex items-center gap-2` de botões "Ver conversa" por canal, com `ml-auto`. Sem wrap; 3+ canais empurram para fora à direita no mobile.
**Severidade:** médio (caso raro).

### C5. ChatList tabs — setas de scroll só no desktop — BAIXO
`chat-list.tsx:382-451`
As setas de scroll das tabs são `hidden md:flex`. No mobile o container é `overflow-x-auto` com scrollbar escondida (`[&::-webkit-scrollbar]:hidden`) — funciona via swipe, mas **sem affordance visual** de que há mais tabs à direita. Aceitável, mas pode confundir.
**Severidade:** baixo.

### C6. ContactDetail — largura e back no mobile — BAIXO (já tratado)
`contact-detail.tsx:146` usa `w-full md:w-[320px]` e `contact-detail.tsx:148` tem um header `md:hidden` com back. Já responsivo. Verificar apenas que o conteúdo interno das tabs (perfil/notas/campanhas/métricas) não tem grids fixos — não auditado em profundidade aqui; recomenda-se passada rápida.
**Severidade:** baixo.

**Observação positiva:** `conversas/page.tsx:507-567` implementa corretamente 3 divs mobile mutuamente exclusivos + `hidden md:flex` para desktop. A arquitetura de navegação mobile está certa — não precisa de refactor, só polimento do header.

---

## Achados — /campanhas (aba disparos e correlatos)

### D1. Header da página de campanhas estoura no mobile — CRÍTICO
`app/(authenticated)/campanhas/page.tsx:121-148`
`<div className="... px-8 py-5 flex items-center justify-between">` com título `text-[32px]` (linha 123) à esquerda e **3 botões** ("+ Disparo Rápido", "+ Disparo", "+ Cadencia") num `flex gap-2` à direita (linha 128). Sem `flex-wrap`, sem colapso. Em 360px, título grande + 3 botões lado a lado **não cabem** — os botões saem da tela ou espremem o título. `px-8` (32px cada lado) come 64px de 360.
**Severidade:** crítico. É a primeira coisa que o usuário vê na tela.

### D2. Tab-nav com `px-8` fixo — ALTO
`campanhas/page.tsx:151-170`
A navegação de abas (`Visão Geral / Disparos / Cadências / Templates`) usa `px-8` fixo e `flex` sem scroll. Em 360px, 4 abas com `px-4 py-3` cada podem estourar; sem `overflow-x-auto`.
**Severidade:** alto.

### D3. BroadcastList — grid de 2 colunas fixo + filtros em linha única — CRÍTICO
`components/campaigns/broadcast-list.tsx:91` → `grid grid-cols-2 gap-4` **sem breakpoint**. Cada `BroadcastCard` tem grid interno de 4 stats (`broadcast-card.tsx:69` `grid-cols-4`). Dois cards densos lado a lado em 360px = conteúdo ilegível/cortado.
Além disso `broadcast-list.tsx:65-86`: busca `w-64` (256px fixo) + 4 botões de filtro num `flex items-center gap-3` sem wrap → estoura 360px.
**Severidade:** crítico.

### D4. Página de detalhe do disparo — header + grids desktop-first — CRÍTICO
`components/campaigns/broadcast-detail.tsx`
- **Header** (`:389-496`): `px-8 py-5 flex justify-between`, título `text-[32px]` + breadcrumb "← Campanhas / nome / status" à esquerda, **e até 3 botões de ação** à direita (Iniciar/Agendar/Excluir em draft; Reagendar/Cancelar agendamento em scheduled). Nada colapsa nem quebra linha. Estoura fortemente em mobile.
- **Cards de métrica** (`:548`): `grid grid-cols-5 gap-4` fixo, com números `text-[36px]` (`:555`). 5 colunas em 360px = ~50px por card, número de 36px não cabe.
- **Reply metrics** (`:569`): `grid grid-cols-2` fixo (ok-ish, mas com `text-[36px]`).
- **Schedule picker inline** (`:499-543`): `flex items-end gap-4 flex-wrap` — tem `flex-wrap`, então esse está OK.
- **Tabela de leads** (`:660`): `overflow-x-auto` presente (bom), mas 6-7 colunas com `px-5` empurram scroll horizontal longo; sem versão card. Aceitável via scroll, mas não ideal.
**Severidade:** crítico (header + métricas).

### D5. CreateBroadcastModal — wizard denso, grid filtro+tabela lado a lado — ALTO
`components/campaigns/create-broadcast-modal.tsx`
- Modal: `max-w-2xl max-h-[90vh]` com `p-4` externo (`:583-584`) — o `p-4` dá margem, mas `max-w-2xl` em `w-full` fica ok no mobile (limitado pela viewport). O corpo tem `overflow-y-auto` (`:640`) — bom.
- **Progress bar de 6 steps** (`:598-637`): 6 círculos + labels `text-[10px]` numa `flex` com conectores. Em 360px, 6 labels ("Configuração", "Agendamento"...) `whitespace-nowrap` (`:619`) espremem/estouram. Provável overflow ou labels ilegíveis.
- **Step 3 (Leads)** (`:831`): `grid grid-cols-[220px_1fr] gap-4` **fixo** — painel de filtro de 220px + tabela lado a lado. Em 360px sobram ~120px para a tabela. Quebra. Precisa empilhar (`grid-cols-1`) no mobile, idealmente filtro colapsável.
- Tabela de leads interna (`:881`) tem `max-h-[320px]` overflow-y — ok verticalmente.
**Severidade:** alto (step 3 é inutilizável no mobile).

### D6. QuickSendModal — layout ok, detalhes de wrap — MÉDIO
`components/campaigns/quick-send-modal.tsx:303-304`
Modal `max-w-lg max-h-[85vh] overflow-y-auto` — responsivo no essencial. Linhas de telefone (`:425`) são `flex gap-2` com input `flex-1` + "Salvar" + "×" — cabe. "Números salvos" usa `flex flex-wrap` (`:467`) — bom. Preview interativo (`:393`) usa inputs inline `size=...` que podem forçar largura, mas o container tem `whitespace-pre-wrap`. Menor risco.
**Severidade:** médio.

### D7. Modal "Nova Cadência" — ok — BAIXO
`campanhas/page.tsx:271-361`: `max-w-lg`, campos empilhados (`space-y-4`), footer `flex justify-end gap-2`. Responsivo. Sem achado relevante.

### D8. Mini-listas da Visão Geral — MÉDIO
`campanhas/page.tsx:186-236`
"Disparos Recentes": cada linha é `flex items-center gap-4` com `StatusBadge` + nome (`flex-1 truncate`) + barra de progresso `w-24` (96px) fixa + `%`. Em 360px, badge + barra de 96px + gap-4 deixam pouco para o nome, mas ele trunca (ok). Barra `w-24` é grande demais para mobile; considerar `w-16 sm:w-24`. Menor.
**Severidade:** médio-baixo.

---

## Propostas de correção

### Quick wins (baixo risco, alto impacto — fazer primeiro)

**QW1 — Header de /campanhas colapsável** (`campanhas/page.tsx:121-148`)
- Trocar `px-8 py-5` por `px-4 md:px-8 py-4 md:py-5`.
- Container: `flex flex-col gap-3 md:flex-row md:items-center md:justify-between`.
- Título: `text-[24px] md:text-[32px]`.
- Grupo de botões: `flex flex-wrap gap-2` e nos botões reduzir texto no mobile ou permitir wrap; alternativamente esconder rótulos longos: manter "+ Disparo" e agrupar "Rápido"/"Cadência" num menu "..." no mobile (refactor menor — ver R1).

**QW2 — Tab-nav de campanhas com scroll** (`campanhas/page.tsx:151-170`)
- Wrapper: `px-4 md:px-8` e `overflow-x-auto [&::-webkit-scrollbar]:hidden`.
- `div.flex` interno: adicionar `w-max` para permitir scroll horizontal das 4 abas.

**QW3 — BroadcastList responsiva** (`broadcast-list.tsx:91` e `:65`)
- Grid de cards: `grid grid-cols-1 md:grid-cols-2 gap-4`.
- Barra de filtros: container `flex flex-col gap-3 md:flex-row md:items-center`; busca `w-full md:w-64`; filtros `flex flex-wrap gap-1`.

**QW4 — Header do detalhe do disparo** (`broadcast-detail.tsx:389` e `:414`)
- `px-4 md:px-8 py-4 md:py-5`; container principal `flex flex-col gap-3 md:flex-row md:items-center md:justify-between`.
- Título `text-[22px] md:text-[32px]`.
- Grupo de botões de ação: `flex flex-wrap gap-2`.

**QW5 — Grids de métrica do detalhe** (`broadcast-detail.tsx:548` e `:569`)
- Métricas: `grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 md:gap-4` (obs: sem `sm` no shell hoje — usar `grid-cols-2 md:grid-cols-5`).
- Reduzir número: `text-[28px] md:text-[36px]`.
- Reply metrics `grid-cols-2` já ok; só ajustar fonte.

**QW6 — Padding do conteúdo já corrigido em campanhas/page.tsx:173** (`px-4 md:px-8 py-4 md:py-8`) — bom, replicar esse padrão em `broadcast-detail.tsx:546` (`px-8 py-6` → `px-4 md:px-8 py-4 md:py-6`).

**QW7 — Touch targets do chat** (`chat-header.tsx:88,169`; `chat-view.tsx:738,752`)
- Back e menu "...": `w-9 h-9` mínimo, idealmente `w-10 h-10` com o ícone centralizado. Mic/anexo: aumentar área clicável (`p-2` em vez de `pb-[9px]`).

### Refactors maiores (mais esforço)

**R1 — ChatHeader adaptativo no mobile** (`chat-header.tsx:84-229`)
- No mobile (`< md`), colapsar o botão "Valéria IA · Ativa" para ícone-only (só a bolinha de status + tooltip), como já se faz com "Finalizar Conversa" (`hidden sm:inline`). Ou mover Valéria IA e Finalizar para dentro do menu "..." no mobile, deixando no header apenas: back, avatar+nome, menu "...". Isso libera espaço e resolve C1.
- Padrão sugerido: manter os toggles críticos no header em desktop; no mobile, `md:inline-flex hidden` nos botões de texto e concentrar ações no dropdown.

**R2 — CreateBroadcastModal mobile** (`create-broadcast-modal.tsx`)
- **Progress bar** (`:598`): no mobile mostrar só "Passo N de 6 — <label atual>" em vez dos 6 círculos; manter os círculos `hidden md:flex`. Resolve o overflow dos 6 labels.
- **Step 3 grid** (`:831`): `grid grid-cols-1 md:grid-cols-[220px_1fr] gap-4`. No mobile, transformar o `LeadFilterPanel` num bloco colapsável (accordion "Filtros") acima da tabela, e a tabela ocupa 100% da largura. Remover `border-r` no mobile.
- Tabela de leads: manter; já tem overflow controlado.

**R3 — Tabela de leads do detalhe → cards no mobile** (`broadcast-detail.tsx:660-720+`)
- Opcional. Manter `overflow-x-auto` como fallback (já existe). Para experiência melhor, `hidden md:block` na `<table>` e um `md:hidden` com lista de cards (nome + telefone + status badge + timestamps empilhados). Baixa prioridade — o scroll horizontal já não quebra.

**R4 — Passada nas tabs internas do ContactDetail**
- Auditar `tabs/crm-perfil-tab.tsx`, `crm-metricas-tab.tsx` etc. em busca de `grid-cols-N` fixos e larguras px. Não coberto em detalhe nesta auditoria.

---

## Priorização final

| # | Item | Área | Severidade | Esforço |
|---|------|------|-----------|---------|
| QW1 | Header campanhas colapsa | disparos | crítico | baixo |
| QW3 | BroadcastList grid + filtros | disparos | crítico | baixo |
| QW4 | Header detalhe disparo | disparos | crítico | baixo |
| QW5 | Grids de métrica | disparos | crítico | baixo |
| QW2 | Tab-nav scroll | disparos | alto | baixo |
| R2 | Wizard mobile (progress + step 3) | disparos | alto | médio |
| R1 | ChatHeader adaptativo | conversas | alto | médio |
| QW7 | Touch targets chat | conversas | alto | baixo |
| QW6 | Padding detalhe | disparos | médio | baixo |
| R3 | Tabela→cards | disparos | médio | médio |
| C3/C4 | Input/sibling wrap | conversas | médio | baixo |

**Nota de execução:** o projeto só tem breakpoint `md:` (768px) no shell. Ao implementar, usar `md:` como divisor mobile/desktop; evitar `sm:` a menos que se defina no Tailwind. O `AuthenticatedShell` já reserva `pt-14` para a top bar mobile — as páginas não precisam duplicar esse espaçamento.
