import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get_skill_info: vi.fn(), get_skill_pack_files: vi.fn() }));
vi.mock("../../hooks/usePanelApi", () => ({ getApi: () => api }));

import { listPacksWithFiles, loadPackFiles } from "./skillPackStudioApi";

/** The slim get_skill_info reply: names, descriptions and subskill metadata, no markdown. */
const slimInfo = {
  packs: [
    {
      id: "verse",
      label: "Verse",
      description: "Verse language",
      kind: "bundled",
      subskills: [
        { id: "core", label: "Core", description: "Basics", default_enabled: true },
        { id: "persistence", label: "Persistence", description: "weak_map", default_enabled: false },
      ],
    },
    { id: "uefn", label: "UEFN", description: "Editor", kind: "bundled", subskills: [] },
  ],
  default_enabled_packs: ["verse"],
  default_enabled_subskills: { verse: ["core"] },
  text: "",
  catalog: [],
};

afterEach(() => vi.resetAllMocks());

describe("Skill Pack Studio loads contents per pack", () => {
  it("renders the pack list from the slim reply without fetching any pack's files", async () => {
    api.get_skill_info.mockResolvedValue(slimInfo);
    const catalog = await listPacksWithFiles();
    expect(catalog.packs.map((p) => p.id)).toEqual(["verse", "uefn"]);
    expect(catalog.packs[0].files.map((f) => [f.id, f.title, f.content])).toEqual([
      ["core", "Core", ""],
      ["persistence", "Persistence", ""],
    ]);
    expect(catalog.defaultEnabledPacks).toEqual(["verse"]);
    expect(api.get_skill_pack_files).not.toHaveBeenCalled();
  });

  it("opening a pack makes one per-pack call that brings its markdown", async () => {
    api.get_skill_pack_files.mockResolvedValue({
      ok: true,
      pack_id: "verse",
      files: [
        { id: "core", label: "Core", description: "Basics", default_enabled: true, file: "core.md", text: "# Verse core" },
        { id: "persistence", label: "Persistence", description: "weak_map", default_enabled: false, text: "# Persist" },
      ],
    });
    const files = await loadPackFiles("verse");
    expect(api.get_skill_pack_files).toHaveBeenCalledTimes(1);
    expect(api.get_skill_pack_files).toHaveBeenCalledWith("verse");
    expect(files.map((f) => [f.id, f.file, f.content])).toEqual([
      ["core", "core.md", "# Verse core"],
      ["persistence", "persistence.md", "# Persist"],
    ]);
    expect(api.get_skill_info).not.toHaveBeenCalled();
  });

  it("a failed pack load says why", async () => {
    api.get_skill_pack_files.mockResolvedValue({ ok: false, error: "Pack not found: gone" });
    await expect(loadPackFiles("gone")).rejects.toThrow("Pack not found: gone");
  });
});
