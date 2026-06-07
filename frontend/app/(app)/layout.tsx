import { AppShell } from "@/components/AppShell";
import { OnboardingGate } from "@/components/settings/OnboardingGate";

export const dynamic = "force-dynamic";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <OnboardingGate>
      <AppShell>{children}</AppShell>
    </OnboardingGate>
  );
}
