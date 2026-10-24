// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  FOLDER_CONTENT_ROOT,
  UEFN_CONTENT_ROOT,
  isPanelReadOnlyFile,
  setProjectContentRoot,
} from "../utils/isVerseFile";
import { useContentRoot } from "./useContentRoot";

afterEach(() => {
  cleanup();
  setProjectContentRoot(UEFN_CONTENT_ROOT);
});

describe("useContentRoot", () => {
  it("re-renders when project info turns the root into a folder project", () => {
    setProjectContentRoot(UEFN_CONTENT_ROOT);
    const { result } = renderHook(() => ({
      root: useContentRoot(),
      locked: isPanelReadOnlyFile("src/app.py"),
    }));
    // Before project info: island rules lock a non-Content path (the find bar loses Replace).
    expect(result.current).toEqual({ root: UEFN_CONTENT_ROOT, locked: true });

    act(() => setProjectContentRoot(FOLDER_CONTENT_ROOT));
    expect(result.current).toEqual({ root: FOLDER_CONTENT_ROOT, locked: false });
  });
});
