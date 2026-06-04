"use client";

import { useCallback, useEffect, useState } from "react";
import { picardApi } from "@/lib/picardApi";
import { OnboardingWizard } from "./OnboardingWizard";

export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const [needsOnboarding, setNeedsOnboarding] = useState<boolean | null>(null);

  const refresh = useCallback(() => {
    picardApi
      .getOnboardingStatus()
      .then((s) => setNeedsOnboarding(s.needs_onboarding))
      .catch(() => setNeedsOnboarding(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (needsOnboarding === null) return <>{children}</>;
  return (
    <>
      {children}
      {needsOnboarding && (
        <OnboardingWizard
          onComplete={() => {
            setNeedsOnboarding(false);
            refresh();
          }}
        />
      )}
    </>
  );
}
