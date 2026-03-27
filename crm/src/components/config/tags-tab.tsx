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
    if (!confirm("Excluir esta tag? Ela será removida de todos os leads.")) return;

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
    return <p className="text-gray-500 text-sm">Carregando tags...</p>;
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-medium text-gray-900">Tags</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-gray-900 text-white px-3 py-1.5 rounded text-sm hover:bg-gray-800"
        >
          + Nova Tag
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="flex items-center gap-2 mb-4 p-3 bg-gray-50 rounded">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Nome da tag"
            className="flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm text-gray-900"
            autoFocus
          />
          <input
            type="color"
            value={newColor}
            onChange={(e) => setNewColor(e.target.value)}
            className="w-8 h-8 rounded cursor-pointer border-0"
          />
          <button
            type="submit"
            className="bg-gray-900 text-white px-3 py-1.5 rounded text-sm hover:bg-gray-800"
          >
            Salvar
          </button>
          <button
            type="button"
            onClick={() => setShowForm(false)}
            className="text-gray-500 text-sm hover:text-gray-700"
          >
            Cancelar
          </button>
        </form>
      )}

      <div className="space-y-2">
        {tags.length === 0 && (
          <p className="text-gray-400 text-sm">Nenhuma tag criada ainda.</p>
        )}
        {tags.map((tag) => (
          <div key={tag.id} className="flex items-center gap-2">
            {editingId === tag.id ? (
              <div className="flex items-center gap-2 flex-1 p-2 bg-gray-50 rounded">
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm text-gray-900"
                  autoFocus
                />
                <input
                  type="color"
                  value={editColor}
                  onChange={(e) => setEditColor(e.target.value)}
                  className="w-8 h-8 rounded cursor-pointer border-0"
                />
                <button
                  onClick={() => handleEdit(tag.id)}
                  className="text-sm text-green-600 hover:text-green-800"
                >
                  Salvar
                </button>
                <button
                  onClick={() => setEditingId(null)}
                  className="text-sm text-gray-500 hover:text-gray-700"
                >
                  Cancelar
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2 flex-1">
                <span
                  className="inline-flex items-center px-3 py-1 rounded-full text-sm text-white"
                  style={{ backgroundColor: tag.color }}
                >
                  {tag.name}
                </span>
                <button
                  onClick={() => startEdit(tag)}
                  className="text-gray-400 hover:text-gray-600 text-sm"
                  title="Editar"
                >
                  &#9998;
                </button>
                <button
                  onClick={() => handleDelete(tag.id)}
                  className="text-gray-400 hover:text-red-600 text-sm"
                  title="Excluir"
                >
                  &#128465;
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
