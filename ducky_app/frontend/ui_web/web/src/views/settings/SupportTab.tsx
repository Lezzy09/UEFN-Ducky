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
          UEFN Ducky is <strong>primarily maintained by one developer</strong> — about 99% of the
          time. Features, fixes, and day-to-day upkeep come from that one person, plus AI that
          helps ship faster.
        </p>
        <p className="support-tab-body">
          If UEFN Ducky saves you time or helps you ship something cool, consider supporting on .
          Pledges go to keeping it running: the website, AI bills, hosting, and day-to-day upkeep.
        </p>
        <p className="support-tab-body support-tab-body--muted">
          No pressure — sharing the project with a friend or leaving feedback is support too. But if you
          want to chip in,  is the best way to keep this going.
        </p>

        <div className="support-tab-warn" role="note">
          <p className="support-tab-warn-title">No official token — contributors are not founders</p>
          <p className="support-tab-body">
            There is no official UEFN Ducky or DuckyOS . The GitHub Contributors list
            is a commit list only. Contributors are not founders and are not authorized to claim
             /  fees. We do not endorse, operate, or receive those coins.
            Support the project on  only.
          </p>
        </div>

        <button type="button" className="support-tab-cta" onClick={handleOpen}>
          <Icons. />
          <span>Support on </span>
        </button>
      </div>
    </div>
  );
}
