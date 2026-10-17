import { describe, expect, it, vi } from "vitest";

vi.mock("../hooks/modelsCatalogCache", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../hooks/modelsCatalogCache")>()),
  getCachedModels: () => [
    {
      provider: "Hosted",
      providerKey: "hosted",
      id: "hosted-ai",
      aliases: ["hosted-old"],
      name: "Hosted AI",
      supportsVision: true,
      supportsTools: true,
      supportsWebSearch: false,
      contextLimit: 0,
      priceIn: null,
      priceOut: null,
      isLocal: false,
    },
  ],
}));

import { billingKind, setGatewayBilling } from "../utils/billing";
import { aiTypeLabel, shortModelLabel } from "./groupMemberHover";

describe("model names in the roster", () => {
  // Oct 17 2026: a group's roster card showed "ducky-brain" (the model id) instead of its name.
  it("shows the catalog name, for an old id too", () => {
    expect(shortModelLabel("hosted-ai")).toBe("Hosted AI");
    expect(shortModelLabel("hosted:hosted-old")).toBe("Hosted AI");
    expect(aiTypeLabel("hosted-old", "ducky")).toBe("Hosted AI");
    expect(shortModelLabel("gpt-6-luna")).toBe("gpt-6-luna");
  });

  it("takes how a gateway is paid from its plugin, never a gateway name", () => {
    expect(billingKind("ducky", "hosted")).toBe("api_key");
    setGatewayBilling([{ id: "hosted", billing: "account" }]);
    expect(billingKind("ducky", "hosted")).toBe("account");
    setGatewayBilling([]);
  });
});
