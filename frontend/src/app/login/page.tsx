"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const supabase = createClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      setError("Email ou senha incorretos");
      setLoading(false);
      return;
    }

    router.push("/dashboard");
  }

  return (
    <div className="min-h-screen bg-[#faf9f6] flex items-center justify-center">
      <div className="bg-white border border-[#dedbd6] rounded-[8px] p-8 w-full max-w-sm">
        <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111] mb-2">
          ValerIA<span className="text-[#ff5600]">·</span>
        </h1>
        <p className="text-[14px] text-[#7b7b78] mb-6">Entre na sua conta</p>

        {error && (
          <p className="text-[14px] text-[#c41c1c] mb-4 text-center">{error}</p>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Email</label>
            <input
              type="email"
              placeholder="seu@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
              required
            />
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Senha</label>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
              required
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
          >
            {loading ? "Entrando..." : "Entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}
