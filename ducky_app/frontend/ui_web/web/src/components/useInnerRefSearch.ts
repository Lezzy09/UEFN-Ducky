import { useEffect, useRef, useState } from "react";
import { getApi } from "../hooks/usePanelApi";
import type { SkillPackFilesDto } from "../types/panel";
import { innerTextHit, type ChatRef } from "./chatReferences";
import { noteChatRefFaces } from "./chatRefFaces";
import { isAbsEncodedPath, isFolderProject } from "../verse-editor/utils/isVerseFile";

interface SkillBody {
  id: string;
  label: string;
  group: string;
  href: string;
  text: string;
}

let skillBodies: Promise<SkillBody[]> | null = null;

function loadSkillBodies(): Promise<SkillBody[]> {
  const api = getApi();
  if (!api?.get_skill_info || !api.get_skill_pack_files) return Promise.resolve([]);
  if (!skillBodies) {
    skillBodies = api
      .get_skill_info()
      .then(async (info) => {
        const packs = info.packs ?? [];
        const loaded = await Promise.all(
          packs.map((pack) => api.get_skill_pack_files!(pack.id).catch(() => null as SkillPackFilesDto | null)),
        );
        const out: SkillBody[] = [];
        packs.forEach((pack, index) => {
          const files = loaded[index]?.files ?? [];
          const id = String(pack.id || "").trim();
          if (!id) return;
          out.push({
            id: `skill:${id}`,
            label: pack.label || id,
            group: "Skills",
            href: `skill:${id}`,
            text: [pack.description, ...files.map((file) => file.text)].join("\n"),
          });
          for (const file of files) {
            if (!file.id || file.id === "core") continue;
            out.push({
              id: `subskill:${id}/${file.id}`,
              label: file.label || file.id,
              group: "Subskills",
              href: `subskill:${id}/${file.id}`,
              text: `${file.description}\n${file.text}`,
            });
          }
        });
        return out;
      })
      .catch(() => []);
  }
  return skillBodies;
}

function take<T>(rows: T[], limit: number): T[] {
  return rows.slice(0, limit);
}

/** ~ searches inside chats, Content files, and skill text. Names stay on @ and /. */
export function useInnerRefSearch(query: string, enabled: boolean, files: ChatRef[], slashRefs: ChatRef[]): ChatRef[] {
  const [hits, setHits] = useState<ChatRef[]>([]);
  const filesRef = useRef(files);
  const slashRef = useRef(slashRefs);
  filesRef.current = files;
  slashRef.current = slashRefs;

  useEffect(() => {
    if (!enabled) {
      setHits([]);
      return;
    }
    const q = query.trim();
    if (q.length < 2) {
      setHits([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        const api = getApi();
        const [workspace, skills] = await Promise.all([
          api?.search_workspace(q, "both", false, false, 24).catch(() => null),
          loadSkillBodies(),
        ]);
        if (cancelled) return;
        const chats: ChatRef[] = [];
        for (const chat of workspace?.chat_results ?? []) {
          if ((chat.folder_id || "") === "archive") continue;
          const preview = chat.matches?.[0]?.preview || chat.title;
          chats.push({
            trigger: "~",
            id: `chat:${chat.id}`,
            label: chat.title || "Ducky",
            group: "Chats",
            href: `ducky:${chat.id}`,
            description: preview,
            duckyStyle: chat.ducky_style,
          });
        }
        const seen = new Set<string>();
        const content: ChatRef[] = [];
        const pushFile = (path: string, preview: string) => {
          const clean = path.replace(/\\/g, "/");
          const inContent = isFolderProject() ? !isAbsEncodedPath(clean) : clean.startsWith("Content/");
          if (!inContent || clean.includes(".digest.verse")) return;
          const href = `file:${clean}`;
          if (seen.has(href)) return;
          seen.add(href);
          content.push({
            trigger: "~",
            id: href,
            label: clean.split("/").pop() || clean,
            group: "Content",
            href,
            description: preview,
          });
        };
        for (const file of workspace?.file_results ?? []) {
          pushFile(file.path, file.matches?.[0]?.preview || file.path);
        }
        for (const file of filesRef.current) {
          const hit = innerTextHit(`${file.label} ${file.description || ""}`, q);
          if (hit) pushFile(file.href.slice("file:".length), file.description || hit);
        }
        const skillHits: ChatRef[] = [];
        for (const skill of skills) {
          const snip = innerTextHit(skill.text, q);
          if (!snip) continue;
          skillHits.push({
            trigger: "~",
            id: skill.id,
            label: skill.label,
            group: skill.group,
            href: skill.href,
            description: snip,
          });
        }
        const other: ChatRef[] = [];
        for (const ref of slashRef.current) {
          if (!ref.href.startsWith("mcp:") && !ref.href.startsWith("plugin:")) continue;
          const snip = innerTextHit(`${ref.label} ${ref.description || ""}`, q);
          if (!snip) continue;
          other.push({ ...ref, trigger: "~", description: snip });
        }
        const rows = [...take(chats, 8), ...take(content, 8), ...take(skillHits, 8), ...take(other, 6)];
        noteChatRefFaces(rows);
        setHits(rows);
      })();
    }, 160);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, enabled]);

  return hits;
}
