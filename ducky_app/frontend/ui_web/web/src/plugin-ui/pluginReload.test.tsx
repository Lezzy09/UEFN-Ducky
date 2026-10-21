// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { useReloadOnPluginUpdate } from "./pluginReload";

function Page({ version }: { version?: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  useReloadOnPluginUpdate(ref, version);
  return <iframe ref={ref} title="panel" src="/plugin-ui/playtester/ui/index.html" />;
}

describe("useReloadOnPluginUpdate", () => {
  it("loads an open plugin page again only when its plugin's version changes", () => {
    const { container, rerender, unmount } = render(<Page />);
    const iframe = container.querySelector("iframe")!;
    const set = vi.spyOn(iframe, "setAttribute");
    const reloads = () => set.mock.calls.filter(([name]) => name === "src");

    rerender(<Page version="1.1.3" />); // contributions arrived: the page already loaded this one
    rerender(<Page version="1.1.3" />);
    expect(reloads()).toEqual([]);

    rerender(<Page version="1.1.4" />); // a Store update
    expect(reloads()).toEqual([["src", "/plugin-ui/playtester/ui/index.html"]]);

    rerender(<Page version="1.1.4" />);
    expect(reloads()).toHaveLength(1);
    unmount();
  });
});
