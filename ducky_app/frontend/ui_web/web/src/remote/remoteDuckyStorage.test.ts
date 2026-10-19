// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { isolateLocalStorage } from "./remoteDuckyStorage";

/** A second window on this app's origin: same localStorage, its own events. */
function remoteWindow(): Window {
  const win = new EventTarget() as unknown as Window;
  Object.defineProperty(win, "localStorage", { configurable: true, value: window.localStorage });
  isolateLocalStorage(win, "key_2");
  return win;
}

beforeEach(() => window.localStorage.clear());

describe("a window showing another UEFN Ducky", () => {
  it("keeps its own layout: hiding its sidebar leaves this app's alone", () => {
    window.localStorage.setItem("uefn-chat-layout-mode", "full");
    const win = remoteWindow();
    expect(win.localStorage.getItem("uefn-chat-layout-mode")).toBeNull();

    win.localStorage.setItem("uefn-chat-layout-mode", "sidebarHidden");
    expect(win.localStorage.getItem("uefn-chat-layout-mode")).toBe("sidebarHidden");
    expect(window.localStorage.getItem("uefn-chat-layout-mode")).toBe("full");
    expect(win.localStorage.length).toBe(1);
    expect(win.localStorage.key(0)).toBe("uefn-chat-layout-mode");

    win.localStorage.clear();
    expect(win.localStorage.length).toBe(0);
    expect(window.localStorage.getItem("uefn-chat-layout-mode")).toBe("full");
  });

  it("never hears this app's changes, only its own keys under their plain names", () => {
    const win = remoteWindow();
    const heard = vi.fn();
    win.addEventListener("storage", (ev) => heard((ev as StorageEvent).key));
    const change = (key: string) =>
      win.dispatchEvent(new StorageEvent("storage", { key, newValue: "sidebarHidden", storageArea: window.localStorage }));

    change("uefn-chat-layout-mode");
    expect(heard).not.toHaveBeenCalled();
    change("ducky-remote:other_ducky:uefn-chat-layout-mode");
    expect(heard).not.toHaveBeenCalled();
    change("ducky-remote:key_2:uefn-chat-layout-mode");
    expect(heard).toHaveBeenCalledOnce();
    expect(heard).toHaveBeenCalledWith("uefn-chat-layout-mode");
  });
});
