// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import {
  readDuckiesAllProjects,
  readDuckiesGlobalAgents,
  rememberDuckiesAllProjects,
  rememberDuckiesGlobalAgents,
} from "./duckiesTreePrefs";

const KEY = "uefn-panel-duckies-all-projects";
const GLOBAL_KEY = "uefn-panel-duckies-global-agents";

afterEach(() => {
  localStorage.removeItem(KEY);
  localStorage.removeItem(GLOBAL_KEY);
});

describe("readDuckiesAllProjects", () => {
  it("is on until someone turns it off", () => {
    localStorage.removeItem(KEY);
    expect(readDuckiesAllProjects()).toBe(true);
    rememberDuckiesAllProjects(false);
    expect(readDuckiesAllProjects()).toBe(false);
    rememberDuckiesAllProjects(true);
    expect(readDuckiesAllProjects()).toBe(true);
  });
});

describe("readDuckiesGlobalAgents", () => {
  it("is on until someone turns it off", () => {
    localStorage.removeItem(GLOBAL_KEY);
    expect(readDuckiesGlobalAgents()).toBe(true);
    rememberDuckiesGlobalAgents(false);
    expect(readDuckiesGlobalAgents()).toBe(false);
    rememberDuckiesGlobalAgents(true);
    expect(readDuckiesGlobalAgents()).toBe(true);
  });
});
