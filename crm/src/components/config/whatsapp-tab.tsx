"use client";

import { useState, useEffect, useRef } from "react";

type ConnectionStatus = "checking" | "disconnected" | "connecting" | "connected";

export function WhatsAppTab() {
  const [status, setStatus] = useState<ConnectionStatus>("checking");
  const [phoneNumber, setPhoneNumber] = useState<string | null>(null);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [qrExpired, setQrExpired] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    checkStatus();
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  async function checkStatus() {
    try {
      const res = await fetch("/api/evolution/status");
      const data = await res.json();
      if (data.connected) {
        setStatus("connected");
        setPhoneNumber(data.number || null);
        setQrCode(null);
        stopPolling();
      } else {
        setStatus("disconnected");
      }
    } catch {
      setStatus("disconnected");
    }
  }

  function startPolling() {
    stopPolling();
    pollingRef.current = setInterval(async () => {
      try {
        const res = await fetch("/api/evolution/status");
        const data = await res.json();
        if (data.connected) {
          setStatus("connected");
          setPhoneNumber(data.number || null);
          setQrCode(null);
          setQrExpired(false);
          stopPolling();
        }
      } catch {
        // keep polling
      }
    }, 3000);

    timeoutRef.current = setTimeout(() => {
      stopPolling();
      setQrExpired(true);
      setQrCode(null);
    }, 60000);
  }

  function stopPolling() {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }

  async function handleConnect() {
    setStatus("connecting");
    setError(null);
    setQrExpired(false);

    try {
      const res = await fetch("/api/evolution/connect", { method: "POST" });
      const data = await res.json();

      if (data.connected) {
        // Instance is already connected — no QR needed
        setStatus("connected");
        checkStatus();
        return;
      }

      if (data.qrcode) {
        setQrCode(data.qrcode);
        startPolling();
      } else {
        setError("Nao foi possivel gerar o QR code.");
        setStatus("disconnected");
      }
    } catch {
      setError("Erro ao conectar. Tente novamente.");
      setStatus("disconnected");
    }
  }

  async function handleDisconnect() {
    try {
      await fetch("/api/evolution/disconnect", { method: "POST" });
      setStatus("disconnected");
      setPhoneNumber(null);
      setQrCode(null);
    } catch {
      setError("Erro ao desconectar.");
    }
  }

  return (
    <div className="card p-6">
      <h2 className="text-[16px] font-semibold text-[#1f1f1f] mb-5">Conexao WhatsApp</h2>

      {status === "checking" && (
        <div className="flex items-center gap-3">
          <div className="w-4 h-4 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
          <p className="text-[#5f6368] text-[13px]">Verificando status...</p>
        </div>
      )}

      {status === "connected" && (
        <div>
          <div className="flex items-center gap-2.5 mb-4">
            <span className="w-2.5 h-2.5 bg-green-500 rounded-full ring-4 ring-green-500/20" />
            <span className="text-green-700 font-medium text-[14px]">Conectado</span>
          </div>
          {phoneNumber && (
            <p className="text-[#5f6368] text-[13px] mb-5">Numero: {phoneNumber}</p>
          )}
          <button
            onClick={handleDisconnect}
            className="btn-secondary px-5 py-2.5 rounded-xl text-[13px] font-medium"
          >
            Desconectar
          </button>
        </div>
      )}

      {status === "disconnected" && (
        <div>
          <div className="flex items-center gap-2.5 mb-4">
            <span className="w-2.5 h-2.5 bg-[#9ca3af] rounded-full ring-4 ring-[#9ca3af]/20" />
            <span className="text-[#5f6368] text-[14px]">Desconectado</span>
          </div>
          <button
            onClick={handleConnect}
            className="btn-primary px-5 py-2.5 rounded-xl text-[13px] font-medium"
          >
            Conectar
          </button>
          {qrExpired && (
            <div className="mt-5">
              <p className="text-amber-600 text-[13px] mb-3">QR code expirado.</p>
              <button
                onClick={handleConnect}
                className="btn-secondary px-4 py-2 rounded-xl text-[13px] font-medium"
              >
                Gerar novo QR
              </button>
            </div>
          )}
        </div>
      )}

      {status === "connecting" && qrCode && (
        <div>
          <p className="text-[#5f6368] text-[13px] mb-4">
            Escaneie o QR code com seu WhatsApp:
          </p>
          <div className="inline-flex flex-col items-center p-6 bg-white rounded-2xl border border-[#e5e5dc] shadow-sm">
            <img
              src={qrCode.startsWith("data:") ? qrCode : `data:image/png;base64,${qrCode}`}
              alt="QR Code WhatsApp"
              className="w-64 h-64"
            />
          </div>
          <p className="text-[#9ca3af] text-[12px] mt-3">
            O QR code expira em 60 segundos.
          </p>
        </div>
      )}

      {status === "connecting" && !qrCode && (
        <div className="flex items-center gap-3">
          <div className="w-4 h-4 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
          <p className="text-[#5f6368] text-[13px]">Gerando QR code...</p>
        </div>
      )}

      {error && (
        <p className="text-red-500 text-[13px] mt-4">{error}</p>
      )}
    </div>
  );
}
