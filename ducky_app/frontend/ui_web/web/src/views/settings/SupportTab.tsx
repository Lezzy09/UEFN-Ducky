import type { MouseEvent } from "react";
import { Icons } from "../../icons/Icons";
import { getApi } from "../../hooks/usePanelApi";
import { burstConfettiFromElement } from "../../utils/confettiBurst";

export function SupportTab() {
  const handleOpen = (event: MouseEvent<HTMLButtonElement>) => {
    burstConfettiFromElement(event.currentTarget);
    const api = getApi();
    if (api && typeof api.open__page === "function") {
      void api.open__page();
    }
  };

  return (
    <div className="support-tab">
      <h2 className="support-tab-title">Support UEFN Ducky</h2>
      <p className="support-tab-lead">Thank you for using UEFN Ducky — it genuinely means a lot.</p>

      <div className="support-tab-card">
        <p className="support-tab-body">
          UEFN Ducky is <strong>maintained by the community</strong> and <strong>powered by AI</strong>.
          Features, fixes, PRs, and day-to-day upkeep are increasingly automated — this isn't a
          one-person project anymore.
        </p>
        <p className="support-tab-body">
          If UEFN Ducky saves you time or helps you ship something cool, consider supporting on .
          Pledges go to continued maintenance: the website, AI bills, hosting, and keeping the automated
          pipeline running.
        </p>
        <p className="support-tab-body support-tab-body--muted">
          No pressure — sharing the project with a friend or leaving feedback is support too. But if you
          want to chip in,  is the best way to keep this going.
        </p>

        <button type="button" className="support-tab-cta" onClick={handleOpen}>
          <Icons. />
          <span>Support on </span>
        </button>
      </div>
    </div>
  );
}
