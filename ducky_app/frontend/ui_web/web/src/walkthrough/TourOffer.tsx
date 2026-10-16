/**
 * The walkthroughs a chat message offers (the welcome ducky's first message): one row
 * per tour with its blurb and a Start button. Tours that are not registered are left out.
 */
import { useState, useSyncExternalStore } from "react";
import { getTour, getWalkthroughState, isCompleted, startTour, subscribeWalkthrough } from "./WalkthroughService";
import "./walkthrough.css";

const activeTourId = () => getWalkthroughState().tourId;

// Re-renders when a tour starts or ends, so Running and Seen stay current.
function useActiveTourId(): string | null {
  return useSyncExternalStore((onChange) => subscribeWalkthrough(() => onChange()), activeTourId, () => null);
}

export function TourOffer({ ids }: { ids: string[] }) {
  const active = useActiveTourId();
  const [failed, setFailed] = useState("");
  const tours = ids.map((id) => ({ id, def: getTour(id) })).filter((t) => t.def);
  if (!tours.length) return null;

  const start = (id: string) => {
    setFailed("");
    void startTour(id, { force: true }).then((ok) => {
      if (!ok) setFailed(id);
    });
  };

  return (
    <ul className="tour-offer" aria-label="Walkthroughs">
      {tours.map(({ id, def }) => {
        const running = active === id;
        return (
          <li key={id} className="tour-offer-row">
            <div className="tour-offer-text">
              <span className="tour-offer-title">
                {def!.title || id}
                {isCompleted(id) ? <span className="tour-offer-seen">Seen</span> : null}
              </span>
              {def!.description ? <span className="tour-offer-desc">{def!.description}</span> : null}
              {failed === id ? <span className="tour-offer-error">Couldn't start it. Try again in a moment.</span> : null}
            </div>
            <button
              type="button"
              className="tour-offer-start"
              disabled={running}
              onClick={() => start(id)}
            >
              {running ? "Running" : "Start"}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
