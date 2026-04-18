# Disparo Rápido — Design Spec

**Data:** 2026-04-18  
**Status:** Aprovado (rev. 2 — pós code review)

## Objetivo

Adicionar um botão "Disparo Rápido" na aba `/campanhas` que permite enviar um template aprovado da Meta para um ou mais números de telefone diretamente, sem passar pelo fluxo completo de criação de campanha. Voltado para testes rápidos de templates.

---

## Interface

### Botão

Adicionado ao header da página `CampanhasPage`, ao lado dos botões existentes (`+ Disparo`, `+ Cadencia`, `+ Template`). Estilo outline idêntico ao `+ Cadencia`.

```tsx
<button onClick={() => setShowQuickSendModal(true)} className="bg-transparent ...">
  + Disparo Rápido
</button>
```

### Modal (`QuickSendModal`)

Modal único (sem steps). Campos em ordem:

1. **Instância** — select filtrado por `provider === "meta_cloud" && is_active`. Rótulo: "INSTÂNCIA".
2. **Template** — select populado via `GET /api/channels/{id}/templates` após seleção da instância. Rótulo: "TEMPLATE".
3. **Variáveis** — inputs dinâmicos gerados a partir de `template.params`, visíveis apenas quando o template possui params. Mesmo padrão visual do `create-broadcast-modal`.
4. **Números de destino** — lista dinâmica de inputs. Cada linha tem:
   - Input de texto para o número (formato `+55...` — exibido ao usuário)
   - Botão "Salvar" — persiste no banco via `POST /api/quick-send-phones`
   - Botão `×` — remove da linha da lista local
5. **Números salvos** — chips clicáveis abaixo da lista. Clicar adiciona o número à lista de destino (se não estiver duplicado).
6. **Botão "+ Adicionar número"** — insere nova linha vazia na lista.

**Footer do modal:** `[Cancelar]` e `[Enviar →]`.

Botão "Enviar" desabilitado enquanto: nenhuma instância selecionada, nenhum template selecionado ou nenhum número adicionado.

---

## Normalização de Telefones

O sistema armazena phones em dois formatos dependendo da origem (inconsistência pré-existente):
- Via CSV import: `5511999999999` (sem `+`)
- Via outbound manual: `+5511999999999` (com `+`)

Para o Disparo Rápido, adota-se o formato **sem `+`** (igual ao CSV import), pois é o mais frequente no banco e o broadcast worker passa `lead["phone"]` direto para a Meta API, que aceita ambos os formatos.

**Regra de normalização (aplicada no frontend antes de qualquer operação):**
```ts
function normalizePhone(raw: string): string {
  return raw.replace(/\D/g, ""); // remove tudo que não é dígito
}
```

- Input do usuário: `+5511999999999` → armazenado e usado como `5511999999999`
- Validação mínima: resultado deve ter entre 12 e 13 dígitos
- Duplicatas na lista de destino: ignoradas silenciosamente

---

## Fluxo de Envio (Opção A — sem alteração no backend Python)

Ao clicar "Enviar", o botão exibe "Enviando..." e executa em sequência:

### Passo 1 — Criar o broadcast
`POST /api/broadcasts` com:
```json
{
  "name": "Disparo Rápido — {template_name} — {DD/MM/YYYY HH:mm}",
  "channel_id": "{channelId}",
  "template_name": "{template.name}",
  "template_language_code": "{template.language}",
  "template_variables": { ...templateVarValues },
  "send_interval_min": 0,
  "send_interval_max": 0
}
```

### Passo 2 — Resolver lead_ids (get-or-create por phone)

`POST /api/leads` retorna 409 sem o `lead_id` quando o número já existe. Por isso, é necessário um novo route dedicado:

**Novo route:** `POST /api/leads/resolve`  
Aceita `{ phone: string }` (normalizado, sem `+`).  
Lógica interna:
1. Faz `SELECT id FROM leads WHERE phone = $phone` via Supabase server-side
2. Se encontrado: retorna `{ id, created: false }`
3. Se não encontrado: insere `{ phone, status: "imported", stage: "pending" }` e retorna `{ id, created: true }`

O QuickSendModal chama este route para cada número da lista e coleta os `lead_ids`.

### Passo 3 — Associar leads ao broadcast
`POST /api/broadcasts/{id}/leads` com `{ lead_ids: [...] }`

### Passo 4 — Iniciar
`POST /api/broadcasts/{id}/start`

### Passo 5 — Feedback
- Modal fecha
- Toast de sucesso por 3s: `"Disparo Rápido enviado para X número(s)"`
- Em erro em qualquer etapa: toast vermelho com a mensagem

O broadcast aparece na aba "Disparos" com status `running` → `completed`.

---

## Números Salvos

### Tabela Supabase: `quick_send_phones`

```sql
CREATE TABLE quick_send_phones (
  id         uuid primary key default gen_random_uuid(),
  phone      text not null unique,  -- formato normalizado sem +
  label      text,
  created_at timestamptz default now()
);
```

### API Routes (Next.js)

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/quick-send-phones` | Lista todos os números salvos |
| POST | `/api/quick-send-phones` | Salva novo número `{ phone, label? }` (normalizado) |
| DELETE | `/api/quick-send-phones/[phone]` | Remove número salvo |

---

## Componentes e Arquivos

### Novos
- `frontend/src/components/campaigns/quick-send-modal.tsx` — modal completo
- `frontend/src/app/api/quick-send-phones/route.ts` — GET e POST
- `frontend/src/app/api/quick-send-phones/[phone]/route.ts` — DELETE
- `frontend/src/app/api/leads/resolve/route.ts` — POST get-or-create por phone

### Modificados
- `frontend/src/app/(authenticated)/campanhas/page.tsx` — adicionar botão e importar modal

### Sem alterações
- Backend Python (FastAPI) — reutiliza endpoints existentes
- Tabelas `broadcasts` e `broadcast_leads` — sem mudanças

---

## Nome do Broadcast Gerado

```
Disparo Rápido — {template_name} — {DD/MM/YYYY HH:mm}
```

O usuário não precisa digitar nome. Isso distingue visualmente os Disparos Rápidos dos disparos normais na lista.

---

## Limitações Conhecidas (MVP)

- **Variáveis posicionais (`{{1}}`):** O route `GET /api/channels/[id]/templates` extrai apenas `body_text_named_params`. Templates antigos com variáveis posicionais retornam `params: []` e não exibem inputs de preenchimento. Limitação pré-existente, não introduzida por esta feature.

---

## Fora do Escopo (MVP)

- Gerenciamento de números salvos (editar label, listar em tela separada)
- Agendamento de envio
- Seleção de agente
- Intervalo entre envios configurável
