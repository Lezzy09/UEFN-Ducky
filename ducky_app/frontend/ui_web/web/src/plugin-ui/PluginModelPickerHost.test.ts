// @vitest-environment jsdom
import { expect, it } from "vitest";

import { extraRows } from "./PluginModelPickerHost";

it("turns a plugin's extra rows into tagged catalog rows and drops broken ones", () => {
  const rows = extraRows([
    { id: "typesafe:jev-1.14.0", name: "Jev 1.14.0", group: "TypeSafe", note: "Not for chat", vision: true },
    { id: "typesafe:jev-1.14.0", name: "duplicate", group: "TypeSafe" },
    { id: "", group: "TypeSafe" },
    { id: "x:y" },
    "junk",
  ]);
  expect(rows).toHaveLength(1);
  expect(rows[0]).toMatchObject({
    id: "typesafe:jev-1.14.0",
    provider: "TypeSafe",
    providerKey: "typesafe",
    note: "Not for chat",
    supportsVision: true,
    supportsTools: false,
  });
  expect(extraRows(undefined)).toEqual([]);
});
