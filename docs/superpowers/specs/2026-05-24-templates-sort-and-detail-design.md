# Templates — Ordenação e Visualização de Detalhes

## Contexto

A aba "Templates" em `/campanhas` exibe uma tabela de templates de WhatsApp sincronizados da Meta API. Atualmente a tabela não tem ordenação e não permite visualizar o conteúdo completo de um template (body, header, variáveis, botões).

## Objetivo

Implementar duas melhorias na aba de templates:
1. **Ordenação client-side** por Name, Categoria, Status, Idioma e Criado em
2. **Sheet de detalhes** que exibe a estrutura completa do template ao clicar em uma linha

## Decisões de Arquitetura

### Fonte dos dados para o Sheet

O campo `components` (JSON bruto da Meta) já é salvo no banco pelo sync. A rota `/api/templates` não o seleciona hoje. A solução é **enriquecer a API**: adicionar `components` ao SELECT e parsear `body`, `header`, `footer`, `buttons`, `params`, `paramsType` no servidor antes de retornar — zero chamadas extras ao clicar.

### Overlay

Instalar o componente `Sheet` do shadcn/ui via `npx shadcn@latest add sheet`. Componente nativo, acessível, com animação slide-in.

### Reutilização de lógica de parsing

A função de parsing de `components` já existe em `frontend/src/app/api/channels/[id]/templates/route.ts`. As funções `parseBody`, `parseHeader`, `parseFooter`, `parseButtons` e `parseParamsAndType` serão extraídas para um módulo compartilhado `frontend/src/lib/template-parser.ts` e reutilizadas por ambas as rotas.

### Ordenação

Estado local `sortConfig: { key: keyof SortableFields; direction: "asc" | "desc" } | null` no componente `TemplatesTab`. Aplicado com `.sort()` antes do `.map()`. Ícones lucide-react nos cabeçalhos.

## Componentes Afetados

| Arquivo | Tipo de mudança |
|---|---|
| `frontend/src/lib/template-parser.ts` | Criado — lógica de parsing extraída |
| `frontend/src/lib/types.ts` | Modificado — `MessageTemplate` enriquecido com campos opcionais |
| `frontend/src/app/api/templates/route.ts` | Modificado — inclui `components`, retorna campos parseados |
| `frontend/src/app/api/channels/[id]/templates/route.ts` | Modificado — usa `template-parser.ts` |
| `frontend/src/components/campaigns/templates-tab.tsx` | Modificado — ordenação + Sheet |
| `frontend/src/components/campaigns/template-detail-sheet.tsx` | Criado — visualização de detalhes |

## UX do Sheet

- Abre ao clicar em qualquer linha da tabela
- Largura: `sm` (384px padrão do shadcn Sheet)
- Conteúdo: Nome + badges de categoria/status/idioma no topo
- Seções (divisores): **Cabeçalho**, **Corpo** (body com `{{vars}}` destacados), **Variáveis** (chips de código), **Botões** (chips)
- Sem inputs de edição — visualização pura
- Estética consistente com o resto do projeto (cores `#111111`, `#7b7b78`, `#dedbd6`, etc.)

## UX da Ordenação

- Clique no cabeçalho: ordena asc
- Segundo clique: ordena desc
- Terceiro clique: remove ordenação (volta ao original)
- Ícone `ArrowUpDown` quando sem ordenação, `ArrowUp`/`ArrowDown` quando ativo
