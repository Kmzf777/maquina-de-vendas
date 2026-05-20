"use client";

import type { Broadcast, Campaign } from "@/lib/types";
import { BroadcastList } from "./broadcast-list";
import { CadenceList } from "./cadence-list";

interface CampaignsTabsProps {
  broadcasts: Broadcast[];
  campaigns: Campaign[];
  onRefreshBroadcasts: () => void;
  onRefreshCampaigns: () => void;
  activeTab: "disparos" | "cadencias";
}

export function CampaignsTabs({ broadcasts, campaigns, onRefreshBroadcasts, onRefreshCampaigns, activeTab }: CampaignsTabsProps) {
  if (activeTab === "cadencias") {
    return <CadenceList campaigns={campaigns} onRefresh={onRefreshCampaigns} />;
  }
  return <BroadcastList broadcasts={broadcasts} onRefresh={onRefreshBroadcasts} />;
}
