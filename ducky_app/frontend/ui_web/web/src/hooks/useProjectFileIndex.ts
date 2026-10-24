import { useCallback, useEffect, useRef, useState } from "react";
import { getApi } from "./usePanelApi";

export function useProjectFileIndex(enabled: boolean, refreshToken = 0) {
  const [files, setFiles] = useState<{ path: string; name: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const loadedRef = useRef(false);

  const load = useCallback(async () => {
    const api = getApi();
    if (!api?.list_project_file_paths) return;
    setLoading(true);
    try {
      // Reply is {paths, total, truncated}: the first 2,000 paths only.
      const reply: unknown = await api.list_project_file_paths();
      const raw = (reply as { paths?: unknown } | null)?.paths;
      const paths = Array.isArray(raw) ? raw.map((path) => String(path || "")).filter(Boolean) : [];
      setFiles(paths.map((path) => ({ path, name: path.replace(/\\/g, "/").split("/").pop() || path })));
      loadedRef.current = true;
    } catch {
      setFiles([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void load();
  }, [enabled, load, refreshToken]);

  return { files, loading, reload: load };
}
