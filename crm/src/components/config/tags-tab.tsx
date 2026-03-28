"use client";

import { useState, useEffect } from "react";
import type { Tag } from "@/lib/types";

export function TagsTab() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState("#8b5cf6");
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState("");

  useEffect(() => {
    fetchTags();
  }, []);

  async function fetchTags() {
    const res = await fetch("/api/tags");
    if (res.ok) {
      const data = await res.json();
      setTags(data);
    }
    setLoading(false);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;

    const res = await fetch("/api/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim(), color: newColor }),
    });

    if (res.ok) {
      setNewName("");
      setNewColor("#8b5cf6");
      setShowForm(false);
      fetchTags();
    }
  }

  async function handleEdit(id: string) {
    if (!editName.trim()) return;

    const res = await fetch(`/api/tags/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: editName.trim(), color: editColor }),
    });

    if (res.ok) {
      setEditingId(null);
      fetchTags();
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Excluir esta tag? Ela sera removida de todos os leads.")) return;

    const res = await fetch(`/api/tags/${id}`, { method: "DELETE" });
    if (res.ok) {
      fetchTags();
    }
  }

  function startEdit(tag: Tag) {
    setEditingId(tag.id);
    setEditName(tag.name);
    setEditColor(tag.color);
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-6">
        <div className="w-4 h-4 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
        <p className="text-[#5f6368] text-[13px]">Carregando tags...</p>
      </div>
    );
  }

  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-[16px] font-semibold text-[#1f1f1f]">Tags</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="btn-primary flex items-center gap-1.5 px-4 py-2 rounded-xl text-[13px] font-medium"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="7" y1="2" x2="7" y2="12" />
            <line x1="2" y1="7" x2="12" y2="7" />
          </svg>
          Nova Tag
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="flex items-center gap-3 mb-5 p-4 bg-[#f6f7ed] rounded-xl">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Nome da tag"
            className="input-field flex-1"
            autoFocus
          />
          <input
            type="color"
            value={newColor}
            onChange={(e) => setNewColor(e.target.value)}
            className="w-10 h-10 rounded-lg cursor-pointer border border-[#e5e5dc] p-0.5"
          />
          <button
            type="submit"
            className="btn-primary px-4 py-2 rounded-xl text-[13px] font-medium"
          >
            Salvar
          </button>
          <button
            type="button"
            onClick={() => setShowForm(false)}
            className="btn-secondary px-4 py-2 rounded-xl text-[13px] font-medium"
          >
            Cancelar
          </button>
        </form>
      )}

      <div className="space-y-2">
        {tags.length === 0 && (
          <p className="text-[#9ca3af] text-[13px] py-4">Nenhuma tag criada ainda.</p>
        )}
        {tags.map((tag) => (
          <div key={tag.id} className="flex items-center gap-2">
            {editingId === tag.id ? (
              <div className="flex items-center gap-3 flex-1 p-3 bg-[#f6f7ed] rounded-xl">
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="input-field flex-1"
                  autoFocus
                />
                <input
                  type="color"
                  value={editColor}
                  onChange={(e) => setEditColor(e.target.value)}
                  className="w-10 h-10 rounded-lg cursor-pointer border border-[#e5e5dc] p-0.5"
                />
                <button
                  onClick={() => handleEdit(tag.id)}
                  className="btn-primary px-4 py-2 rounded-xl text-[13px] font-medium"
                >
                  Salvar
                </button>
                <button
                  onClick={() => setEditingId(null)}
                  className="btn-secondary px-4 py-2 rounded-xl text-[13px] font-medium"
                >
                  Cancelar
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-3 flex-1 py-2">
                <span
                  className="inline-flex items-center px-3 py-1 rounded-full text-[13px] text-white font-medium"
                  style={{ backgroundColor: tag.color }}
                >
                  {tag.name}
                </span>
                <div className="flex items-center gap-1 ml-auto">
                  <button
                    onClick={() => startEdit(tag)}
                    className="p-2 rounded-lg text-[#9ca3af] hover:text-[#1f1f1f] hover:bg-[#f6f7ed] transition-colors"
                    title="Editar"
                  >
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                  </button>
                  <button
                    onClick={() => handleDelete(tag.id)}
                    className="p-2 rounded-lg text-[#9ca3af] hover:text-red-500 hover:bg-red-50 transition-colors"
                    title="Excluir"
                  >
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      <line x1="10" y1="11" x2="10" y2="17" />
                      <line x1="14" y1="11" x2="14" y2="17" />
                    </svg>
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
