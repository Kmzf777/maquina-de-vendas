"use client";

import { useState } from "react";
import {
  DndContext, closestCenter, PointerSensor, useSensor, useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext, verticalListSortingStrategy,
  useSortable, arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { PipelineStage } from "@/lib/types";

const COLOR_PALETTE = [
  "#e07a7a", "#d4a04a", "#d4b84a", "#5aad65",
  "#5b8aad", "#9b7abf", "#9ca3af", "#111111",
];

interface EditableStage extends PipelineStage {
  _dirty?: boolean;
}


interface PipelineEditModalProps {
  pipelineId: string;
  pipelineName: string;
  stages: PipelineStage[];
  onClose: () => void;
  onSaved: () => void;
}

function SortableStageRow({
  stage, onChange, onDelete,
}: {
  stage: EditableStage;
  onChange: (id: string, field: keyof EditableStage, value: string) => void;
  onDelete: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: stage.id });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }}
      className="flex items-center gap-3 py-2.5 px-3 bg-white border border-[#dedbd6] rounded-[6px] mb-2"
    >
      {/* Drag handle */}
      <div
        {...{ ...listeners, ...attributes }}
        className="flex-shrink-0 cursor-grab active:cursor-grabbing"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="#7b7b78">
          <circle cx="5" cy="4" r="1.2" /><circle cx="11" cy="4" r="1.2" />
          <circle cx="5" cy="8" r="1.2" /><circle cx="11" cy="8" r="1.2" />
          <circle cx="5" cy="12" r="1.2" /><circle cx="11" cy="12" r="1.2" />
        </svg>
      </div>

      {/* Color picker */}
      <div className="relative flex-shrink-0 group">
        <div className="w-4 h-4 rounded-full border border-[#dedbd6] cursor-pointer" style={{ backgroundColor: stage.dot_color }} />
        <div className="absolute left-0 top-full mt-1 bg-white border border-[#dedbd6] rounded-[6px] p-2 z-10 hidden group-hover:grid grid-cols-4 gap-1 w-[88px] shadow-sm">
          {COLOR_PALETTE.map((c) => (
            <button key={c} type="button" onClick={() => onChange(stage.id, "dot_color", c)}
              className={`w-4 h-4 rounded-full border ${stage.dot_color === c ? "border-[#111111]" : "border-transparent"}`}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
      </div>

      {/* Label input */}
      <input
        value={stage.label}
        onChange={(e) => onChange(stage.id, "label", e.target.value)}
        className="flex-1 text-[13px] text-[#111111] bg-transparent focus:outline-none min-w-0"
      />

      {/* Delete button */}
      <button type="button" onClick={() => onDelete(stage.id)}
        className="flex-shrink-0 text-[#7b7b78] hover:text-[#e07a7a] transition-colors"
      >
        <svg width="14" height="14" fill="none" viewBox="0 0 16 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </div>
  );
}

export function PipelineEditModal({
  pipelineId, pipelineName, stages: initialStages, onClose, onSaved,
}: PipelineEditModalProps) {
  const [stages, setStages] = useState<EditableStage[]>(initialStages);
  const [name, setName] = useState(pipelineName);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  function handleChange(id: string, field: keyof EditableStage, value: string) {
    setStages((prev) => prev.map((s) => s.id === id ? { ...s, [field]: value, _dirty: true } : s));
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setStages((prev) => {
      const oldIndex = prev.findIndex((s) => s.id === active.id);
      const newIndex = prev.findIndex((s) => s.id === over.id);
      return arrayMove(prev, oldIndex, newIndex).map((s, i) => ({ ...s, order_index: i, _dirty: true }));
    });
  }

  async function handleAddStage() {
    const res = await fetch(`/api/pipelines/${pipelineId}/stages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: "Novo Stage", dot_color: "#5b8aad" }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setError(d.error ?? "Erro ao adicionar stage.");
      return;
    }
    const data = await res.json();
    if (data?.id) {
      setStages((prev) => {
        // Inserir antes do primeiro stage com is_protected (fica sempre no final)
        const firstProtected = prev.findIndex((s) => s.is_protected);
        const insertAt = firstProtected === -1 ? prev.length : firstProtected;
        const next = [...prev];
        next.splice(insertAt, 0, { ...data, _dirty: false });
        return next.map((s, i) => ({ ...s, order_index: i }));
      });
    }
  }

  async function handleDelete(stageId: string) {
    const res = await fetch(`/api/pipelines/${pipelineId}/stages/${stageId}`, { method: "DELETE" });
    if (!res.ok) {
      const msg = await res.json().then((d: { error?: string }) => d.error).catch(() => "Erro ao excluir stage.");
      setError(msg ?? "Erro ao excluir stage.");
      return;
    }
    setStages((prev) => prev.filter((s) => s.id !== stageId));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const ops: Promise<void>[] = [];

      if (name.trim() && name.trim() !== pipelineName) {
        ops.push(
          fetch(`/api/pipelines/${pipelineId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name.trim() }),
          }).then(async (r) => {
            if (!r.ok) {
              const d = await r.json().catch(() => ({}));
              throw new Error(d.error ?? "Erro ao renomear funil.");
            }
          })
        );
      }

      // Salvar apenas stages marcados como dirty
      const dirty = stages.filter((s) => s._dirty);
      ops.push(
        ...dirty.map((s) =>
          fetch(`/api/pipelines/${pipelineId}/stages/${s.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label: s.label, dot_color: s.dot_color, order_index: s.order_index }),
          }).then(async (r) => {
            if (!r.ok) {
              const d = await r.json().catch(() => ({}));
              throw new Error(d.error ?? `Stage "${s.label}" falhou ao salvar`);
            }
          })
        )
      );

      await Promise.all(ops);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-md p-6 max-h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-normal text-[#111111] mb-3" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>
          Editar Funil
        </h3>
        <div className="mb-4">
          <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome do Funil</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
          />
        </div>

        {error && (
          <div className="bg-[#fee2e2] border border-[#fca5a5] rounded-[6px] px-3 py-2 text-[13px] text-[#991b1b] mb-3">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Stages</p>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext items={stages.map((s) => s.id)} strategy={verticalListSortingStrategy}>
              {stages.map((stage) => (
                <SortableStageRow key={stage.id} stage={stage} onChange={handleChange} onDelete={handleDelete} />
              ))}
            </SortableContext>
          </DndContext>
          <button type="button" onClick={handleAddStage}
            className="w-full border border-dashed border-[#dedbd6] text-[13px] text-[#7b7b78] py-2.5 rounded-[6px] hover:border-[#111111] hover:text-[#111111] transition-colors flex items-center justify-center gap-2"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
            </svg>
            Adicionar Stage
          </button>
        </div>

        <div className="flex gap-2 justify-end pt-4 border-t border-[#dedbd6] mt-4">
          <button type="button" onClick={onClose} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">
            Cancelar
          </button>
          <button onClick={handleSave} disabled={saving} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50">
            {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}
