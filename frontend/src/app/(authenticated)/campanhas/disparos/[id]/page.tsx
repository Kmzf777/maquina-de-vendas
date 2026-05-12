import { BroadcastDetail } from "@/components/campaigns/broadcast-detail";

interface BroadcastDetailPageProps {
  params: Promise<{ id: string }>;
}

export default async function BroadcastDetailPage({ params }: BroadcastDetailPageProps) {
  const { id } = await params;
  return <BroadcastDetail broadcastId={id} />;
}
