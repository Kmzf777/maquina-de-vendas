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
        <div className="w-4 h-4 border-2 border-[#dedbd6] border-t-transparent rounded-full animate-spin" />
        <p className="text-[#7b7b78] text-[14px]">Carregando tags...</p>
      </div>
    );
  }

  return (
    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-[14px] font-normal text-[#111111]">Tags</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
        >
          + Nova Tag
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="flex items-center gap-3 mb-5 p-4 bg-white border border-[#dedbd6] rounded-[8px]">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Nome da tag"
            className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none flex-1"
            autoFocus
          />
          <input
            type="color"
            value={newColor}
            onChange={(e) => setNewColor(e.target.value)}
            className="w-10 h-10 rounded-[4px] cursor-pointer border border-[#dedbd6] p-0.5"
          />
          <button
            type="submit"
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
          >
            Salvar
          </button>
          <button
            type="button"
            onClick={() => setShowForm(false)}
            className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
          >
            Cancelar
          </button>
        </form>
      )}

      <div className="space-y-2">
        {tags.length === 0 && (
          <p className="text-[#7b7b78] text-[14px] py-4">Nenhuma tag criada ainda.</p>
        )}
        {tags.map((tag) => (
          <div key={tag.id} className="flex items-center gap-2">
            {editingId === tag.id ? (
              <div className="flex items-center gap-3 flex-1 p-3 bg-white border border-[#dedbd6] rounded-[8px]">
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none flex-1"
                  autoFocus
                />
                <input
                  type="color"
                  value={editColor}
                  onChange={(e) => setEditColor(e.target.value)}
                  className="w-10 h-10 rounded-[4px] cursor-pointer border border-[#dedbd6] p-0.5"
                />
                <button
                  onClick={() => handleEdit(tag.id)}
                  className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
                >
                  Salvar
                </button>
                <button
                  onClick={() => setEditingId(null)}
                  className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
                >
                  Cancelar
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-3 flex-1 py-2">
                <span
                  className="inline-flex items-center px-3 py-1 rounded-[4px] text-[14px] text-white font-normal"
                  style={{ backgroundColor: tag.color }}
                >
                  {tag.name}
                </span>
                <div className="flex items-center gap-1 ml-auto">
                  <button
                    onClick={() => startEdit(tag)}
                    className="p-2 rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#faf9f6] transition-colors"
                    title="Editar"
                  >
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                  </button>
                  <button
                    onClick={() => handleDelete(tag.id)}
                    className="p-2 rounded-[4px] text-[#7b7b78] hover:text-[#c41c1c] transition-colors"
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
