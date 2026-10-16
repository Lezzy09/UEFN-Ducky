import { useEffect, useState } from "react";
import { getApi } from "./usePanelApi";

const MIN_QUERY = 3;
const DEBOUNCE_MS = 200;

/** Tool names ranked for ``query`` by the app's search index (meaning + keywords); [] on any failure. */
export async function rankToolNames(query: string, limit = 30): Promise<string[]> {
  const q = query.trim();
  const api = getApi();
  if (q.length < MIN_QUERY || !api?.search_query) return [];
  try {
    const res = await api.search_query(q, "tools", limit);
    return res.ok ? res.results.map((hit) => hit.tool || "").filter(Boolean) : [];
  } catch {
    return [];
  }
}

/** ``rankToolNames`` for a search box: debounced, one request per pause in typing. */
export function useRankedToolNames(query: string, limit = 30): string[] {
  const [names, setNames] = useState<string[]>([]);
  useEffect(() => {
    if (query.trim().length < MIN_QUERY) {
      setNames([]);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      void rankToolNames(query, limit).then((next) => {
        if (live) setNames(next);
      });
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [query, limit]);
  return names;
}
