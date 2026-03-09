"use client";

import { useTranslations } from 'next-intl';
import { LandingHero } from "@/components/organisms/LandingHero";
import { LandingShell } from "@/components/templates/LandingShell";

export default function HomePage() {
  const t = useTranslations('Dashboard');
  
  return (
    <LandingShell>
      <LandingHero />
    </LandingShell>
  );
}
