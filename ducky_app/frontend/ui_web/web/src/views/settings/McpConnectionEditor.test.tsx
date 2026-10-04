// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { McpServerConnectionDto } from "../../types/panel";
import { McpConnectionEditor } from "./McpConnectionEditor";

const getConn = vi.fn();
const saveConn = vi.fn();

vi.mock("../../hooks/usePanelApi", () => ({
  getApi: () => ({ get_mcp_server_connection: getConn, save_mcp_server_connection: saveConn }),
}));

const view: McpServerConnectionDto = {
  ok: true, server_id: "site", kind: "custom", editable: true, transport: "http", url: "https://old.example/mcp",
  values: [{ name: "Authorization", secret: "", has_value: true, masked: "Bearer ••••abcd" }], values_label: "Headers",
};

beforeEach(() => {
  getConn.mockResolvedValue(view);
  saveConn.mockImplementation(async (_id: string, _t: string, url: string) => ({ ...view, url, values: [{ name: "Authorization", secret: "MCP_SITE_AUTHORIZATION", has_value: true, masked: "Bearer ••••9999" }] }));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("McpConnectionEditor", () => {
  it("shows the key masked, saves a new one, and keeps the old one when untouched", async () => {
    render(<McpConnectionEditor serverId="site" testing={false} onTest={() => undefined} />);
    const key = await screen.findByLabelText("Authorization value");
    expect(key.getAttribute("placeholder")).toContain("Bearer ••••abcd");
    expect((key as HTMLInputElement).value).toBe("");  // the stored key never reaches the page
    expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);

    fireEvent.change(screen.getByLabelText("URL"), { target: { value: "https://new.example/mcp" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saveConn).toHaveBeenCalledWith("site", "http", "https://new.example/mcp", "", [],
      [{ name: "Authorization", from: "Authorization", value: "", keep: true }]));

    fireEvent.change(await screen.findByLabelText("Authorization value"), { target: { value: "Bearer new-9999" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saveConn).toHaveBeenLastCalledWith("site", "http", "https://new.example/mcp", "", [],
      [{ name: "Authorization", from: "Authorization", value: "Bearer new-9999", keep: false }]));
    expect(await screen.findByText("Saved secret MCP_SITE_AUTHORIZATION")).toBeTruthy();
  });

  it("saves unsaved changes before testing", async () => {
    const onTest = vi.fn();
    render(<McpConnectionEditor serverId="site" testing={false} onTest={onTest} />);
    fireEvent.change(await screen.findByLabelText("Authorization value"), { target: { value: "Bearer x" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and test" }));
    await waitFor(() => expect(onTest).toHaveBeenCalled());
    expect(saveConn).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Test connection" })).toBeTruthy();
  });

  it("adds a header for a key", async () => {
    getConn.mockResolvedValue({ ...view, values: [] });
    render(<McpConnectionEditor serverId="site" testing={false} onTest={() => undefined} />);
    fireEvent.click(await screen.findByRole("button", { name: /Add header/ }));
    expect((screen.getByLabelText("Headers name") as HTMLInputElement).value).toBe("Authorization");
  });
});
