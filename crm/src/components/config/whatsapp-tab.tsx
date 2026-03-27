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
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <h2 className="font-medium text-gray-900 mb-4">Conexao WhatsApp</h2>

      {status === "checking" && (
        <p className="text-gray-500 text-sm">Verificando status...</p>
      )}

      {status === "connected" && (
        <div>
          <div className="flex items-center gap-2 mb-4">
            <span className="w-3 h-3 bg-green-500 rounded-full" />
            <span className="text-green-700 font-medium">Conectado</span>
          </div>
          {phoneNumber && (
            <p className="text-gray-600 text-sm mb-4">Numero: {phoneNumber}</p>
          )}
          <button
            onClick={handleDisconnect}
            className="border border-gray-300 text-gray-700 px-4 py-2 rounded text-sm hover:bg-gray-50"
          >
            Desconectar
          </button>
        </div>
      )}

      {status === "disconnected" && (
        <div>
          <div className="flex items-center gap-2 mb-4">
            <span className="w-3 h-3 bg-gray-400 rounded-full" />
            <span className="text-gray-500">Desconectado</span>
          </div>
          <button
            onClick={handleConnect}
            className="bg-gray-900 text-white px-4 py-2 rounded text-sm hover:bg-gray-800"
          >
            Conectar
          </button>
          {qrExpired && (
            <div className="mt-4">
              <p className="text-amber-600 text-sm mb-2">QR code expirado.</p>
              <button
                onClick={handleConnect}
                className="border border-gray-300 text-gray-700 px-3 py-1.5 rounded text-sm hover:bg-gray-50"
              >
                Gerar novo QR
              </button>
            </div>
          )}
        </div>
      )}

      {status === "connecting" && qrCode && (
        <div>
          <p className="text-gray-600 text-sm mb-3">
            Escaneie o QR code com seu WhatsApp:
          </p>
          <div className="bg-white p-4 rounded-lg border border-gray-200 inline-block">
            <img
              src={`data:image/png;base64,${qrCode}`}
              alt="QR Code WhatsApp"
              className="w-64 h-64"
            />
          </div>
          <p className="text-gray-400 text-xs mt-2">
            O QR code expira em 60 segundos.
          </p>
        </div>
      )}

      {status === "connecting" && !qrCode && (
        <p className="text-gray-500 text-sm">Gerando QR code...</p>
      )}

      {error && (
        <p className="text-red-600 text-sm mt-3">{error}</p>
      )}
    </div>
  );
}
