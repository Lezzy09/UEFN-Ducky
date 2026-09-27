/** Icon-only Store installs shown when Default Model is unset. */
export const DEFAULT_MODEL_GATEWAY_SLUGS = ["openai", "cursor", "anthropic", "ollama"] as const;

export type GatewayIcon = { slug: string; icon: string };

function norm(id: string): string {
  return id.trim().toLowerCase().replace(/-/g, "_");
}

/**
 * OpenAI, Cursor, Anthropic, and Ollama only — and only while not installed.
 * Other catalog rows (Google, SpaceXAI, Kimi, UEFN Ducky) are ignored.
 */
export function unsetDefaultGatewayIcons(
  items: ReadonlyArray<{ slug?: string; icon_data_url?: string | null; state?: string | null }>,
): GatewayIcon[] {
  const icons = new Map<string, string>();
  const installed = new Set<string>();
  for (const item of items) {
    const slug = norm(item.slug || "");
    if (!slug) continue;
    if (item.state === "installed" || item.state === "update") installed.add(slug);
    const icon = String(item.icon_data_url || "").trim();
    if (icon) icons.set(slug, icon);
  }
  const out: GatewayIcon[] = [];
  for (const slug of DEFAULT_MODEL_GATEWAY_SLUGS) {
    if (installed.has(slug)) continue;
    const icon = icons.get(slug);
    if (!icon) continue;
    out.push({ slug, icon });
  }
  return out;
}
