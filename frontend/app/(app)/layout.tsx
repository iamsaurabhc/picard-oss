import { AppSidebar } from "@/components/app-sidebar";
import { OnboardingGate } from "@/components/settings/OnboardingGate";

export const dynamic = "force-dynamic";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <OnboardingGate>
      <div className="flex min-h-screen">
        <AppSidebar />
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </OnboardingGate>
  );
}
