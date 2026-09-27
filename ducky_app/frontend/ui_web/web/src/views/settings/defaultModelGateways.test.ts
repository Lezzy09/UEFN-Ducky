import { describe, expect, it } from "vitest";
import { unsetDefaultGatewayIcons } from "./defaultModelGateways";

describe("unsetDefaultGatewayIcons", () => {
  it("keeps only OpenAI, Cursor, Anthropic, and Ollama icons that are not installed", () => {
    const icons = unsetDefaultGatewayIcons([
      { slug: "google", icon_data_url: "data:google", state: "available" },
      { slug: "spacexai", icon_data_url: "data:spacex", state: "available" },
      { slug: "kimi", icon_data_url: "data:kimi", state: "available" },
      { slug: "uefn-ducky", icon_data_url: "data:ducky", state: "installed" },
      { slug: "openai", icon_data_url: "data:openai", state: "available" },
      { slug: "cursor", icon_data_url: "data:cursor", state: "available" },
      { slug: "anthropic", icon_data_url: "data:anthropic", state: "installed" },
      { slug: "ollama", icon_data_url: "data:ollama", state: "update" },
    ]);
    expect(icons).toEqual([
      { slug: "openai", icon: "data:openai" },
      { slug: "cursor", icon: "data:cursor" },
    ]);
  });
});
