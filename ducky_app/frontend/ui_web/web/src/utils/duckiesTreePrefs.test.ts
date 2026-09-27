// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { readDuckiesAllProjects, rememberDuckiesAllProjects } from "./duckiesTreePrefs";

const KEY = "uefn-panel-duckies-all-projects";

afterEach(() => {
  localStorage.removeItem(KEY);
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
