# Spec: CRM Panel Completo em /conversas

**Data:** 2026-05-20  
**Status:** Aprovado

---

## Problema

O painel lateral de `/conversas` (`contact-detail.tsx`) tem dois problemas críticos:

1. **Bug de edição**: `EditableField` não sincroniza o estado `draft` quando a prop `value` muda (ao trocar de conversa). O usuário edita, sai do campo, e o valor reverte — porque `updateLeadField` chama a API mas não atualiza o estado local da conversa no pai.

2. **CRM incompleto**: O painel mostra apenas campos B2B e deals. Faltam: nome/empresa editáveis, notas, timeline de eventos, cadências e métricas — tudo já existente no `LeadDetailModal` de `/leads`.

---

## Solução

Transformar `contact-detail.tsx` num painel CRM completo com 4 abas, corrigindo o bug estruturalmente com otimismo de estado.

---

## Arquitetura

### Correção do Bug (EditableField)

Adicionar `useEffect` em `editable-field.tsx` para sincronizar `draft` quando `value` muda:

```tsx
useEffect(() => {
  if (!editing) setDraft(value || "");
}, [value, editing]);
```

### Fluxo de Atualização (onLeadUpdate)

Adicionar prop `onLeadUpdate?: (leadId: string, patch: Partial<Lead>) => void` ao `ContactDetail`.

Em `conversas/page.tsx`, implementar `handleLeadUpdate` que atualiza `conversations` e `selectedConversation` otimisticamente:

```tsx
function handleLeadUpdate(leadId: string, patch: Partial<Lead>) {
  const updateConv = (c: Conversation) =>
    (c.leads as Lead)?.id === leadId
      ? { ...c, leads: { ...(c.leads as Lead), ...patch } }
      : c;
  setConversations(prev => prev.map(updateConv));
  setSelectedConversation(prev => prev ? updateConv(prev) : prev);
}
```

Cada save em `contact-detail.tsx` chama `onLeadUpdate` com o patch antes da requisição (otimista) e reverte em caso de erro.

### Estrutura de Abas

```
ContactDetail (header fixo: avatar + nome + telefone + canal + badges)
├── Tab Bar: [Perfil] [Notas] [Campanhas] [Métricas]
└── Tab Content (scrollável)
    ├── CrmPerfilTab
    ├── CrmNotasTab
    ├── CrmCampanhasTab
    └── CrmMetricasTab
```

### CrmPerfilTab

Seções:
- **Identificação**: Nome (editável), Empresa/company (editável), Telefone (readonly), Email, Instagram
- **Empresa B2B**: CNPJ, Razão Social, Nome Fantasia, IE, Endereço, Telefone Comercial
- **Status CRM**: Stage (dropdown AGENT_STAGES), Atribuído a (texto)
- **Oportunidades**: lista de deals + botão criar novo deal
- **Tags**: igual ao atual

Comportamento de save: otimista via `onLeadUpdate` + `PATCH /api/leads/:id`. Feedback visual inline (campo fica verde por 1s no sucesso, vermelho + restaura no erro).

### CrmNotasTab

- Campo + botão "Adicionar nota" no topo
- Timeline unificada (notas + eventos de stage_change, cadence, etc.) ordenada por data desc
- Formato igual ao `LeadDetailModal` tabs_notas

Fetch: `GET /api/leads/:id/notes` + `GET /api/leads/:id/events` ao montar a aba

### CrmCampanhasTab

- Seção "Cadências" — `cadence_enrollments` com status, step atual, próximo envio
- Seção "Disparos Recebidos" — componente `LeadBroadcastHistory` já existente

Fetch: Supabase direto (`cadence_enrollments + cadences`) ao montar a aba

### CrmMetricasTab

Cards: Temperatura · 1ª Resposta · Dias no CRM · Dias no stage atual  
Lógica idêntica ao `LeadDetailModal` aba Métricas. Sem fetch adicional (usa dados do `lead` já carregado).

---

## Arquivos

### Criar
- `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`
- `frontend/src/components/conversas/tabs/crm-notas-tab.tsx`
- `frontend/src/components/conversas/tabs/crm-campanhas-tab.tsx`
- `frontend/src/components/conversas/tabs/crm-metricas-tab.tsx`

### Modificar
- `frontend/src/components/conversas/editable-field.tsx` — bug fix
- `frontend/src/components/conversas/contact-detail.tsx` — rewrite com tabs
- `frontend/src/app/(authenticated)/conversas/page.tsx` — add handleLeadUpdate

---

## Consistência com /leads

A página `/leads` já tem `LeadDetailModal` com as mesmas 4 abas. Esta spec traz `/conversas` para paridade, mantendo a mesma lógica de API e os mesmos componentes onde possível (ex: `LeadBroadcastHistory`, `DealCreateModal`).

---

## Não incluído nesta spec

- Mudanças no `/leads` — já está funcional
- Mudanças de schema Supabase — todos os campos já existem
- Mudanças no backend — API PATCH /leads/:id já suporta todos os campos
