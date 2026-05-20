import { CadenceFlowBuilder } from "@/components/campaigns/cadence-flow-builder";

export default async function CadenceFlowPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CadenceFlowBuilder campaignId={id} />;
}
