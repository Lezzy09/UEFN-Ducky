import { useCallback, useEffect, useRef, useState } from "react";
import { getApi } from "../hooks/usePanelApi";
import type { AgentProfileDto, PanelApi } from "../types/panel";

const NEW_DUCKY = "__new__";
type Chat = Awaited<ReturnType<PanelApi["list_all_conversations"]>>[number];

export function AgentField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [profiles, setProfiles] = useState<AgentProfileDto[]>([]);
  const [templates, setTemplates] = useState<AgentProfileDto[]>([]);
  const [chats, setChats] = useState<Chat[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const request = useRef(0);
  const refresh = useCallback(async () => {
    const revision = ++request.current;
    const api = getApi();
    const [library, conversations] = await Promise.allSettled([
      api?.list_agent_profiles?.(),
      api?.list_all_conversations?.(true),
    ]);
    if (revision !== request.current) return;
    const libraryOk = library.status === "fulfilled" && Array.isArray(library.value?.profiles);
    const chatsOk = conversations.status === "fulfilled" && Array.isArray(conversations.value);
    if (libraryOk && library.status === "fulfilled" && library.value) {
      const rows = library.value.profiles.filter((row) => row.id && row.id !== library.value?.blank_profile_id);
      setProfiles(rows);
      setTemplates((library.value.template_profiles || []).filter((row) => row.id && !rows.some((saved) => saved.id === row.id)));
    }
    if (chatsOk && conversations.status === "fulfilled") setChats(conversations.value!.filter((chat) => chat.id && !chat.is_group));
    setStatus(libraryOk && chatsOk ? "ready" : "error");
  }, []);

  useEffect(() => {
    void refresh();
    return () => { request.current++; };
  }, [refresh]);

  const available = [...profiles, ...templates];
  // Older graphs may contain a profile name instead of its ID.
  const matches = available.filter((profile) => profile.name.toLowerCase() === value.toLowerCase());
  const selected = !value || value === "__blank__" ? NEW_DUCKY
    : available.some((profile) => profile.id === value) ? value
    : matches.length === 1 ? matches[0].id : value;
  const known = selected === NEW_DUCKY || available.some((profile) => profile.id === selected) || chats.some((chat) => `chat:${chat.id}` === selected);

  return (
    <select value={selected} onChange={(event) => onChange(event.target.value)} onFocus={() => void refresh()}>
      <option value={NEW_DUCKY}>Create new when workflow runs</option>
      {chats.length > 0 && <optgroup label="Existing duckies">
        {chats.map((chat) => <option key={chat.id} value={`chat:${chat.id}`}>
          {chat.ducky_name || chat.title || "Ducky"}{chat.ducky_name && chat.title && chat.title !== chat.ducky_name ? ` — ${chat.title}` : ""}{chat.project_name ? ` (${chat.project_name})` : ""}
        </option>)}
      </optgroup>}
      {profiles.length > 0 && <optgroup label="Saved duckies">
        {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
      </optgroup>}
      {templates.length > 0 && <optgroup label="Ducky templates">
        {templates.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
      </optgroup>}
      {!known && <option value={selected}>Saved assignment — {value}</option>}
      {status === "loading" && <option disabled>Loading duckies…</option>}
      {status === "error" && <option disabled>Some duckies could not be loaded — reopen to retry</option>}
    </select>
  );
}
