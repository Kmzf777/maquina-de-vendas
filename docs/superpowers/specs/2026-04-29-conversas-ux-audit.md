# Auditoria UX/UI — Página `/conversas` (CRM Máquina de Vendas Canastra)

**Data:** 2026-04-29
**Escopo:** `/home/rafael/maquinadevendas/frontend/src/app/(authenticated)/conversas/page.tsx` e árvore de componentes em `frontend/src/components/conversas/`.
**Sistema de design de referência:** `/home/rafael/maquinadevendas/DESIGN.md` (Intercom-inspired — warm cream `#faf9f6`, off-black `#111111`, Fin Orange `#ff5600` apenas para IA/marca, oat border `#dedbd6`, sem sombras, raio 4/6/8 px).
**Persona:** Vendedor que passa o dia inteiro nesta tela, gerenciando dezenas de WhatsApp simultâneos, dividindo atenção com IA Valéria, dentro da janela de 24h da Meta.

---

## 1. Resumo Executivo

A página de conversas está funcional, mas é arquetipicamente um "ciborg": o layout segue uma tríade lista/chat/detalhes saudável, porém a hierarquia visual interna está achatada — tudo parece ter o mesmo peso. Os principais sintomas são:

1. **Não existe contagem de não-lidas** no schema (`Conversation` em `frontend/src/lib/types.ts:Conversation`) — a queixa do cliente está correta e tem raiz de produto, não só de UI: o backend não retorna `unread_count`.
2. **Indicador de janela 24h** está espalhado em três lugares (lista, header, chat), com vocabulários e cores diferentes (verde/âmbar/vermelho com emojis ⏳⏱🔒🔴). Falta um único componente coeso.
3. **Datas e horas usam três regras diferentes** (lista: hoje=hora, ontem="Ontem", outros="dd/MM"; header: nada; bolha: "HH:mm"; separador: "Hoje/Ontem/dia de mês"), com tipografia minúscula e baixo contraste (`text-[#9b9b98]`).
4. **Toggle Pausar/Ativar IA** é a ação mais frequente do vendedor mas mora **escondido na sidebar direita** (3º painel) — em mobile/laptop pequeno isso quase obriga a abrir o drawer.
5. **Conversa selecionada vira um cartão preto sólido** (`bg-[#111111]`) na lista — destrói legibilidade dos meta-dados secundários (telefone, prévia, status da IA), todos rebaixados a `text-white/60`.

A boa notícia: o stack já está no design system correto (warm cream, oat borders, raios 4/6/8). O trabalho aqui é de **redistribuição de peso, consolidação de affordances repetidas e adicionar 2-3 indicadores de estado que faltam de fato**.

---

## 2. Mapa do Código

### 2.1 Estrutura de arquivos

```
frontend/src/app/(authenticated)/conversas/
└── page.tsx                                          # Container, fetch, deep-link, Realtime

frontend/src/components/conversas/
├── chat-list.tsx                                     # Coluna esquerda (320 px): canal, busca, tabs, cards
├── chat-view.tsx                                     # Coluna central: header + mensagens + input + banner janela
├── chat-header.tsx                                   # Avatar + nome + tags + badge canal + countdown 24h
├── message-list.tsx                                  # Lista virtualizada com scroll, separator, "novas" badge
├── message-bubble.tsx                                # Bolha individual + senderBadge ("IA"/"Vendedor")
├── day-separator.tsx                                 # "Hoje", "Ontem", "23 de abril"
├── event-card.tsx                                    # Eventos sistêmicos (handoff, stage change, etc.)
├── window-reactivate-panel.tsx                       # Painel rodapé p/ template + cadência (janela fechada)
└── contact-detail.tsx                                # Sidebar direita: lead info, IA toggle, deals, tags
```

Bibliotecas: Next.js App Router + React Server/Client Components, Tailwind via classes arbitrárias `[#hex]` (não usa shadcn nem Radix nesta página), Supabase Realtime (`useRealtimeMessages` em `frontend/src/hooks/use-realtime-messages.ts`).

### 2.2 Backend — campos disponíveis hoje vs. faltantes

`backend/app/conversations/router.py` expõe **só** o `PATCH /api/conversations/{id}/agent` para `ai_enabled` e `agent_profile_id`. A listagem é feita pelo Next.js em `frontend/src/app/api/conversations/route.ts` consultando Supabase direto. Tipo `Conversation` (`frontend/src/lib/types.ts`):

```ts
interface Conversation {
  id, lead_id, channel_id, stage, status,
  last_msg_at, created_at,
  agent_profile_id, ai_enabled,
  last_message_text,
  leads?: Lead, channels?, agent_profiles?
}
```

**Campos que a UI precisa e que NÃO existem hoje:**

| Campo | Para quê | Fonte sugerida |
|---|---|---|
| `unread_count` | Bolinha verde + contador na lista | Coluna nova em `conversations`, incrementada no `buffer/processor.py` quando `role='user'` chega; zerada quando o vendedor abre a conversa |
| `last_message_role` ou `last_message_from` | Saber se a última mensagem é do lead (=> requer atenção) ou nossa | Já dá pra inferir comparando `last_msg_at` vs `lead.last_customer_message_at`, mas formaliza |
| `last_seen_at` (do vendedor por conv) | Calcular não-lidas e "marcar como lida" | Tabela `conversation_reads(user_id, conversation_id, seen_at)` |
| `assigned_to` (no `Conversation`) | Hoje só existe em `lead.assigned_to`, e não é exibido | Seguir cadeia `conv → lead.assigned_to`, exibir avatar do dono na lista |
| `delivery_status` por mensagem | Tick simples/duplo/azul (entregue/lida) | Já existe webhook Meta para `sent`/`delivered`/`read`; persistir em `messages.delivery_status` |
| `whatsapp_window_expires_at` calculado e indexado | Evita recalcular no cliente em cada conversa | Já é derivável de `lead.last_customer_message_at`; OK manter no cliente, mas exposição no payload sem aninhar via `leads` simplificaria |

Sem `unread_count` no payload, **qualquer "bolinha verde + número" será um placeholder visual**. Esse é o gargalo número um: corrigir produto, não só design.

---

## 3. Análise Crítica por Categoria

### 3.1 Hierarquia visual & densidade

| # | Problema | Local |
|---|---|---|
| H1 | **Coluna esquerda achata 4 informações sobrepostas por card** (nome, hora, badge canal, telefone, prévia, IA dot). Tudo `text-[12-13px]`, mesma cor `#7b7b78`. Cérebro do vendedor não tem ponto focal. | `chat-list.tsx` (cards do listing — bloco que renderiza `displayName`, `formatTime`, `channel.name`, `lead.phone`, `last_message_text`, `IA ativa/pausada`) |
| H2 | **Card ativo é preto sólido** — vira buraco visual e força o olho a re-aprender hierarquia interna invertida (`text-white/60` para tudo secundário). Falta uma alternativa "selecionado" que não destrua densidade. | `chat-list.tsx` — `isActive ? "bg-[#111111] text-white"` |
| H3 | **Avatares coloridos por stage** competem com badges de stage e com tags coloridas. Três sistemas de cor concorrentes ocupando o mesmo card. | `chat-list.tsx:getStageColor`, `chat-header.tsx:getStageColor` (mapas duplicados, valores divergentes p/ `exportacao`) |
| H4 | **Badge de canal** repetido em três lugares (lista, header, e implícito no select de canais). Em janela apertada vira ruído. | `chat-list.tsx`, `chat-header.tsx` |
| H5 | **Sidebar direita (`contact-detail.tsx`) tem ~6 seções empilhadas** sem separadores visuais nem grupos colapsáveis: AI control, Stage info, Lead fields editáveis (CNPJ, razão social, endereço…), Tags, Deals, Notes. Vendedor rola muito. | `contact-detail.tsx` (1)-(4) |
| H6 | **Spacing inconsistente**: `px-3 py-3`, `px-4 py-3`, `px-2 py-1`, `py-1.5`, `py-2` se alternam. DESIGN.md pede escala 8/10/12/14/16/20/24… — nem sempre é seguido. | múltiplos |

### 3.2 Indicadores de estado (a queixa central do cliente)

| # | Problema | Local |
|---|---|---|
| S1 | **Não há indicador de "mensagem nova"** na lista. Dot verde + contador sugerido pelo cliente é correto e não está implementado. Hoje a única pista é que a conversa "subiu" porque `last_msg_at` mudou — mas com 50 conversas isso é ilegível. Falta `unread_count` no schema. | `chat-list.tsx` — não existe; backend não fornece |
| S2 | **Não há diferença visual entre "nova mensagem do lead" e "última msg fui eu"**. Vendedor tem que ler o `last_message_text` toda vez. | `chat-list.tsx` — `last_message_text` é renderizado igual nas duas direções |
| S3 | **Janela 24h tem 4 representações diferentes** numa mesma página: emoji ⏳/⏱/🔒 no header (`chat-header.tsx`), emoji ⏱/🔴 na lista (`chat-list.tsx`), banner amarelo+laranja no chat-view (`chat-view.tsx`), e botão "Reativar conversa" mais painel inline. Sem componente único, vocabulário inconsistente ("Janela", "Janela fechada", "Janela de 24h encerrada"). | `chat-header.tsx`, `chat-list.tsx`, `chat-view.tsx`, `window-reactivate-panel.tsx` |
| S4 | **Não há tooltip/explicação** do que é a janela de 24h para o vendedor que não conhece a regra Meta — só emojis e "Janela". | `chat-header.tsx` |
| S5 | **IA ativa/pausada** mostrado em 3 lugares com 3 visuais: dot 1.5px na lista (`chat-list.tsx`), dot 2px + badge na bolha (`message-bubble.tsx senderBadge`), dot+texto+toggle no contact-detail (`contact-detail.tsx`). Toggle pra alternar mora só no contact-detail — toda vez que vendedor quer pausar, precisa abrir o painel direito. | `chat-list.tsx`, `message-bubble.tsx`, `contact-detail.tsx` |
| S6 | **Status do lead/stage** (secretaria, atacado, private_label, exportacao, consumo) só aparece como cor de avatar — sem rótulo na lista. Vendedor precisa abrir a conversa pra ler o stage no contact-detail. | `chat-list.tsx:getStageColor` (sem label adjacente) |
| S7 | **Atribuição (`lead.assigned_to`)** — não é mostrada em lugar nenhum da lista. Tab "Pessoal" na verdade filtra `!conv.leads` (`chat-list.tsx` linha do filtro `pessoal`), o que é diferente de "minhas". | `chat-list.tsx` filtro por tab |
| S8 | **Status de envio da mensagem** está reduzido a `opacity-70` e texto "Enviando..." (`message-bubble.tsx`). Não há tick simples (enviado), tick duplo (entregue), tick azul (lido). Em volume alto, vendedor não sabe o que pegou. | `message-bubble.tsx` |
| S9 | **Online/offline** do lead — não existe (Meta não fornece presence em todos os providers, mas Evolution sim em vários casos). Pode ser N/A intencional, mas vale reconhecer. | — |

### 3.3 Tipografia & legibilidade

| # | Problema | Local |
|---|---|---|
| T1 | **Datas/horas: três sistemas diferentes** sem unificação em `lib/datetime.ts`. (a) `chat-list.tsx` tem `formatTime` próprio (hoje=HH:mm, ontem="Ontem", senão dd/MM); (b) `message-bubble.tsx` tem outro `formatTime` (sempre HH:mm); (c) `day-separator.tsx` tem `formatDayLabel` (Hoje/Ontem/"23 de abril"); (d) `event-card.tsx` provavelmente um quarto. Todos ignoram fuso/locale com edge-cases (ex: "ontem" às 23:59 em conversa atrasada vira só dia/mês). | `chat-list.tsx:formatTime`, `message-bubble.tsx:formatTime`, `day-separator.tsx`, `event-card.tsx` |
| T2 | **Hora na bolha é cinza claríssimo** (`text-[#7b7b78]` em bolha branca, `text-white/50` em bolha preta) — em ambientes claros ou em laptop sem brilho fica abaixo do mínimo de contraste (3:1 para texto não-essencial). | `message-bubble.tsx` |
| T3 | **`text-[10px]` e `text-[11px]` em vários badges** — abaixo da escala recomendada (DESIGN.md fala em 12px mono uppercase para labels). Aparece em senderBadge, tags, day-separator. | `message-bubble.tsx`, `chat-header.tsx`, `day-separator.tsx` |
| T4 | **DaySeparator usa pílula `bg-[#f0ede8]`** — uma cor warm que não é nem `#faf9f6` (canvas) nem `#dedbd6` (border), inventada localmente. | `day-separator.tsx` |
| T5 | **Headings sem `tracking-tight` ou `letterSpacing` negativo**. `chat-header.tsx` h2 está `text-[14px] font-medium truncate` — pra DESIGN.md, mesmo nomes de lead deveriam ter tratamento tipográfico. | `chat-header.tsx` |
| T6 | **Telefone do lead na lista é `text-[12px]`** mesmo nível visual que nome — não tem hierarquia. | `chat-list.tsx` |

### 3.4 Affordances & ações

| # | Problema | Local |
|---|---|---|
| A1 | **Pausar/Ativar IA é a ação #1 do vendedor** e está no painel direito que muitas vezes está fechado. Deveria estar no `ChatHeader`, sempre visível, idealmente com **toggle switch** ao lado do nome do agent profile. | `contact-detail.tsx` (toggle); `chat-header.tsx` deveria hospedar |
| A2 | **Anexar mídia, áudio, emoji** — não existem affordances no input. `chat-view.tsx` tem só `<textarea>` e botão de envio. | `chat-view.tsx` |
| A3 | **Buscar conversa** está em `chat-list.tsx`, mas só busca por `name` e `phone` (não por conteúdo de mensagem nem por tag). Não há shortcut Cmd+K nem Ctrl+F. | `chat-list.tsx` |
| A4 | **Filtros são tabs por stage** (`CONVERSATION_TABS` em `frontend/src/lib/constants.ts`) e *quebram em flex-wrap*. Em laptop 13" viram 2 linhas. Não há "minhas conversas" funcional (a tab "Pessoal" significa outra coisa). | `chat-list.tsx`, `frontend/src/lib/constants.ts` |
| A5 | **Reativar conversa** abre painel inline com select de templates — mas não há preview do template, só nome/idioma/categoria. Vendedor envia às cegas. | `window-reactivate-panel.tsx` (3) |
| A6 | **Atalhos de teclado**: só Enter. Nada de ↑/↓ pra navegar conversas, J/K, Esc pra fechar painel, /, etc. Em ferramenta usada o dia inteiro isso é grande perda. | global |
| A7 | **Copy/quote de mensagem** — não há. Selecionar texto e responder não é affordance dedicada. | `message-bubble.tsx` |
| A8 | **Marcar conversa como não lida / favoritar / arquivar** — não existem. | global |
| A9 | **Notas internas / mentions** — `LeadNote` existe nos types, mas não é mostrado na sidebar de contact-detail nem é editável no chat. | `contact-detail.tsx`, `frontend/src/lib/types.ts` |

### 3.5 Feedback de sistema

| # | Problema | Local |
|---|---|---|
| F1 | **`ConversasPage.tsx` engole erros** silenciosamente (`catch { /* ignore */ }`). Vendedor não sabe quando a lista está velha por falha de fetch. | `frontend/src/app/(authenticated)/conversas/page.tsx` (linhas do `fetchConversations`) |
| F2 | **Loading inicial** mostra só vazio enquanto `loading=true`. Não há skeleton de cards na lista nem skeleton de mensagens. | `chat-list.tsx`, `message-list.tsx` |
| F3 | **Envio em progresso** = `opacity-70 + "Enviando..."`. Sem ticks, sem retry visível em caso de erro (input apenas restaura o texto silenciosamente — `chat-view.tsx` `setText(content)` no catch). | `chat-view.tsx`, `message-bubble.tsx` |
| F4 | **Toggle IA** atualiza otimisticamente, faz rollback em erro mas sem toast/banner — vendedor pode achar que pausou e ela voltar. | `contact-detail.tsx` `updateAgent` |
| F5 | **Realtime reconnect**: `supabase.channel("conversations-updates")` está sempre vivo, mas se cair (sleep do laptop, tab idle), nada avisa. | `page.tsx` |
| F6 | **Scroll-to-bottom button** mostra `unreadCount` (no `MessageList`), mas com `bg-red-500` — cor "perigo". Para "novas mensagens" deveria ser neutra ou Fin Orange. | `message-list.tsx` |

### 3.6 Consistência

| # | Problema | Local |
|---|---|---|
| C1 | **Cores fora do design system**: `bg-red-500`, `bg-green-500`, `bg-amber-700`, `bg-[#fef3c7]`, `bg-[#fff7ed]`, `border-[#f59e0b]/30`, `border-[#f97316]/30`, `text-[#92400e]`, `text-[#7c2d12]`. Tailwind defaults frios sendo usados em layout warm. | `chat-view.tsx` (banner janela), `message-list.tsx`, `chat-list.tsx` (red/green dots) |
| C2 | **`getStageColor` aparece duplicado** com valores diferentes entre `chat-list.tsx` e `chat-header.tsx` (ex.: `exportacao` é `#5aad65` em chat-header e `#5aad65` na chat-list, mas `consumo` é `#ad9c4a` em chat-list vs `#ad9c4a` em chat-header — coincidem aqui mas o duplo source-of-truth vai divergir). E `AGENT_STAGES` em `constants.ts` traz uma terceira tabela (`avatarColor`, `dotColor`, `tintColor`). | três fontes: `chat-list.tsx`, `chat-header.tsx`, `frontend/src/lib/constants.ts` |
| C3 | **Cantos**: cards de mensagem `rounded-[8px]` (✓ design), botões `rounded-[4px]` (✓), mas tabs de stage usam `rounded-[4px]` quando deveriam ser `rounded-[6px]` (nav). Scroll-to-bottom é `rounded-full`. Inconsistência fina. | múltiplos |
| C4 | **Sombras**: DESIGN.md proíbe sombras, mas `message-list.tsx` scroll button usa `shadow-lg`. | `message-list.tsx` |
| C5 | **Vocabulário misto**: "Pausar/Ativar IA" (contact-detail) vs "IA ativa/IA pausada" (chat-list) vs "Valeria" (em outros canais do produto) vs "Agente" (no select). | `contact-detail.tsx`, `chat-list.tsx`, `chat-header.tsx` |
| C6 | **Botão preto com `transition-transform hover:scale-110 active:scale-[0.85]`** (✓ DESIGN.md) está só no `chat-view.tsx` enviar mensagem. Demais botões (Reativar, Pausar, Confirmar envio, Adicionar à cadência) usam `hover:opacity-90` ou `hover:bg-...`. | `chat-view.tsx` (correto), `window-reactivate-panel.tsx`, `contact-detail.tsx` |

### 3.7 Acessibilidade

| # | Problema | Local |
|---|---|---|
| Y1 | **Botões de tabs sem `aria-pressed`** — leitor de tela não sabe qual está ativo. | `chat-list.tsx` tabs |
| Y2 | **Conversa selecionada na lista** sem `aria-current` ou role apropriado. | `chat-list.tsx` |
| Y3 | **Áreas de toque do dot 1.5×1.5px** (IA ativa/pausada) não são alvos clicáveis hoje, mas se virarem (recomendado), precisam ≥44×44 px de hit area. | `chat-list.tsx` |
| Y4 | **Contraste**: `text-white/50` no card preto ativo, `text-[#9b9b98]` em `bg-[#faf9f6]` (separador de dia), `text-white/60` em prévia da última mensagem do card ativo — todos abaixo de 4.5:1 (texto secundário). | `chat-list.tsx`, `day-separator.tsx`, `message-bubble.tsx` |
| Y5 | **Foco de teclado**: `<button>` da lista sem estilo de `:focus-visible` customizado — fica padrão do browser, frequentemente invisível em fundo escuro. | `chat-list.tsx` |
| Y6 | **Emojis carregam significado semântico** (⏳ ⏱ 🔒 🔴) sem texto alternativo — leitor de tela lê "ampulheta" sem contexto. | `chat-list.tsx`, `chat-header.tsx` |

### 3.8 Mobile / responsividade

| # | Problema | Local |
|---|---|---|
| M1 | **Layout é 3 colunas fixas** (`w-[320px]` lista + flex chat + sidebar) — colapsa horizontalmente em telas <1280px sem breakpoint. | `chat-list.tsx`, `chat-view.tsx`, `contact-detail.tsx` |
| M2 | **Sem drawer** para sidebar direita em viewport médio (1280-1440 px). Em 13" o vendedor perde o input ou a lista. | `page.tsx` |
| M3 | **Tabs flex-wrap** em vez de scroll horizontal — quebra em 2 linhas e empurra cards. | `chat-list.tsx` |
| M4 | **Sem mobile** real (página não é prioridade mobile, mas o cliente possivelmente vai tentar usar) — `<textarea rows={1}>` no input não escala bem em touch. | `chat-view.tsx` |

---

## 4. Recomendações Prioritizadas

> **Convenção:** Alta = dor diária do cliente; Média = polish que aparece imediatamente; Baixa = qualidade de longo prazo.

### Alta prioridade

#### R1. Adicionar `unread_count` no backend e bolinha verde + contador na lista
**Problema:** S1, S2. Cliente disse explicitamente.
**Proposta:**
- **Backend:** adicionar coluna `conversations.unread_count INT NOT NULL DEFAULT 0`. Incrementar em `backend/app/buffer/processor.py` quando salvar mensagem `role='user'`. Zerar quando vendedor abrir conversa (novo endpoint `POST /api/conversations/{id}/mark-read` no `backend/app/conversations/router.py`). Expor no payload do listing.
- **UI:** no card do `chat-list.tsx`, ao lado do nome ou do horário, **ponto verde 8×8px com número** quando `unread_count > 0`. Para `>9`, mostrar "9+". Cor: `#10b981` (verde) ou Fin Orange `#ff5600` para reforçar marca em destaque atencional. Recomendo Fin Orange — é o uso "para destaque/AI" do design system, e sinaliza onde a IA tipicamente está aguardando triagem.
- **Bonus:** no card ativo (selecionado) o contador zera com transição suave; nome do lead em `font-semibold` enquanto não-lido, `font-medium` depois.
**Impacto:** Vendedor vê de relance quem precisa de resposta. Reduz tempo médio de resposta. É a feature mais alta de ROI.

#### R2. Mover toggle "Pausar/Ativar IA" para o `ChatHeader`, com switch claro
**Problema:** A1, S5.
**Proposta:** No `chat-header.tsx`, ao lado do nome (antes do badge de canal), adicionar um pill switch:
- Estado ativo: fundo Fin Orange `#ff5600` + texto branco "Valéria ativa" + dot pulsante. (Uso correto do Fin Orange — é IA/marca.)
- Estado pausado: outline `#dedbd6` + texto `#7b7b78` "IA pausada" + ícone "play". Um clique alterna.
- Toast `bottom-right` confirmando "IA pausada para João Silva" / "Valéria reativada".
- Manter a versão completa (com seleção de profile) na sidebar direita, mas sem o toggle duplicado.
**Impacto:** Reduz cliques da ação #1 de 3 → 1. Elimina ambiguidade sobre estado da IA.

#### R3. Componente único `WhatsappWindowIndicator` consolidando 4 representações
**Problema:** S3, S4, C1.
**Proposta:** criar `frontend/src/components/conversas/whatsapp-window-indicator.tsx` com 3 variants:
- `compact` (lista): pill 6px alto, `bg-emerald-50 text-emerald-700` aberto / `bg-amber-50 text-amber-700` <2h / `bg-stone-200 text-stone-600` fechado. Texto: "23h", "1h 12min", "Fechada".
- `header` (chat): mesma cor + tooltip ao hover ("Janela WhatsApp 24h: cliente respondeu há X. Após 24h sem resposta dele, só pode enviar template aprovado pela Meta.").
- `banner` (chat): só quando `expiring` (<2h) ou `closed`. Sem emoji. Sem `bg-red-*`. Usa cores warm (`bg-[#fef3c7]` é OK, mas trocar `border-[#f97316]/30` por `border-[#dedbd6]`).

Consequência: remover lógica duplicada em `chat-list.tsx`, `chat-header.tsx`, `chat-view.tsx`. Vocabulário único: **"Janela 24h"**.
**Impacto:** Vendedor entende a regra Meta. Reduz medo/erros de envio em janela fechada.

#### R4. Diferenciar visualmente "última msg do lead" vs "última msg minha/da IA" no card
**Problema:** S2.
**Proposta:** no `chat-list.tsx`, antes do `last_message_text`:
- Se foi do lead (`last_msg_at == lead.last_customer_message_at` ou novo campo `last_message_role`): texto em cor `#111111` + leve negrito quando `unread_count > 0`.
- Se foi nossa: prefixo discreto "✓ Você:" ou "✓ IA:" em `text-[#9b9b98]`, mensagem em `text-[#7b7b78]`.
**Impacto:** Em 200ms vendedor sabe se a bola está com ele ou não.

#### R5. Repensar visual do card ativo na lista
**Problema:** H2, Y4.
**Proposta:** Em vez de `bg-[#111111] text-white`, usar **fundo warm cream tintado + borda esquerda Fin Orange 3px** (`border-l-[3px] border-l-[#ff5600] bg-white`). Mantém legibilidade dos meta-dados em `text-[#7b7b78]`. Alternativa: `bg-[#dedbd6]/40 border-l-[3px] border-l-[#111111]`.
**Impacto:** Densidade da lista preserva. Affordance "selecionado" mais elegante e acessível.

### Média prioridade

#### R6. Unificar formatação de data/hora em `frontend/src/lib/datetime.ts`
**Problema:** T1, T2.
**Proposta:** Funções `formatChatListTime`, `formatBubbleTime`, `formatDaySeparator`, `formatRelative`, `formatAbsolute`. Usar Intl com timezone do usuário. Garantir contraste >=4.5:1.
- Bolha: `text-[12px] text-[#7b7b78]` (em bolha branca) e `text-[12px] text-white/80` (em bolha preta — passa AA).
- Lista: `text-[12px] text-[#7b7b78]`. Hoje → "HH:mm" / Ontem → "Ontem HH:mm" / esta semana → "Seg 14:32" / antigo → "12/04".
- Day separator: pílula `bg-white border border-[#dedbd6] text-[12px] text-[#111111]`.

#### R7. Hierarquia tipográfica do card da lista
**Problema:** H1, T6.
**Proposta:**
- Linha 1: **Nome** `text-[14px] font-medium text-[#111111] tracking-[-0.1px]` + horário direita `text-[12px] text-[#7b7b78]`.
- Linha 2: prévia da última mensagem `text-[13px]` (1 linha truncada). Negrito quando não-lido.
- Linha 3 (meta): canal + telefone + IA dot, todos `text-[11px] text-[#9b9b98]`, separados por `·`.

Resultado: 3 níveis claros de peso, em vez do achatamento atual.

#### R8. Sidebar direita colapsável com seções padronizadas
**Problema:** H5.
**Proposta:** Em `contact-detail.tsx`, agrupar em 4 cards expansíveis:
1. **Lead** (sempre aberto): nome, telefone, stage, tags, owner.
2. **Valéria & Agent Profile** (sempre aberto): toggle redundante com header (espelhado), seleção de profile, último handoff.
3. **Empresa B2B** (colapsado por padrão): CNPJ, razão social, endereço.
4. **Deals & Cadências** (aberto se houver deals): lista de deals + enrollments ativos + botão "Criar deal".
Cada card = `bg-white border border-[#dedbd6] rounded-[8px] p-4`, header com chevron.

#### R9. Indicador de delivery status nas bolhas
**Problema:** S8, F3.
**Proposta:** Persistir em `messages.delivery_status` (`pending|sent|delivered|read|failed`) via webhook Meta (já chega em `backend/app/webhook/`). UI: ticks SVG ao lado do horário na bolha enviada — cinza um, cinza dois, azul dois, vermelho com tooltip de erro. Padrão WhatsApp, vendedor reconhece.

#### R10. Atalhos de teclado essenciais
**Problema:** A6.
**Proposta:**
- `↑`/`↓` ou `J`/`K`: navegar conversas na lista.
- `Cmd+K` / `Ctrl+K`: focar busca.
- `Esc`: fechar painel direito ou desselecionar conversa.
- `Cmd+Enter`: enviar mensagem (manter Enter como atalho atual).
- `Cmd+/` ou `?`: abrir cheatsheet.
Documentar no `frontend/src/hooks/use-keyboard-shortcuts.ts`.

### Baixa prioridade (mas alto retorno em polish)

#### R11. Skeletons e estados de erro
**Problema:** F1, F2, F5.
**Proposta:** Skeleton da lista (8 cards placeholder com pulse `bg-[#dedbd6]/40`). Skeleton de mensagens (3 bolhas placeholder). Banner topo `chat-list.tsx` quando fetch falha: "Não foi possível atualizar — tentar de novo" com retry. Indicator de Realtime status ("Conectado" / "Reconectando…").

#### R12. Pesquisa expandida
**Problema:** A3.
**Proposta:** `chat-list.tsx` busca: por nome, telefone, **conteúdo de mensagem** (RPC Supabase `search_messages`), e tag (`#tag`). Exibir snippets com highlight.

#### R13. Anexos, áudio, emojis, templates rápidos no input
**Problema:** A2.
**Proposta:** Toolbar mínima acima do `<textarea>`: ícones de anexar imagem, gravar áudio, abrir templates aprovados, emoji. Cada um abre menu/modal próprio. Templates inline: vendedor digita `/` e abre lista de templates (mesma fonte do reativar).

#### R14. Tabs com scroll horizontal e contagem por tab
**Problema:** M3, A4.
**Proposta:** `overflow-x-auto` nas tabs em vez de `flex-wrap`. Cada tab mostra contagem de não-lidas: "Atacado · 3". Adicionar tab "Minhas" filtrando `lead.assigned_to == currentUser.id`. Renomear "Pessoal" para "Sem lead" (que é o que ela faz hoje) ou remover.

#### R15. Pequenos ajustes de design system
**Problema:** C1, C3, C4, C6.
- Remover `shadow-lg` do scroll-to-bottom (`message-list.tsx`); usar `border border-[#dedbd6]`.
- Trocar `bg-red-500` do contador novo no scroll-to-bottom por `bg-[#ff5600]`.
- Aplicar `transition-transform hover:scale-110 active:scale-[0.85]` em todos botões pretos.
- Substituir `bg-amber-*`/`bg-orange-*`/`bg-red-*` dos banners de janela por warm equivalents do palette do projeto.

---

## 5. Top 5 / Top 5

### Top 5 problemas críticos
1. **Sem `unread_count`** — bug de produto + UI; queixa #1 do cliente. (S1)
2. **Janela 24h fragmentada** em 4 representações inconsistentes. (S3, S4)
3. **Toggle IA escondido** no painel direito apesar de ser ação mais frequente. (A1, S5)
4. **Datas e horários** com 3 sistemas, contraste baixo, regras divergentes. (T1, T2)
5. **Card selecionado preto sólido** destrói legibilidade da lista. (H2, Y4)

### Top 5 recomendações de maior impacto
1. **R1** — `unread_count` end-to-end + bolinha + contador. (Alta)
2. **R2** — Toggle Valéria no `ChatHeader`. (Alta)
3. **R3** — Componente único `WhatsappWindowIndicator` com tooltip educativo. (Alta)
4. **R5** — Card ativo com borda lateral Fin Orange em vez de fundo preto. (Alta)
5. **R7 + R6** — Hierarquia tipográfica e formatação de data unificadas. (Média; alto polish)

---

## 6. Apêndice — Arquivos relevantes (caminhos absolutos)

- `/home/rafael/maquinadevendas/frontend/src/app/(authenticated)/conversas/page.tsx`
- `/home/rafael/maquinadevendas/frontend/src/components/conversas/chat-list.tsx`
- `/home/rafael/maquinadevendas/frontend/src/components/conversas/chat-view.tsx`
- `/home/rafael/maquinadevendas/frontend/src/components/conversas/chat-header.tsx`
- `/home/rafael/maquinadevendas/frontend/src/components/conversas/message-list.tsx`
- `/home/rafael/maquinadevendas/frontend/src/components/conversas/message-bubble.tsx`
- `/home/rafael/maquinadevendas/frontend/src/components/conversas/day-separator.tsx`
- `/home/rafael/maquinadevendas/frontend/src/components/conversas/event-card.tsx`
- `/home/rafael/maquinadevendas/frontend/src/components/conversas/window-reactivate-panel.tsx`
- `/home/rafael/maquinadevendas/frontend/src/components/conversas/contact-detail.tsx`
- `/home/rafael/maquinadevendas/frontend/src/lib/types.ts`
- `/home/rafael/maquinadevendas/frontend/src/lib/constants.ts`
- `/home/rafael/maquinadevendas/frontend/src/lib/window-status.ts`
- `/home/rafael/maquinadevendas/frontend/src/hooks/use-realtime-messages.ts`
- `/home/rafael/maquinadevendas/frontend/src/app/api/conversations/route.ts`
- `/home/rafael/maquinadevendas/backend/app/conversations/router.py`
- `/home/rafael/maquinadevendas/backend/app/conversations/service.py`
- `/home/rafael/maquinadevendas/backend/app/buffer/processor.py` (onde incrementar `unread_count`)
- `/home/rafael/maquinadevendas/DESIGN.md`
