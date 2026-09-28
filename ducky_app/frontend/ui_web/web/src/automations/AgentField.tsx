import { useCallback, useEffect, useRef, useState } from "react";
import { ChoiceDropdown, type ChoiceOption } from "../components/ChoiceDropdown";
import { getApi } from "../hooks/usePanelApi";
import type { AgentProfileDto, PanelApi } from "../types/panel";

const NEW_DUCKY = "__new__";
type Chat = Awaited<ReturnType<PanelApi["list_all_conversations"]>>[number];

export function AgentField({ value, onChange, label = "Assign ducky", id }: { value: string; onChange: (value: string) => void; label?: string; id?: string }) {
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

  const options: ChoiceOption[] = [
    { value: NEW_DUCKY, label: "Create new when workflow runs" },
    ...chats.map((chat) => ({ value: 'chat:' + chat.id, label: (chat.ducky_name || chat.title || "Ducky") + (chat.ducky_name && chat.title && chat.title !== chat.ducky_name ? ' — ' + chat.title : '') + (chat.project_name ? ' (' + chat.project_name + ')' : ''), group: "Existing duckies" })),
    ...profiles.map((profile) => ({ value: profile.id, label: profile.name, group: "Saved duckies" })),
    ...templates.map((profile) => ({ value: profile.id, label: profile.name, group: "Ducky templates" })),
  ];
  if (!known) options.push({ value: selected, label: "Saved assignment — " + value });
  return <ChoiceDropdown id={id} aria-label={label} value={selected} options={options} onChange={onChange} onOpen={() => void refresh()} searchable searchPlaceholder="Search duckies" size="compact" footer={status === "loading" ? "Loading duckies…" : status === "error" ? "Some duckies could not be loaded — reopen to retry" : undefined} />;
}
