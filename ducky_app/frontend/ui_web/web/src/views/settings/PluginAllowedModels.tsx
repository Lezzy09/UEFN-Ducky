import { useCallback, useEffect, useState } from "react";

import { ChoiceDropdown, type ChoiceOption } from "../../components/ChoiceDropdown";
import { getApi } from "../../hooks/usePanelApi";
import { Icons } from "../../icons/Icons";
import { GeneralSectionHeader } from "./GeneralSectionHeader";

/**
 * Allowed models for a plugin's sensitive tools (`agent.tools.sensitive`). Chats on any
 * other model don't see those tools and a call is refused. Empty = no agent gets them.
 */
export function PluginAllowedModels({ pluginId }: { pluginId: string }) {
  const [sensitive, setSensitive] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [options, setOptions] = useState<ChoiceOption[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    const api = getApi();
    void (async () => {
      try {
        const res = await api?.get_uefn_plugin_allowed_models?.(pluginId);
        if (!live || !res?.ok || !res.sensitive) return;
        setSensitive(true);
        setModels(res.models || []);
        const catalog = await api?.get_models_catalog?.(false);
        if (!live) return;
        setOptions(
          (catalog?.models || []).map((m) => ({ value: m.id, label: m.name || m.id, group: m.provider || undefined })),
        );
      } catch {
        /* older app or offline: nothing to show */
      }
    })();
    return () => {
      live = false;
    };
  }, [pluginId]);

  const save = useCallback(
    async (next: string[]) => {
      setModels(next);
      const res = await getApi()?.set_uefn_plugin_allowed_models?.(pluginId, next);
      setError(res && !res.ok ? res.error || "Could not save" : "");
      if (res?.ok && res.models) setModels(res.models);
    },
    [pluginId],
  );

  if (!sensitive) return null;
  // A saved model the catalog no longer lists stays visible so it can be removed.
  const known = new Set(options.map((o) => o.value));
  const all = [...options, ...models.filter((m) => !known.has(m)).map((m) => ({ value: m, label: m }))];

  return (
    <section className="general-tab-section">
      <GeneralSectionHeader
        icon={<Icons.PanelLeft />}
        title="Allowed models"
        description="Only chats on these models can use this plugin's private tools (mail, files). None picked: no AI can use them."
      />
      <div className="voice-settings-row">
        <ChoiceDropdown
          aria-label="Allowed models"
          mode="checkbox"
          values={models}
          options={all}
          searchable
          searchPlaceholder="Search models"
          placeholder={models.length ? `${models.length} allowed` : "No models allowed"}
          onChange={(next) => void save(next)}
        />
      </div>
      {error ? (
        <p className="plugin-secret-test-detail is-error" role="status">
          {error}
        </p>
      ) : null}
    </section>
  );
}
