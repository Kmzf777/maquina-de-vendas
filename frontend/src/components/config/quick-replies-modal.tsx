// frontend/src/components/config/quick-replies-modal.tsx
"use client";

import { useState, useEffect } from "react";
import type { QuickReply } from "@/lib/types";

interface Props {
  open: boolean;
  onClose: () => void;
  initialCreate?: boolean;
}

const VARIABLES = ["primeiro_nome", "nome_completo", "telefone", "empresa"];

export function QuickRepliesModal({ open, onClose, initialCreate = false }: Props) {
  const [items, setItems] = useState<QuickReply[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [shortcut, setShortcut] = useState("");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  useEffect(() => {
    if (!open) return;
    fetchItems();
    if (initialCreate) startCreate();
  }, [open, initialCreate]);

  async function fetchItems() {
    setLoading(true);
    const res = await fetch("/api/quick-replies");
    if (res.ok) setItems(await res.json());
    setLoading(false);
  }

  function resetForm() {
    setShortcut(""); setTitle(""); setContent(""); setEditingId(null); setShowForm(false);
  }
  function startCreate() { setShortcut(""); setTitle(""); setContent(""); setEditingId(null); setShowForm(true); }
  function startEdit(it: QuickReply) {
    setEditingId(it.id); setShortcut(it.shortcut ?? ""); setTitle(it.title); setContent(it.content); setShowForm(true);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !content.trim()) return;
    const payload = { shortcut: shortcut.trim() || null, title: title.trim(), content };
    const res = editingId
      ? await fetch(`/api/quick-replies/${editingId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
      : await fetch("/api/quick-replies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (res.ok) { resetForm(); fetchItems(); }
  }

  async function handleDelete(id: string) {
    if (!confirm("Excluir esta resposta rápida?")) return;
    const res = await fetch(`/api/quick-replies/${id}`, { method: "DELETE" });
    if (res.ok) fetchItems();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-[8px] border border-[#dedbd6] w-full max-w-2xl max-h-[85vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-[18px] font-normal text-[#111111]">Respostas Rápidas</h2>
          <button onClick={onClose} className="text-[#7b7b78] hover:text-[#111111] transition-colors" aria-label="Fechar">✕</button>
        </div>

        {!showForm && (
          <button
            onClick={startCreate}
            className="mb-5 bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
          >
            + Nova resposta
          </button>
        )}

        {showForm && (
          <form onSubmit={handleSubmit} className="mb-6 p-4 bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] space-y-3">
            <div className="flex gap-3">
              <input
                value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Título" autoFocus
                className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] focus:border-[#111111] focus:outline-none"
              />
              <input
                value={shortcut} onChange={(e) => setShortcut(e.target.value)} placeholder="atalho (opcional)"
                className="w-40 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] focus:border-[#111111] focus:outline-none"
              />
            </div>
            <textarea
              value={content} onChange={(e) => setContent(e.target.value)} placeholder="Mensagem... use {{primeiro_nome}} para personalizar"
              rows={4}
              className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] focus:border-[#111111] focus:outline-none resize-none"
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[12px] text-[#7b7b78]">Inserir variável:</span>
              {VARIABLES.map((v) => (
                <button
                  key={v} type="button" onClick={() => setContent((c) => c + `{{${v}}}`)}
                  className="text-[12px] px-2 py-1 rounded-[4px] border border-[#dedbd6] text-[#111111] hover:bg-[#faf9f6] transition-colors"
                >
                  {`{{${v}}}`}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <button type="submit" className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">
                {editingId ? "Salvar" : "Criar"}
              </button>
              <button type="button" onClick={resetForm} className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">
                Cancelar
              </button>
            </div>
          </form>
        )}

        {loading ? (
          <p className="text-[#7b7b78] text-[14px] py-4">Carregando...</p>
        ) : items.length === 0 ? (
          <p className="text-[#7b7b78] text-[14px] py-4">Nenhuma resposta rápida criada ainda.</p>
        ) : (
          <div className="space-y-2">
            {items.map((it) => (
              <div key={it.id} className="flex items-start gap-3 p-3 bg-white border border-[#dedbd6] rounded-[8px]">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[14px] text-[#111111] font-normal truncate">{it.title}</span>
                    {it.shortcut && <span className="text-[12px] text-[#7b7b78]">/{it.shortcut}</span>}
                  </div>
                  <p className="text-[13px] text-[#7b7b78] truncate">{it.content}</p>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button onClick={() => startEdit(it)} className="p-2 rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#faf9f6] transition-colors" title="Editar">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                  </button>
                  <button onClick={() => handleDelete(it.id)} className="p-2 rounded-[4px] text-[#7b7b78] hover:text-[#c41c1c] transition-colors" title="Excluir">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      <line x1="10" y1="11" x2="10" y2="17" />
                      <line x1="14" y1="11" x2="14" y2="17" />
                    </svg>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
