"use client";

import { useState, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";

export function PasswordTab() {
  const supabase = createClient();
  const [email, setEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (user?.email) setEmail(user.email);
    });
  }, []);

  async function handlePasswordChange(e: React.FormEvent) {
    e.preventDefault();
    if (!newPassword) return;

    const { error } = await supabase.auth.updateUser({
      password: newPassword,
    });

    if (error) {
      setMessage("Erro ao atualizar senha");
    } else {
      setMessage("Senha atualizada");
      setNewPassword("");
    }
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <h2 className="font-medium text-gray-900 mb-4">Perfil</h2>

      <div className="mb-4">
        <label className="block text-sm text-gray-500 mb-1">Email</label>
        <p className="text-gray-900">{email}</p>
      </div>

      <form onSubmit={handlePasswordChange}>
        <label className="block text-sm text-gray-500 mb-1">Nova senha</label>
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 mb-3"
          placeholder="Deixe vazio para manter"
        />
        <button
          type="submit"
          className="bg-gray-900 text-white px-4 py-2 rounded text-sm hover:bg-gray-800"
        >
          Atualizar senha
        </button>
        {message && (
          <p className="text-sm text-green-600 mt-2">{message}</p>
        )}
      </form>
    </div>
  );
}
