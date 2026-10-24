// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StoreActions } from "./StoreActions";
import type { DuckyOSStoreItemDto } from "../../../types/panel";

vi.mock("./pluginStoreActions", () => ({
  loadPluginContributes: () => Promise.resolve({}),
  openInstalledPluginSettings: vi.fn(),
  pluginHasWalkthrough: () => false,
  redoInstalledPluginWalkthrough: vi.fn(),
  settingsTargetFromContributes: () => null,
}));

const handlers = { onInstall: vi.fn(), onToggle: vi.fn(), onUninstall: vi.fn() };

describe("StoreActions", () => {
  it("keeps Uninstall next to Update while an update is pending", () => {
    const item = { slug: "island-media-kit", kind: "plugin", state: "update", enabled: true } as unknown as DuckyOSStoreItemDto;
    render(<StoreActions item={item} handlers={handlers} busy={false} size="detail" />);
    expect(screen.getByText("Update")).toBeTruthy();
    expect(screen.getByText("Uninstall")).toBeTruthy();
  });
});
