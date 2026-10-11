/** How a chat's turns are paid. Mirrors frontend/favorite_models.billing_kind. */
export type BillingKind = "subscription" | "api_key" | "local" | "account" | "";

const LOCAL_PROVIDERS = new Set(["ollama", "lmstudio", "llamacpp"]);

export function billingKind(codingAgent: string | undefined, provider: string | undefined, isLocal = false): BillingKind {
  const agent = (codingAgent || "").trim().toLowerCase();
  if (agent && agent !== "ducky") return "subscription";
  const prov = (provider || "").trim().toLowerCase();
  if (prov === "uefn_ducky") return "account";
  if (!prov) return "";
  if (isLocal || LOCAL_PROVIDERS.has(prov)) return "local";
  return "api_key";
}

export const BILLING_LABEL: Record<Exclude<BillingKind, "">, string> = {
  subscription: "Subscription",
  api_key: "API key",
  local: "Local",
  account: "Ducky account",
};

export const BILLING_TITLE: Record<Exclude<BillingKind, "">, string> = {
  subscription: "Runs on the coding agent's own login (Codex, Claude Code…): your subscription, not per-token billing.",
  api_key: "Billed per token to your saved API key. Agents may only start chats on it when you allow it in Settings → LLMs.",
  local: "Runs on a model on this PC: no per-token cost.",
  account: "Runs on your UEFN Ducky account.",
};
