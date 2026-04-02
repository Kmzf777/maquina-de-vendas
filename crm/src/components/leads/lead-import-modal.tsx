"use client";

import { useState, useRef } from "react";
import Papa from "papaparse";

const LEAD_FIELDS = [
  { key: "", label: "Pular coluna" },
  { key: "phone", label: "Telefone" },
  { key: "name", label: "Nome" },
  { key: "email", label: "Email" },
  { key: "instagram", label: "Instagram" },
  { key: "company", label: "Empresa" },
  { key: "cnpj", label: "CNPJ" },
  { key: "razao_social", label: "Razao Social" },
  { key: "nome_fantasia", label: "Nome Fantasia" },
  { key: "endereco", label: "Endereco" },
  { key: "telefone_comercial", label: "Telefone Comercial" },
  { key: "stage", label: "Stage" },
];

const AUTO_MAP: Record<string, string> = {
  telefone: "phone", phone: "phone", celular: "phone", whatsapp: "phone",
  nome: "name", name: "name",
  email: "email", "e-mail": "email",
  instagram: "instagram",
  empresa: "company", company: "company",
  cnpj: "cnpj",
  "razao social": "razao_social", razao_social: "razao_social",
  "nome fantasia": "nome_fantasia", nome_fantasia: "nome_fantasia",
  endereco: "endereco", address: "endereco",
  "telefone comercial": "telefone_comercial",
  stage: "stage", etapa: "stage",
};

interface LeadImportModalProps {
  onClose: () => void;
  onImportDone: () => void;
}

type Step = "upload" | "mapping" | "confirm";

export function LeadImportModal({ onClose, onImportDone }: LeadImportModalProps) {
  const [step, setStep] = useState<Step>("upload");
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [mapping, setMapping] = useState<Record<number, string>>({});
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<{ inserted: number; updated: number; skipped: number } | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function handleFile(file: File) {
    Papa.parse(file, {
      skipEmptyLines: true,
      complete: (results) => {
        const data = results.data as string[][];
        if (data.length < 2) return;
        const headers = data[0];
        setCsvHeaders(headers);
        setCsvRows(data.slice(1));

        const autoMapping: Record<number, string> = {};
        headers.forEach((h, i) => {
          const normalized = h.toLowerCase().trim();
          if (AUTO_MAP[normalized]) {
            autoMapping[i] = AUTO_MAP[normalized];
          }
        });
        setMapping(autoMapping);
        setStep("mapping");
      },
    });
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".csv")) handleFile(file);
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  async function handleImport() {
    setImporting(true);

    const leads = csvRows.map((row) => {
      const lead: Record<string, string> = {};
      Object.entries(mapping).forEach(([colIdx, field]) => {
        if (field) {
          lead[field] = row[Number(colIdx)] || "";
        }
      });
      return lead;
    }).filter((l) => l.phone);

    const res = await fetch("/api/leads/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leads, skipDuplicates }),
    });
    const data = await res.json();
    setResult(data);
    setImporting(false);
    onImportDone();
  }

  const phoneColumnMapped = Object.values(mapping).includes("phone");

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-12" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative bg-white rounded-2xl w-full max-w-[640px] overflow-hidden shadow-[0_25px_50px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-[#f3f3f0] flex justify-between items-center">
          <h3 className="text-[18px] font-semibold text-[#1f1f1f]">Importar Leads (CSV)</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-lg border border-[#e5e5dc] flex items-center justify-center text-[#9ca3af] hover:text-[#1f1f1f]">
            x
          </button>
        </div>

        {/* Steps indicator */}
        <div className="px-6 py-3 flex items-center gap-2 text-[12px] border-b border-[#f3f3f0]">
          {(["Upload", "Mapeamento", "Confirmacao"] as const).map((label, i) => {
            const stepKeys: Step[] = ["upload", "mapping", "confirm"];
            const isActive = stepKeys.indexOf(step) >= i;
            return (
              <div key={label} className="flex items-center gap-2">
                {i > 0 && <span className="text-[#e5e5dc]">&rarr;</span>}
                <span className={`px-2.5 py-0.5 rounded-full ${isActive ? "bg-[#1f1f1f] text-white" : "bg-[#f4f4f0] text-[#9ca3af]"}`}>
                  {i + 1}. {label}
                </span>
              </div>
            );
          })}
        </div>

        <div className="p-6 max-h-[450px] overflow-y-auto">

          {/* Step 1: Upload */}
          {step === "upload" && (
            <div
              className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors ${
                dragActive ? "border-[#c8cc8e] bg-[#f6f7ed]" : "border-[#e5e5dc]"
              }`}
              onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
            >
              <p className="text-[14px] text-[#5f6368] mb-2">Arraste um arquivo CSV aqui</p>
              <p className="text-[12px] text-[#9ca3af] mb-4">ou</p>
              <button
                onClick={() => fileRef.current?.click()}
                className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333]"
              >
                Selecionar arquivo
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".csv"
                onChange={handleFileInput}
                className="hidden"
              />
            </div>
          )}

          {/* Step 2: Mapping */}
          {step === "mapping" && (
            <div>
              <p className="text-[13px] text-[#5f6368] mb-4">
                {csvRows.length} linhas encontradas. Mapeie as colunas do CSV para os campos do lead:
              </p>
              <div className="space-y-2 mb-4">
                {csvHeaders.map((header, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="text-[13px] text-[#1f1f1f] w-40 truncate font-medium">{header}</span>
                    <span className="text-[#9ca3af]">&rarr;</span>
                    <select
                      value={mapping[i] || ""}
                      onChange={(e) => setMapping((prev) => ({ ...prev, [i]: e.target.value }))}
                      className="flex-1 text-[13px] px-3 py-1.5 rounded-lg border border-[#e5e5dc] outline-none bg-white"
                    >
                      {LEAD_FIELDS.map((f) => (
                        <option key={f.key} value={f.key}>{f.label}</option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>

              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase mb-2">Preview (5 primeiras linhas)</p>
              <div className="overflow-x-auto border border-[#e5e5dc] rounded-lg">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-[#f6f7ed]">
                      {csvHeaders.map((h, i) => (
                        <th key={i} className="px-2 py-1.5 text-left text-[#9ca3af] font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {csvRows.slice(0, 5).map((row, i) => (
                      <tr key={i} className="border-t border-[#f3f3f0]">
                        {row.map((cell, j) => (
                          <td key={j} className="px-2 py-1 text-[#5f6368] truncate max-w-[120px]">{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex justify-end mt-4">
                <button
                  onClick={() => setStep("confirm")}
                  disabled={!phoneColumnMapped}
                  className="px-5 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] disabled:opacity-50"
                >
                  Proximo
                </button>
              </div>
              {!phoneColumnMapped && (
                <p className="text-[12px] text-[#ef4444] mt-2 text-right">Mapeie pelo menos a coluna de telefone.</p>
              )}
            </div>
          )}

          {/* Step 3: Confirm */}
          {step === "confirm" && !result && (
            <div>
              <div className="bg-[#f6f7ed] rounded-xl p-5 mb-4">
                <p className="text-[14px] font-semibold text-[#1f1f1f] mb-2">Resumo da importacao</p>
                <p className="text-[13px] text-[#5f6368]">{csvRows.length} leads serao processados</p>
                <p className="text-[13px] text-[#5f6368]">
                  Campos mapeados: {Object.values(mapping).filter(Boolean).join(", ")}
                </p>
              </div>

              <label className="flex items-center gap-2 mb-4 cursor-pointer">
                <input
                  type="checkbox"
                  checked={skipDuplicates}
                  onChange={(e) => setSkipDuplicates(e.target.checked)}
                  className="rounded"
                />
                <span className="text-[13px] text-[#5f6368]">
                  Pular leads duplicados (mesmo telefone). Desmarque para atualizar dados existentes.
                </span>
              </label>

              <div className="flex justify-between">
                <button
                  onClick={() => setStep("mapping")}
                  className="px-4 py-2 rounded-lg border border-[#e5e5dc] text-[13px] text-[#5f6368] hover:bg-[#f6f7ed]"
                >
                  Voltar
                </button>
                <button
                  onClick={handleImport}
                  disabled={importing}
                  className="px-5 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] disabled:opacity-50"
                >
                  {importing ? "Importando..." : "Importar"}
                </button>
              </div>
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="text-center py-6">
              <p className="text-[18px] font-semibold text-[#1f1f1f] mb-3">Importacao concluida!</p>
              <div className="flex justify-center gap-6 mb-5">
                <div>
                  <p className="text-[24px] font-bold text-[#4ade80]">{result.inserted}</p>
                  <p className="text-[12px] text-[#9ca3af]">Inseridos</p>
                </div>
                <div>
                  <p className="text-[24px] font-bold text-[#e8d44d]">{result.updated}</p>
                  <p className="text-[12px] text-[#9ca3af]">Atualizados</p>
                </div>
                <div>
                  <p className="text-[24px] font-bold text-[#9ca3af]">{result.skipped}</p>
                  <p className="text-[12px] text-[#9ca3af]">Pulados</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="px-5 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333]"
              >
                Fechar
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
