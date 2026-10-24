// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const pick = vi.fn(async () => ({ ok: true }));
vi.mock("../hooks/usePanelApi", async (orig) => ({
  ...(await orig<typeof import("../hooks/usePanelApi")>()),
  getApi: () => ({ native_menu_pick: pick }),
}));

const { NativeTextMenu } = await import("./NativeTextMenu");

afterEach(() => {
  cleanup();
  pick.mockClear();
});

it("shows WebView2's spelling suggestions as Ducky's menu and answers with the pick", () => {
  render(<NativeTextMenu />);
  fireEvent.contextMenu(window, { clientX: 40, clientY: 60 });
  act(() => {
    window.__uefnPanelPush?.({
      type: "native_menu",
      token: "t1",
      items: [{ id: 11, label: "villager" }, { separator: true }, { id: 20, label: "Cut" }],
    } as never);
  });
  fireEvent.click(screen.getByRole("menuitem", { name: "villager" }));
  expect(pick).toHaveBeenCalledWith("t1", 11);
  expect(pick).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("menu")).toBeNull();
});
