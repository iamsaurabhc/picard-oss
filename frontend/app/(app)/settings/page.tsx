"use client";

import { useCallback, useEffect, useState } from "react";
import {
  checkDesktopUpdates,
  installDesktopUpdate,
  isTauriDesktop,
  type DesktopUpdateInfo,
} from "@/lib/desktopUpdates";
import { picardApi, type AppComponent, type AppSettings, type UpdateCheck } from "@/lib/picardApi";
import { isVersionNewer } from "@/lib/version";

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [components, setComponents] = useState<AppComponent[]>([]);
  const [updateInfo, setUpdateInfo] = useState<UpdateCheck | null>(null);
  const [desktopUpdate, setDesktopUpdate] = useState<DesktopUpdateInfo | null>(null);
  const [openaiKey, setOpenaiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [s, c] = await Promise.all([picardApi.getSettings(), picardApi.getComponents()]);
    setSettings(s);
    setComponents(c.components);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    picardApi
      .checkForUpdates()
      .then((u) => {
        if (!cancelled) setUpdateInfo(u);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!settings) {
    return <div className="p-8 text-sm text-neutral-500">Loading settings…</div>;
  }

  async function savePrefs() {
    const s = settings;
    if (!s) return;
    setBusy(true);
    setMessage(null);
    try {
      const next = await picardApi.updateSettings({
        llm_provider: s.llm_provider,
        llm_model: s.llm_model,
        ollama_base_url: s.ollama_base_url,
        enable_carp: s.enable_carp,
        enable_llm_query_understanding: s.enable_llm_query_understanding,
        enable_context_ranker: s.enable_context_ranker,
        enable_ner_entity_extract: s.enable_ner_entity_extract,
        enable_slm_entity_extract: s.enable_slm_entity_extract,
        show_prompts_in_chat: s.show_prompts_in_chat,
        agent_profile: s.agent_profile,
        update_channel: s.update_channel,
      });
      setSettings(next);
      setMessage("Settings saved.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveSecrets() {
    setBusy(true);
    try {
      await picardApi.updateSecrets({
        openai_api_key: openaiKey || undefined,
        anthropic_api_key: anthropicKey || undefined,
      });
      setOpenaiKey("");
      setAnthropicKey("");
      await load();
      setMessage("API keys updated.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Failed to save keys");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-2xl p-8">
      <h1 className="font-serif text-2xl text-neutral-900">Settings</h1>
      <p className="mt-1 text-sm text-neutral-600">
        v{settings.version} · Data: {settings.picard_data_dir}
      </p>

      {updateInfo?.update_available &&
        isVersionNewer(updateInfo.latest_version, updateInfo.current_version) && (
        <div className="mt-4 rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm">
          Update available: v{updateInfo.latest_version}
          {updateInfo.download_url && (
            <a
              href={updateInfo.download_url}
              className="ml-2 font-medium text-amber-900 underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              Download
            </a>
          )}
        </div>
      )}

      <section className="mt-8 space-y-3">
        <h2 className="text-sm font-medium text-neutral-800">LLM</h2>
        <select
          className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
          value={settings.llm_provider}
          onChange={(e) => setSettings({ ...settings, llm_provider: e.target.value })}
        >
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="ollama">Ollama</option>
        </select>
        <input
          className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
          value={settings.llm_model}
          onChange={(e) => setSettings({ ...settings, llm_model: e.target.value })}
        />
        {!settings.llm_configured && (
          <p className="text-sm text-amber-700">LLM not configured — add an API key or use Ollama.</p>
        )}
        <input
          type="password"
          placeholder={settings.openai_api_key_set ? "OpenAI key (set — enter to replace)" : "OpenAI API key"}
          className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
          value={openaiKey}
          onChange={(e) => setOpenaiKey(e.target.value)}
        />
        <input
          type="password"
          placeholder={
            settings.anthropic_api_key_set ? "Anthropic key (set)" : "Anthropic API key"
          }
          className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
          value={anthropicKey}
          onChange={(e) => setAnthropicKey(e.target.value)}
        />
        <button
          type="button"
          className="rounded border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-50"
          onClick={() => void saveSecrets()}
          disabled={busy}
        >
          Save API keys
        </button>
      </section>

      <section className="mt-8 space-y-3">
        <h2 className="text-sm font-medium text-neutral-800">Deployment profile</h2>
        <p className="text-xs text-neutral-500">
          Filters built-in workflows in the library (firm vs court).
        </p>
        <select
          className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
          value={settings.agent_profile}
          onChange={(e) => setSettings({ ...settings, agent_profile: e.target.value })}
        >
          <option value="firm">Firm</option>
          <option value="court">Court</option>
        </select>
      </section>

      <section className="mt-8 space-y-2">
        <h2 className="text-sm font-medium text-neutral-800">Features</h2>
        {(
          [
            ["enable_carp", "CARP multi-constraint retrieval"],
            ["enable_llm_query_understanding", "LLM query understanding"],
            ["enable_context_ranker", "Context ranker"],
            ["enable_slm_entity_extract", "SLM entity extraction"],
            ["enable_ner_entity_extract", "GLiNER NER (requires model)"],
            ["show_prompts_in_chat", "Show pipeline prompts in chat"],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings[key]}
              onChange={(e) => setSettings({ ...settings, [key]: e.target.checked })}
            />
            {label}
          </label>
        ))}
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-neutral-800">Optional components</h2>
        <div className="mt-2 space-y-2">
          {components.map((c) => (
            <div key={c.id} className="flex items-center justify-between rounded border border-neutral-200 px-3 py-2 text-sm">
              <span>
                {c.name} {c.installed ? "✓" : ""}
              </span>
              <button
                type="button"
                className="text-xs underline"
                onClick={async () => {
                  await picardApi.installComponent(c.id);
                  await load();
                }}
              >
                Install
              </button>
            </div>
          ))}
        </div>
      </section>

      <div className="mt-8 flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-800 disabled:opacity-50"
          onClick={() => void savePrefs()}
          disabled={busy}
        >
          Save settings
        </button>
        <button
          type="button"
          className="rounded border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-50"
          onClick={async () => {
            await picardApi.resetSettings(true);
            await load();
            setMessage("Reset to defaults (keys kept).");
          }}
        >
          Reset to defaults
        </button>
        <button
          type="button"
          className="rounded border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-50"
          onClick={async () => {
            const u = await picardApi.checkForUpdates();
            setUpdateInfo(u);
            if (isTauriDesktop()) {
              setDesktopUpdate(await checkDesktopUpdates());
            }
          }}
        >
          Check for updates
        </button>
        {desktopUpdate && (
          <button
            type="button"
            className="rounded border border-neutral-800 px-4 py-2 text-sm hover:bg-neutral-50"
            onClick={() => void installDesktopUpdate()}
          >
            Install {desktopUpdate.version}
          </button>
        )}
      </div>
      {desktopUpdate && (
        <p className="mt-2 text-sm text-neutral-600">
          Desktop update available: {desktopUpdate.currentVersion} → {desktopUpdate.version}
        </p>
      )}

      {message && <p className="mt-4 text-sm text-neutral-600">{message}</p>}
    </div>
  );
}
