const DUCKIES_ALL_PROJECTS_KEY = "uefn-panel-duckies-all-projects";

export function readDuckiesAllProjects(): boolean {
  try {
    const raw = localStorage.getItem(DUCKIES_ALL_PROJECTS_KEY);
    // First launch: show every island, including duckies made with no project open.
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

export function rememberDuckiesAllProjects(allProjects: boolean): void {
  try {
    localStorage.setItem(DUCKIES_ALL_PROJECTS_KEY, allProjects ? "1" : "0");
  } catch {
    /* ignore */
  }
}

const DUCKIES_GLOBAL_AGENTS_KEY = "uefn-panel-duckies-global-agents";

export function readDuckiesGlobalAgents(): boolean {
  try {
    // First launch: the library duckies are visible until someone hides them.
    const raw = localStorage.getItem(DUCKIES_GLOBAL_AGENTS_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

export function rememberDuckiesGlobalAgents(show: boolean): void {
  try {
    localStorage.setItem(DUCKIES_GLOBAL_AGENTS_KEY, show ? "1" : "0");
  } catch {
    /* ignore */
  }
}
