import { useEffect, useState } from "react";
import { getApi } from "../../hooks/usePanelApi";
import { onApiReady } from "../../hooks/onApiReady";
import { SettingsToggleRow } from "./SettingsToggleRow";

/** Whether agents may start chats on this provider's API key. Off: a chat an agent seats
 *  or spawns runs on a subscription (Codex, Claude Code…) or a local model, never this key. */
export function AgentApiKeyToggle({ providerId }: { providerId: string }) {
  const id = (providerId || "").trim().toLowerCase();
  const [allowed, setAllowed] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => onApiReady((api) => {
    void api.get_settings().then((settings) => {
      setAllowed((settings.agent_api_keys || []).map((p) => p.trim().toLowerCase()));
      setLoaded(true);
    });
  }), []);
  if (!id) return null;
  const on = allowed.includes(id);
  return (
    <div className="general-tab-toggle-card">
      <SettingsToggleRow
        id={`toggle-agent-api-key-${id}`}
        label="Let agents start chats on this key"
        checked={on}
        disabled={!loaded}
        onChange={(value) => {
          const next = value ? [...new Set([...allowed, id])] : allowed.filter((p) => p !== id);
          setAllowed(next);
          void getApi()?.save_agent_settings({ agent_api_keys: next });
        }}
      />
      <p className="general-tab-toggle-desc">
        Billed per token. Off: duckies an agent creates or seats in a team run on a subscription
        (Codex, Claude Code…) or a local model instead, so a team never spends this key without you.
        Your own chats can always use it.
      </p>
    </div>
  );
}
