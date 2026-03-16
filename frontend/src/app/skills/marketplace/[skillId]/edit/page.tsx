import { redirect } from "next/navigation";

type EditMarketplaceSkillPageProps = {
  params: Promise<{ skillId: string }>;
};

export default async function EditMarketplaceSkillPage({
  params,
}: EditMarketplaceSkillPageProps) {
  await params;
  redirect("/skills/marketplace");
}
