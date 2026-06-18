import { describe, it, expect } from "vitest";
import {
  canWriteDealsInPipeline,
  canManagePipeline,
  resolvePipelineOwnerOnCreate,
} from "@/lib/supabase/pipeline-access";

const admin = { userId: "u-admin", role: "admin" };
const joao = { userId: "u-joao", role: "vendedor" };
const maria = { userId: "u-maria", role: "vendedor" };

const joaoPipeline = { owner_user_id: "u-joao", is_universal: false };
const adminPipeline = { owner_user_id: null, is_universal: false };
const blacklist = { owner_user_id: null, is_universal: true };

describe("canWriteDealsInPipeline", () => {
  it("admin escreve em qualquer funil", () => {
    expect(canWriteDealsInPipeline(admin, joaoPipeline)).toBe(true);
    expect(canWriteDealsInPipeline(admin, adminPipeline)).toBe(true);
    expect(canWriteDealsInPipeline(admin, blacklist)).toBe(true);
  });
  it("vendedor escreve no próprio funil", () => {
    expect(canWriteDealsInPipeline(joao, joaoPipeline)).toBe(true);
  });
  it("vendedor NÃO escreve no funil de outro vendedor", () => {
    expect(canWriteDealsInPipeline(maria, joaoPipeline)).toBe(false);
  });
  it("vendedor NÃO escreve em funil administrativo", () => {
    expect(canWriteDealsInPipeline(joao, adminPipeline)).toBe(false);
  });
  it("qualquer vendedor escreve no funil universal (Blacklist)", () => {
    expect(canWriteDealsInPipeline(maria, blacklist)).toBe(true);
  });
});

describe("canManagePipeline", () => {
  it("admin gerencia qualquer funil", () => {
    expect(canManagePipeline(admin, blacklist)).toBe(true);
    expect(canManagePipeline(admin, adminPipeline)).toBe(true);
  });
  it("vendedor gerencia o próprio funil", () => {
    expect(canManagePipeline(joao, joaoPipeline)).toBe(true);
  });
  it("vendedor NÃO gerencia funil universal (não exclui/renomeia Blacklist)", () => {
    expect(canManagePipeline(maria, blacklist)).toBe(false);
  });
  it("vendedor NÃO gerencia funil de outro nem administrativo", () => {
    expect(canManagePipeline(maria, joaoPipeline)).toBe(false);
    expect(canManagePipeline(joao, adminPipeline)).toBe(false);
  });
});

describe("resolvePipelineOwnerOnCreate", () => {
  it("vendedor sempre vira dono (ignora o solicitado)", () => {
    expect(resolvePipelineOwnerOnCreate(joao, null)).toBe("u-joao");
    expect(resolvePipelineOwnerOnCreate(joao, "u-maria")).toBe("u-joao");
  });
  it("admin usa o dono solicitado", () => {
    expect(resolvePipelineOwnerOnCreate(admin, "u-joao")).toBe("u-joao");
  });
  it("admin sem seleção cria funil administrativo (null)", () => {
    expect(resolvePipelineOwnerOnCreate(admin, null)).toBeNull();
    expect(resolvePipelineOwnerOnCreate(admin, undefined)).toBeNull();
  });
});
