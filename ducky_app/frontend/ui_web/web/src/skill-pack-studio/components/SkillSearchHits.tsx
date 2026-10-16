import { useEffect, useState } from "react";
import { getApi } from "../../hooks/usePanelApi";
import type { SearchHit } from "../../types/panel";

const MIN_QUERY = 3;
const DEBOUNCE_MS = 200;

/** Skill sections that best match ``query`` (meaning + keywords), from the app's search index. */
export function useSkillSearch(query: string): SearchHit[] {
  const [hits, setHits] = useState<SearchHit[]>([]);
  useEffect(() => {
    const q = query.trim();
    if (q.length < MIN_QUERY) {
      setHits([]);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      const api = getApi();
      if (!api?.search_query) return;
      void api
        .search_query(q, "skills", 8)
        .then((res) => {
          if (live) setHits(res.ok ? res.results.filter((h) => h.pack) : []);
        })
        .catch(() => {
          if (live) setHits([]);
        });
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [query]);
  return hits;
}

export function SkillSearchHits({
  hits,
  onOpen,
}: {
  hits: SearchHit[];
  onOpen: (hit: SearchHit) => void;
}) {
  if (!hits.length) return null;
  return (
    <div className="sps-search-hits" data-testid="skill-search-hits">
      <div className="sps-search-hits-title">Best matches</div>
      <ul className="sps-search-hits-list">
        {hits.map((hit, i) => (
          <li key={`${hit.pack}/${hit.subskill ?? ""}#${hit.section ?? ""}#${i}`}>
            <button type="button" className="sps-search-hit" onClick={() => onOpen(hit)}>
              <span className="sps-search-hit-title">{hit.section || hit.title}</span>
              <span className="sps-search-hit-where">{hit.where}</span>
              {hit.snippet ? <span className="sps-search-hit-snippet">{hit.snippet}</span> : null}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
