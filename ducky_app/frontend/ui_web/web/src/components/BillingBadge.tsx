import { Icons } from "../icons/Icons";
import { BILLING_LABEL, BILLING_TITLE, type BillingKind } from "../utils/billing";

/** Where a chat's turns are billed: a subscription, a pay-per-token API key, this PC, or the account. */
export function BillingBadge({ kind, compact = false }: { kind: BillingKind; compact?: boolean }) {
  if (!kind) return null;
  const icon = kind === "api_key" ? <Icons.Key /> : kind === "local" ? <Icons.Monitor /> : kind === "account" ? <Icons.User /> : <Icons.Shield />;
  return (
    <span className={`billing-badge billing-badge--${kind}`} title={BILLING_TITLE[kind]} aria-label={BILLING_LABEL[kind]}>
      {icon}
      {compact ? null : <span className="billing-badge-text">{BILLING_LABEL[kind]}</span>}
    </span>
  );
}
