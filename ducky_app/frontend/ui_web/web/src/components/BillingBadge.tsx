import { BILLING_TITLE, type BillingKind } from "../utils/billing";

/** A tiny "API" tag when a model bills a pay-per-token API key; nothing otherwise.
 *  `corner`: pinned to the top-right of the model icon. */
export function BillingBadge({ kind, corner = false }: { kind: BillingKind; corner?: boolean }) {
  if (kind !== "api_key") return null;
  return (
    <span className={`billing-api-tag${corner ? " billing-api-tag--corner" : ""}`} title={BILLING_TITLE.api_key}>
      API
    </span>
  );
}
