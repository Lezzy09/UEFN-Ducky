import { useEffect, useState } from "react";
import { getApi } from "../hooks/usePanelApi";
import { usePluginContributions } from "../hooks/usePluginContributions";
import { chatMentionGroup, dedupeChatRefs, orderChatMentions, type ChatRef } from "./chatReferences";
import { noteChatRefFaces } from "./chatRefFaces";
import { resolvePluginIconContent } from "../hooks/pluginHeaderActions";

interface ConvRow {
  id: string;
  title?: string;
  folder_id?: string;
  is_group?: boolean;
  project_slug?: string;
  project_name?: string;
  ducky_style?: string;
}

function isArchived(row: ConvRow): boolean {
  return (row.folder_id || "").trim() === "archive";
}

function chatRef(
  trigger: ChatRef["trigger"],
  id: string,
  label: string,
  group: string,
  href: string,
  description?: string,
  face?: { duckyStyle?: string; iconUrl?: string },
): ChatRef {
  return { trigger, id, label, group, href, description, ...face };
}

const CONTENT_TEXT = /\.(verse|versetest|vson|json|md|txt|toml|cfg)$/i;

export function useChatReferenceCatalog(
  active: boolean,
  chatId: string,
): { mentions: ChatRef[]; slashRefs: ChatRef[]; files: ChatRef[] } {
  const contrib = usePluginContributions();
  const [builtinMentions, setBuiltinMentions] = useState<ChatRef[]>([]);
  const [builtinSlash, setBuiltinSlash] = useState<ChatRef[]>([]);
  const [contentFiles, setContentFiles] = useState<ChatRef[]>([]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    void (async () => {
      const api = getApi();
      if (!api) return;
      const [convs, profiles, skills, mcp, recents, paths, pipelines] = await Promise.all([
        api.list_all_conversations(true).catch(() => []),
        api.list_agent_profiles().catch(() => null),
        api.get_skill_info().catch(() => null),
        api.list_mcp_servers?.().catch(() => null) ?? null,
        api.list_recent_projects().catch(() => []),
        api.list_project_file_paths().catch(() => []),
        api.list_pipelines?.().catch(() => null) ?? null,
      ]);
      if (cancelled) return;
      const openSlug = String(
        (convs as ConvRow[]).find((row) => row.id === chatId)?.project_slug
          || recents.find((row) => row.active)?.slug
          || "",
      ).trim();
      const thisProject: ChatRef[] = [];
      const otherProjects = new Map<string, ChatRef[]>();
      const globalMentions: ChatRef[] = [];
      for (const conv of (convs || []) as ConvRow[]) {
        if (!conv.id || isArchived(conv)) continue;
        const slug = String(conv.project_slug || "").trim();
        const title = String(conv.title || "Ducky").trim() || "Ducky";
        const face = { duckyStyle: String(conv.ducky_style || "").trim() || undefined };
        const group = chatMentionGroup(slug, openSlug, String(conv.project_name || ""));
        const row = chatRef("@", `chat:${conv.id}`, title, group, `ducky:${conv.id}`, undefined, face);
        if (group === "This project") thisProject.push(row);
        else if (group === "Global") globalMentions.push(row);
        else {
          const list = otherProjects.get(group) ?? [];
          list.push(row);
          otherProjects.set(group, list);
        }
      }
      for (const profile of profiles?.profiles ?? []) {
        const id = String(profile.id || "").trim();
        if (!id || id === "__blank__") continue;
        globalMentions.push(chatRef("@", `profile:${id}`, profile.name || id, "Global", `profile:${id}`, profile.when_to_use, {
          duckyStyle: profile.ducky_style,
        }));
      }
      const mentions = orderChatMentions([
        ...thisProject,
        ...[...otherProjects.values()].flat(),
        ...globalMentions,
      ]);

      const slash: ChatRef[] = [];
      for (const pipeline of pipelines?.pipelines || []) {
        slash.push(chatRef("/", `pipeline:${pipeline.id}`, pipeline.name || "Untitled pipeline", "Pipelines", `pipeline:${pipeline.id}`, pipeline.description || "Run this pipeline with the request you type after it", { iconUrl: "🔗" }));
      }
      for (const pack of skills?.packs ?? []) {
        const id = String(pack.id || "").trim();
        if (!id) continue;
        slash.push(chatRef("/", `skill:${id}`, pack.label || id, "Skills", `skill:${id}`, pack.description));
        for (const sub of pack.subskills ?? []) {
          const subId = String(sub.id || "").trim();
          if (!subId || subId === "core") continue;
          slash.push(
            chatRef(
              "/",
              `subskill:${id}/${subId}`,
              sub.label || subId,
              "Subskills",
              `subskill:${id}/${subId}`,
              pack.label || id,
            ),
          );
        }
      }
      for (const server of mcp?.plugins ?? []) {
        const id = String(server.id || "").trim();
        if (!id) continue;
        slash.push(chatRef("/", `mcp:${id}`, server.label || id, "MCP", `mcp:${id}`, server.description));
      }
      for (const panel of contrib.ui_panels ?? []) {
        const pluginId = String(panel.plugin_id || "").trim();
        const panelId = String(panel.id || "").trim();
        if (!pluginId || !panelId) continue;
        slash.push(
          chatRef(
            "/",
            `plugin:${pluginId}/${panelId}`,
            panel.title || panelId,
            "Plugins",
            `plugin:${pluginId}/${panelId}`,
            undefined,
            {
              iconUrl: (() => {
                const icon = resolvePluginIconContent(panel.icon);
                return icon.kind === "image" ? icon.src : icon.emoji;
              })(),
            },
          ),
        );
      }
      const files: ChatRef[] = [];
      for (const row of paths || []) {
        const path = String(row.path || "").replace(/\\/g, "/");
        const name = String(row.name || "").trim();
        if (!name || !path.startsWith("Content/") || !CONTENT_TEXT.test(name)) continue;
        if (path.includes(".digest.verse")) continue;
        files.push(chatRef("/", `file:${path}`, name, "Content", `file:${path}`, path));
      }
      noteChatRefFaces([...mentions, ...slash]);
      setBuiltinMentions(mentions);
      setBuiltinSlash(slash);
      setContentFiles(files);
    })();
    return () => {
      cancelled = true;
    };
  }, [active, chatId, contrib.ui_panels]);

  const extra: ChatRef[] = [];
  for (const row of contrib.chat_references ?? []) {
    const trigger = row.trigger === "@" ? "@" : row.trigger === "/" ? "/" : null;
    const id = String(row.id || "").trim();
    const label = String(row.label || "").trim();
    const href = String(row.href || "").trim();
    if (!trigger || !id || !label || !href) continue;
    extra.push({
      trigger,
      id,
      label,
      href,
      group: String(row.group || "Plugins").trim() || "Plugins",
      description: row.description,
    });
  }
  const extraMentions = extra.filter((row) => row.trigger === "@");
  const extraSlash = extra.filter((row) => row.trigger === "/");

  const mentions = dedupeChatRefs([...builtinMentions, ...extraMentions]);
  const slashRefs = dedupeChatRefs([...builtinSlash, ...extraSlash]);
  useEffect(() => {
    noteChatRefFaces([...mentions, ...slashRefs]);
  }, [mentions, slashRefs]);
  return { mentions, slashRefs, files: contentFiles };
}
