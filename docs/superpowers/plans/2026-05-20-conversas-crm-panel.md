# Plano: CRM Panel Completo em /conversas

**Spec:** `docs/superpowers/specs/2026-05-20-conversas-crm-panel-design.md`  
**Branch:** `fix/conversas-crm-panel`  
**Status:** Aprovado para execução

---

## Passos

### 1. Fix: editable-field.tsx

**Arquivo:** `frontend/src/components/conversas/editable-field.tsx`

Adicionar `useEffect` para sincronizar `draft` quando `value` muda fora do modo de edição:

```tsx
useEffect(() => {
  if (!editing) setDraft(value || "");
}, [value, editing]);
```

---

### 2. Infrastructure: handleLeadUpdate em conversas/page.tsx

**Arquivo:** `frontend/src/app/(authenticated)/conversas/page.tsx`

Adicionar função `handleLeadUpdate`:
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

Passar `onLeadUpdate={handleLeadUpdate}` para ambos os `<ContactDetail>` (mobile e desktop).

---

### 3. Criar: crm-perfil-tab.tsx

**Arquivo:** `frontend/src/components/conversas/tabs/crm-perfil-tab.tsx`

Props: `lead: Lead, onLeadUpdate: (field: string, value: string) => void, deals: LeadDeal[], pipelines: Pipeline[], tags: Tag[], leadTags: Tag[], onTagToggle: (tagId: string, add: boolean) => void, onCreateDeal: () => void`

Seções:
- Identificação (nome editável, empresa editável, telefone readonly, email, instagram)
- Empresa B2B (CNPJ, razao_social, nome_fantasia, inscricao_estadual, endereco, tel_comercial)
- Status CRM (stage dropdown, assigned_to)
- Oportunidades (deals list + botão criar)
- Tags

Todos os campos usam `EditableField`. Saves: chamar `onLeadUpdate` (otimista no pai) + `PATCH /api/leads/:id`.

---

### 4. Criar: crm-notas-tab.tsx

**Arquivo:** `frontend/src/components/conversas/tabs/crm-notas-tab.tsx`

Props: `leadId: string`

- Fetch ao montar: `GET /api/leads/:id/notes` + `GET /api/leads/:id/events`
- Campo de nova nota + botão Salvar
- Timeline unificada (notas + eventos) ordenada por data desc
- Reutilizar formatação de `LeadDetailModal` tab tags_notas

---

### 5. Criar: crm-campanhas-tab.tsx

**Arquivo:** `frontend/src/components/conversas/tabs/crm-campanhas-tab.tsx`

Props: `leadId: string`

- Fetch ao montar: Supabase `cadence_enrollments` JOIN `cadences` onde `lead_id = leadId`
- Exibir enrollments com status badge, step atual, próximo envio
- Componente `LeadBroadcastHistory` abaixo

---

### 6. Criar: crm-metricas-tab.tsx

**Arquivo:** `frontend/src/components/conversas/tabs/crm-metricas-tab.tsx`

Props: `lead: Lead`

- Cards: Temperatura (getTemperature), 1ª Resposta (first_response_at), Dias no CRM (created_at), Dias no stage (entered_stage_at)
- Sem fetch adicional — dados já no lead prop

---

### 7. Rewrite: contact-detail.tsx

**Arquivo:** `frontend/src/components/conversas/contact-detail.tsx`

Adicionar prop: `onLeadUpdate?: (leadId: string, patch: Partial<Lead>) => void`

Estrutura:
```
Header fixo (avatar, nome, telefone, canal, on_hold, mobile back button, AI/followup toggles mobile)
Tab bar (Perfil | Notas | Campanhas | Métricas) — estado local activeTab
Tab content scrollável:
  - activeTab === "perfil" → <CrmPerfilTab>
  - activeTab === "notas" → <CrmNotasTab>
  - activeTab === "campanhas" → <CrmCampanhasTab>
  - activeTab === "metricas" → <CrmMetricasTab>
DealCreateModal (mantém como está)
```

A função `updateLeadField` que passa para `CrmPerfilTab`:
```tsx
async function updateLeadField(field: string, value: string) {
  if (!lead) return;
  onLeadUpdate?.(lead.id, { [field]: value } as Partial<Lead>); // otimista
  try {
    const res = await fetch(`/api/leads/${lead.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value }),
    });
    if (!res.ok) throw new Error();
  } catch {
    // reverter: buscar valor atual e chamar onLeadUpdate com o original
    onLeadUpdate?.(lead.id, { [field]: lead[field as keyof Lead] } as Partial<Lead>);
  }
}
```

---

### 8. Commit

Commit com todos os arquivos modificados/criados.

---

## Dependências entre passos

- Passos 1 e 2 são independentes entre si e dos demais
- Passos 3-6 são independentes entre si (cada tab é isolada)
- Passo 7 depende dos passos 3-6 (importa os tab components)
- Passo 8 é o último
