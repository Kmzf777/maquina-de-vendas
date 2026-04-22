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
    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
      <h2 className="text-[14px] font-normal text-[#111111] mb-4">Perfil</h2>

      <div className="mb-4">
        <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Email</label>
        <p className="text-[14px] text-[#111111]">{email}</p>
      </div>

      <form onSubmit={handlePasswordChange}>
        <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nova senha</label>
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full mb-3"
          placeholder="Deixe vazio para manter"
        />
        <button
          type="submit"
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
        >
          Atualizar senha
        </button>
        {message && (
          <p className="text-[14px] text-[#0bdf50] mt-2">{message}</p>
        )}
      </form>
    </div>
  );
}
