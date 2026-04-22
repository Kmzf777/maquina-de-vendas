# Kanban Premium Redesign — Design Spec

**Data:** 2026-03-28
**Status:** Aprovado
**Motivacao:** As telas de Qualificacao e Vendas estao visualmente cruas — sem hierarquia visual, cards genericos, metricas sem destaque, colunas sem diferenciacao. Redesign geral com direcao "Headers Premium" para dar autoridade e polish profissional.

---

## 1. Direcao Visual: Headers Premium

Contraste forte entre elementos dark (metricas, headers de coluna) e fundo claro. Combina com a sidebar dark existente. Paleta olive/verde para acentos. Visual premium, clean, inspirado em Linear/Pipedrive.

### Paleta de Cores

| Token | Valor | Uso |
|-------|-------|-----|
| Dark base | `#1f1f1f` | Metricas, headers de coluna, avatares |
| Canvas | `#f6f7ed` | Fundo da pagina |
| Card bg | `#ffffff` | Cards de lead |
| Border | `#e5e5dc` | Bordas de cards |
| Olive | `#c8cc8e` | Acento primario, indicadores |
| Green | `#5aad65` | Valores monetarios positivos |
| Dark green | `#2d6a3f` | Texto de valor em cards |
| Muted | `#9ca3af` | Texto secundario, labels |
| Yellow | `#e8d44d` | Unread badges |

### Cores por Stage (dots + tint de fundo de coluna)

**Qualificacao (AGENT_STAGES):**
| Stage | Dot | Fundo coluna |
|-------|-----|-------------|
| Secretaria | `#c8cc8e` | `#f2f3eb` |
| Atacado | `#5b8aad` | `#eef2f6` |
| Private Label | `#9b7abf` | `#f0edf4` |
| Exportacao | `#5aad65` | `#edf4ef` |
| Consumo | `#d4b84a` | `#f4f2ea` |

**Vendas (SELLER_STAGES):**
| Stage | Dot | Fundo coluna |
|-------|-----|-------------|
| Novo | `#e07a7a` | `#f6eeee` |
| Em Contato | `#d4a04a` | `#f4f0ea` |
| Negociacao | `#5b8aad` | `#eef2f6` |
| Fechado | `#5aad65` | `#edf4ef` |
| Perdido | `#9ca3af` | `#f2f2f0` |

---

## 2. Barra de Metricas

Substituir a barra horizontal unica por **cards dark individuais** lado a lado.

### Estrutura de cada card de metrica:
- Background: `#1f1f1f`, border-radius: 12px
- Padding: 14px 18px
- Label: 10px uppercase, `#9ca3af`, letter-spacing 0.5px
- Valor principal: 24px bold, white
- Subtexto: 11px, olive (`#c8cc8e`) ou green (`#5aad65`)
- Opcional: mini progress bar (3px height, bg `#333`, fill com cor de acento)

### Metricas mostradas (4 cards):
1. **Total no funil** — contagem de leads + "R$ X em pipeline" em olive
2. **Novos hoje / ontem** — numero grande + "/ N" em cinza + indicador de tendencia em verde
3. **Vendas em potencial** — valor em verde + progress bar
4. **Tempo medio resp.** — valor + "agente IA" em olive

Ambas as paginas (Qualificacao e Vendas) usam o mesmo componente de metricas, ja que `KanbanMetricsBar` e compartilhado.

---

## 3. Headers de Coluna

Substituir headers simples (texto + dot) por **headers dark**.

### Estrutura:
- Background: `#1f1f1f`
- Border-radius: 12px 12px 0 0 (top only)
- Padding: 10px 14px
- Layout: flex, space-between
- Esquerda: dot colorido (8px, circular) + nome do stage (12px semibold, white)
- Direita: badge de contagem (10px semibold, white, bg `rgba(255,255,255,0.15)`, rounded-full, padding 2px 8px)

### Corpo da coluna:
- Background: tint sutil da cor do stage (ver tabela acima)
- Border-radius: 0 0 12px 12px (bottom only)
- Padding: 10px
- Min-height: calc(100vh - 280px) para manter colunas uniformes

O header e o corpo formam visualmente um bloco unico com cantos arredondados.

---

## 4. Lead Cards (Nivel Medio)

### Layout do card:
- Background: white, border: 1px solid `#e5e5dc`, border-radius: 10px
- Padding: 12px
- Shadow: `0 2px 8px rgba(0,0,0,0.05)`
- Hover: shadow `0 4px 12px rgba(0,0,0,0.08)`, translate-y -1px
- Cursor: pointer

### Conteudo (de cima pra baixo):

**Row 1 — Avatar + Nome + Tempo:**
- Avatar: 34px circular, bg `#1f1f1f`, inicial em cor do stage (font 13px bold)
- Nome: 13px semibold, `#1f1f1f`
- Tempo: 10px, `#9ca3af`, alinhado a direita
- Valor (se >0): 11px semibold, `#2d6a3f`, abaixo do nome

**Row 2 — Tags (se existirem):**
- Max 3 tags visiveis + "+N" se houver mais
- Badge: 9px font-weight 500, padding 2px 8px, border-radius 6px
- Cores pastel com texto escuro (manter cores customizadas das tags)

**Row 3 — Preview da ultima mensagem:**
- 11px italic, `#9ca3af`
- white-space: nowrap, overflow: hidden, text-overflow: ellipsis
- Aspas ao redor do texto

### Avatar — Cor da inicial por stage:
A cor da letra dentro do avatar dark reflete o stage do lead:
- Secretaria: olive `#c8cc8e`
- Atacado: green `#5aad65`
- Private Label: purple `#9b7abf`
- Exportacao: yellow `#e8d44d`
- Consumo: tan `#d4b84a`

Para Vendas, usar a mesma logica com as cores dos SELLER_STAGES:
- Novo: `#e07a7a`
- Em Contato: `#d4a04a`
- Negociacao: `#5b8aad`
- Fechado: `#5aad65`
- Perdido: `#9ca3af`

---

## 5. Empty States

Colunas sem leads mostram estado vazio minimalista:

- Layout: flex column, align-items center, justify-content center (preenche o corpo da coluna)
- Texto: "Nenhum lead", 12px, `#b0adb5`
- Botao: "+ Adicionar", border 1px dashed (cor derivada do tint do stage), border-radius 10px, transparent bg, `#9ca3af`, 12px
- Hover no botao: background levemente tinted

---

## 6. Filtros (Search + Toggle)

### Search input:
- Icone de lupa (emoji ou SVG) a esquerda, padding-left para acomodar
- Width: 320px
- Padding: 9px 12px 9px 34px
- Border: 1px solid `#e5e5dc`, border-radius 10px
- Font: 13px, placeholder em `#9ca3af`

### Toggle "Leads ativos":
- Ativo: bg `#1f1f1f`, text white, 12px medium
- Inativo: bg `#f6f7ed`, border `#e5e5dc`, text `#9ca3af`
- Border-radius: 10px, padding: 9px 16px

---

## 7. Arquivos Afetados

| Arquivo | Mudanca |
|---------|---------|
| `crm/src/app/globals.css` | Novas CSS variables para cores de stage (dots e tints) |
| `crm/src/lib/constants.ts` | Adicionar `dotColor` e `tintColor` aos AGENT_STAGES e SELLER_STAGES |
| `crm/src/components/kanban-metrics-bar.tsx` | Redesign completo — cards dark individuais |
| `crm/src/components/kanban-column.tsx` | Header dark + corpo com tint + empty state |
| `crm/src/components/lead-card.tsx` | Avatar dark com inicial colorida, layout medio |
| `crm/src/components/kanban-filters.tsx` | Icone de busca no input |
| `crm/src/components/quick-add-lead.tsx` | Estilo dashed consistente com empty state |
| `crm/src/app/(authenticated)/qualificacao/page.tsx` | Ajustar passagem de props (cores) |
| `crm/src/app/(authenticated)/vendas/page.tsx` | Ajustar passagem de props (cores), DroppableColumn com novo visual |

## 8. O que NAO muda

- Sidebar (ja esta dark e ok)
- Logica de drag-and-drop no Vendas
- Dashboard page
- Conversas/Config/Campanhas pages
- Backend / API routes
- Tipos TypeScript (Lead, Tag, etc.)
- Funcionalidade de filtros (apenas visual)

## 9. Resultado Esperado

- Visual premium com contraste dark/light que da autoridade
- Hierarquia clara: metricas > colunas > cards
- Cada stage visualmente distinto pela cor (dot + tint + avatar)
- Cards scannable com info essencial sem abrir detalhe
- Empty states limpos que nao poluem a tela
- Consistencia visual entre Qualificacao e Vendas
