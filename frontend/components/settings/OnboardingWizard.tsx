"use client";

import { useCallback, useEffect, useState } from "react";
import { picardApi } from "@/lib/picardApi";

type Props = {
  onComplete: () => void;
};

export function OnboardingWizard({ onComplete }: Props) {
  const [step, setStep] = useState(0);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-4o-mini");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434");
  const [openaiKey, setOpenaiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [useDefaults, setUseDefaults] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [components, setComponents] = useState<
    Awaited<ReturnType<typeof picardApi.getComponents>>["components"]
  >([]);

  useEffect(() => {
    picardApi.getComponents().then((r) => setComponents(r.components)).catch(() => {});
  }, []);

  const finish = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      if (!useDefaults) {
        await picardApi.updateSettings({
          llm_provider: provider,
          llm_model: model,
          ollama_base_url: ollamaUrl,
        });
      } else {
        await picardApi.updateSettings({
          llm_provider: provider,
          llm_model: provider === "ollama" ? model : "gpt-4o-mini",
          ollama_base_url: ollamaUrl,
        });
      }
      const secrets: { openai_api_key?: string; anthropic_api_key?: string } = {};
      if (provider === "openai" && openaiKey.trim()) secrets.openai_api_key = openaiKey.trim();
      if (provider === "anthropic" && anthropicKey.trim()) secrets.anthropic_api_key = anthropicKey.trim();
      if (Object.keys(secrets).length) await picardApi.updateSecrets(secrets);
      await picardApi.updateSettings({ onboarding_complete: true });
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Setup failed");
    } finally {
      setBusy(false);
    }
  }, [useDefaults, provider, model, ollamaUrl, openaiKey, anthropicKey, onComplete]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-neutral-200 bg-white p-6 shadow-xl">
        <h2 className="font-serif text-xl text-neutral-900">Welcome to Picard OSS</h2>
        <p className="mt-1 text-sm text-neutral-600">
          Configure locally on your machine. API keys are stored encrypted and never sent to picard.law.
        </p>

        {step === 0 && (
          <div className="mt-6 space-y-4">
            <label className="block text-sm font-medium text-neutral-800">LLM provider</label>
            <select
              className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="ollama">Ollama (local)</option>
            </select>
            {provider === "ollama" ? (
              <>
                <input
                  className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
                  placeholder="Model (e.g. llama3.2)"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
                <input
                  className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
                  value={ollamaUrl}
                  onChange={(e) => setOllamaUrl(e.target.value)}
                />
              </>
            ) : (
              <>
                <input
                  className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
                  placeholder="Model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
                <input
                  type="password"
                  className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
                  placeholder={provider === "openai" ? "OpenAI API key" : "Anthropic API key"}
                  value={provider === "openai" ? openaiKey : anthropicKey}
                  onChange={(e) =>
                    provider === "openai"
                      ? setOpenaiKey(e.target.value)
                      : setAnthropicKey(e.target.value)
                  }
                />
              </>
            )}
            <label className="flex items-center gap-2 text-sm text-neutral-700">
              <input
                type="checkbox"
                checked={useDefaults}
                onChange={(e) => setUseDefaults(e.target.checked)}
              />
              Use recommended defaults for retrieval and CARP
            </label>
            <button
              type="button"
              className="w-full rounded bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-800"
              onClick={() => setStep(1)}
            >
              Continue
            </button>
          </div>
        )}

        {step === 1 && (
          <div className="mt-6 space-y-3">
            <p className="text-sm text-neutral-600">Optional components (can install later in Settings):</p>
            {components.map((c) => (
              <div key={c.id} className="rounded border border-neutral-200 p-3 text-sm">
                <div className="font-medium">{c.name}</div>
                <p className="text-neutral-600">{c.description}</p>
                <button
                  type="button"
                  className="mt-2 text-xs text-neutral-800 underline"
                  onClick={async () => {
                    try {
                      await picardApi.installComponent(c.id);
                    } catch {
                      /* hint only */
                    }
                  }}
                >
                  Try install
                </button>
              </div>
            ))}
            <button
              type="button"
              disabled={busy}
              className="w-full rounded bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-800 disabled:opacity-50"
              onClick={() => void finish()}
            >
              {busy ? "Saving…" : "Finish setup"}
            </button>
          </div>
        )}

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>
    </div>
  );
}
