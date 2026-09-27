import { useEffect, useState } from "react";
import { getApi } from "../hooks/usePanelApi";
import { resolvePluginHeaderIcon } from "../hooks/pluginHeaderActions";
import { BUNDLED_DUCKIES, DEFAULT_BUNDLED_DUCKY_STYLE } from "../generated/bundledDuckies";
import { useDuckyCatalogOptional } from "../components/ducky/DuckyCatalogContext";
import type { AutomationGraphNodeDto, AutomationNodeDto } from "../types/panel";

export function isEndNode(node: AutomationGraphNodeDto) {
  return node.type === "pipeline.finish" || node.type === "flow.end";
}

export function nodeLabel(node: AutomationGraphNodeDto, meta?: AutomationNodeDto) {
  if (node.type === "start.chat" && (!node.label || node.label === "Chat")) return "Chat input";
  if (node.type === "pipeline.finish" && (!node.label || node.label === "Finish")) return "Return to user";
  return node.label || meta?.label || node.type;
}

export function useNodeFaces(enabled: boolean) {
  const [faces, setFaces] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const refresh = async () => {
      const api = getApi();
      const [library, chats] = await Promise.allSettled([api?.list_agent_profiles?.(), api?.list_all_conversations?.(true)]);
      if (cancelled) return;
      const next: Record<string, string> = {};
      if (library.status === "fulfilled") {
        for (const profile of [...(library.value?.template_profiles || []), ...(library.value?.profiles || [])]) {
          next[profile.id] = profile.ducky_style;
          next[profile.name.toLowerCase()] = profile.ducky_style;
        }
      }
      if (chats.status === "fulfilled") for (const chat of chats.value || []) next[`chat:${chat.id}`] = chat.ducky_style || "";
      setFaces(next);
    };
    void refresh();
    window.addEventListener("focus", refresh);
    return () => { cancelled = true; window.removeEventListener("focus", refresh); };
  }, [enabled]);
  return faces;
}

const EMOJI: Record<string, string> = {
  "start.chat": "💬", "start.manual": "▶️", "start.cron": "⏰",
  "pipeline.finish": "📤", "flow.end": "🏁", "flow.wait": "⏳",
  "flow.branch": "🔀", "flow.foreach": "🔁", "tool.call": "🛠️",
  "uefn.open_project": "📂", "uefn.launch": "🚀", "uefn.close": "⏹️",
  "uefn.restart": "🔄", "uefn.wait_ready": "⏳", "uefn.wait_window": "🖥️",
};

export function NodeIcon({ meta, node, faces = {} }: { meta?: AutomationNodeDto; node?: AutomationGraphNodeDto; faces?: Record<string, string> }) {
  const catalog = useDuckyCatalogOptional();
  if (meta?.plugin_id && meta.icon) return <span className="aw-node-icon" aria-hidden>{resolvePluginHeaderIcon(meta.icon)}</span>;
  if (meta?.group === "Agents" || meta?.group === "Duckies" || node?.type === "pipeline.agent") {
    const assignment = String(node?.config.ducky || node?.config.profile_id || "");
    const style = faces[assignment] || faces[assignment.toLowerCase()] || catalog?.defaultStyle || DEFAULT_BUNDLED_DUCKY_STYLE;
    const url = catalog?.resolveUrl(style) || BUNDLED_DUCKIES.find((row) => row.id === style)?.url || BUNDLED_DUCKIES[0]?.url;
    return <span className="aw-node-icon" aria-hidden><img src={url} alt="" draggable={false} /></span>;
  }
  return <span className="aw-node-icon" aria-hidden>{resolvePluginHeaderIcon(meta?.icon || EMOJI[node?.type || meta?.type || ""] || (meta?.role === "starter" ? "⚡" : "🧩"))}</span>;
}
