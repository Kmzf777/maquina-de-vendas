# Disparo Rápido — Design Spec

**Data:** 2026-04-18  
**Status:** Aprovado

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
   - Input de texto para o número (formato `+55...`)
   - Botão "Salvar" — persiste no banco via `POST /api/quick-send-phones`
   - Botão `×` — remove da lista local
5. **Números salvos** — chips clicáveis abaixo da lista. Clicar adiciona o número à lista de destino (se não estiver duplicado).
6. **Botão "+ Adicionar número"** — insere nova linha vazia na lista.

**Footer do modal:** `[Cancelar]` e `[Enviar →]`.

Botão "Enviar" desabilitado enquanto: nenhuma instância, nenhum template ou nenhum número adicionado.

---

## Fluxo de Envio (Opção A — sem alteração no backend Python)

Ao clicar "Enviar", o botão exibe "Enviando..." e executa em sequência:

1. `POST /api/broadcasts` com:
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

2. Para cada número na lista, buscar/criar lead via `POST /api/leads` (se não existir) e então chamar `POST /api/broadcasts/{id}/leads` com os `lead_ids` resultantes.

3. `POST /api/broadcasts/{id}/start` — inicia imediatamente.

4. Modal fecha. Toast de sucesso exibido por 3s: `"Disparo Rápido enviado para X número(s)"`.

5. Em caso de erro em qualquer etapa: toast vermelho com mensagem do erro.

O broadcast criado aparece na aba "Disparos" com status `running` → `completed`.

---

## Números Salvos

### Tabela Supabase: `quick_send_phones`

```sql
CREATE TABLE quick_send_phones (
  id         uuid primary key default gen_random_uuid(),
  phone      text not null unique,
  label      text,
  created_at timestamptz default now()
);
```

### API Routes (Next.js)

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/quick-send-phones` | Lista todos os números salvos |
| POST | `/api/quick-send-phones` | Salva novo número `{ phone, label? }` |
| DELETE | `/api/quick-send-phones/[phone]` | Remove número salvo |

---

## Validações

- Número deve começar com `+` para ser adicionado à lista
- Duplicatas na lista de destino são ignoradas silenciosamente
- Duplicata ao salvar no banco: retorna 409, ignorada silenciosamente no frontend

---

## Componentes e Arquivos

### Novos
- `frontend/src/components/campaigns/quick-send-modal.tsx` — modal completo
- `frontend/src/app/api/quick-send-phones/route.ts` — GET e POST
- `frontend/src/app/api/quick-send-phones/[phone]/route.ts` — DELETE

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

## Fora do Escopo (MVP)

- Gerenciamento de números salvos (editar label, listar em tela separada)
- Agendamento de envio
- Seleção de agente
- Intervalo entre envios configurável
