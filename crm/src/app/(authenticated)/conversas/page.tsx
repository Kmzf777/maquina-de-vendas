"use client";

import { useState, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";
import { ChatList } from "@/components/conversas/chat-list";
import { ChatView } from "@/components/conversas/chat-view";
import { ContactDetail } from "@/components/conversas/contact-detail";
import type { EvolutionChat, Lead, Tag } from "@/lib/types";

export default function ConversasPage() {
  const supabase = createClient();
  const [chats, setChats] = useState<EvolutionChat[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, string[]>>({});
  const [selectedPhone, setSelectedPhone] = useState<string | null>(null);
  const [selectedPushName, setSelectedPushName] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("todos");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    await Promise.all([fetchChats(), fetchLeads(), fetchTags()]);
    setLoading(false);
  }

  async function fetchChats() {
    try {
      const res = await fetch("/api/evolution/chats");
      if (res.ok) {
        const data = await res.json();
        setChats(Array.isArray(data) ? data : []);
      }
    } catch {
      // ignore
    }
  }

  async function fetchLeads() {
    const { data } = await supabase
      .from("leads")
      .select("*")
      .order("last_msg_at", { ascending: false });
    if (data) {
      setLeads(data);
      // Fetch lead_tags for all leads
      const { data: ltData } = await supabase
        .from("lead_tags")
        .select("lead_id, tag_id");
      if (ltData) {
        const map: Record<string, string[]> = {};
        ltData.forEach((row: { lead_id: string; tag_id: string }) => {
          if (!map[row.lead_id]) map[row.lead_id] = [];
          map[row.lead_id].push(row.tag_id);
        });
        setLeadTagsMap(map);
      }
    }
  }

  async function fetchTags() {
    try {
      const res = await fetch("/api/tags");
      if (res.ok) {
        const data = await res.json();
        setTags(data);
      }
    } catch {
      // ignore
    }
  }

  function handleSelectChat(phone: string, pushName: string | null) {
    setSelectedPhone(phone);
    setSelectedPushName(pushName);
  }

  const selectedLead = selectedPhone
    ? leads.find((l) => l.phone === selectedPhone) || null
    : null;

  const selectedLeadTags = selectedLead
    ? tags.filter((t) => leadTagsMap[selectedLead.id]?.includes(t.id))
    : [];

  async function handleTagToggle(tagId: string, add: boolean) {
    if (!selectedLead) return;

    const currentTagIds = leadTagsMap[selectedLead.id] || [];
    const newTagIds = add
      ? [...currentTagIds, tagId]
      : currentTagIds.filter((id) => id !== tagId);

    const res = await fetch(`/api/leads/${selectedLead.id}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tagIds: newTagIds }),
    });

    if (res.ok) {
      setLeadTagsMap((prev) => ({ ...prev, [selectedLead.id]: newTagIds }));
    }
  }

  async function handleCreateLead() {
    if (!selectedPhone) return;

    const { data, error } = await supabase
      .from("leads")
      .insert({
        phone: selectedPhone,
        name: selectedPushName,
        status: "active",
        stage: "secretaria",
        seller_stage: "novo",
        human_control: true,
        channel: "evolution",
      })
      .select()
      .single();

    if (!error && data) {
      setLeads((prev) => [data, ...prev]);
    }
  }

  async function handleSellerStageChange(stage: string) {
    if (!selectedLead) return;

    await supabase
      .from("leads")
      .update({ seller_stage: stage })
      .eq("id", selectedLead.id);

    setLeads((prev) =>
      prev.map((l) =>
        l.id === selectedLead.id ? { ...l, seller_stage: stage } : l
      )
    );
  }

  function handleLeadCreated(lead: Lead) {
    setLeads((prev) => {
      if (prev.find((l) => l.id === lead.id)) return prev;
      return [lead, ...prev];
    });
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-950">
        <p className="text-gray-500">Carregando conversas...</p>
      </div>
    );
  }

  return (
    <div className="flex h-full bg-gray-950">
      <ChatList
        chats={chats}
        leads={leads}
        activeTab={activeTab}
        selectedPhone={selectedPhone}
        onSelectChat={handleSelectChat}
        onTabChange={setActiveTab}
      />

      {selectedPhone ? (
        <>
          <ChatView
            phone={selectedPhone}
            lead={selectedLead}
            tags={tags}
            pushName={selectedPushName}
            onLeadCreated={handleLeadCreated}
          />
          <ContactDetail
            phone={selectedPhone}
            pushName={selectedPushName}
            lead={selectedLead}
            tags={tags}
            leadTags={selectedLeadTags}
            onTagToggle={handleTagToggle}
            onCreateLead={handleCreateLead}
            onSellerStageChange={handleSellerStageChange}
          />
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center bg-gray-950">
          <div className="text-center">
            <p className="text-gray-500 text-lg">Selecione uma conversa</p>
            <p className="text-gray-600 text-sm mt-1">
              Escolha um contato para ver as mensagens
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
