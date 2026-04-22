"use client";

import type { Broadcast, Cadence } from "@/lib/types";
import { BroadcastList } from "./broadcast-list";
import { CadenceList } from "./cadence-list";

interface CampaignsTabsProps {
  broadcasts: Broadcast[];
  cadences: Cadence[];
  onRefreshBroadcasts: () => void;
  activeTab: "disparos" | "cadencias";
}

export function CampaignsTabs({ broadcasts, cadences, onRefreshBroadcasts, activeTab }: CampaignsTabsProps) {
  if (activeTab === "cadencias") {
    return <CadenceList cadences={cadences} />;
  }
  return <BroadcastList broadcasts={broadcasts} onRefresh={onRefreshBroadcasts} />;
}
