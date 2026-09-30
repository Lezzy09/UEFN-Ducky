// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { buildFolderTree, folderPaths, joinFolder, loadEmptyFolders, movedPath, normalizeFolder, saveEmptyFolders } from './workflowFolders';
import type { AutomationSummaryDto } from '../types/panel';

const row = (id: string, folder = ''): AutomationSummaryDto => ({ id, name: id, enabled: true, folder });

describe('workflow folders', () => {
  afterEach(() => window.localStorage.clear());
  it('tidies paths like the host', () => {
    expect(normalizeFolder('  Play tests / / Tycoon ')).toBe('Play tests/Tycoon');
    expect(normalizeFolder('a\\b')).toBe('a/b');
    expect(joinFolder('', ' Tests ')).toBe('Tests');
    expect(joinFolder('QA', 'Smoke')).toBe('QA/Smoke');
  });
  it('builds a sorted tree with counts and keeps empty folders', () => {
    const tree = buildFolderTree([row('top'), row('t1', 'Tests/Tycoon'), row('t2', 'Tests'), row('b', 'builds')], ['Tests/Empty', 'Zed']);
    expect(tree.rows.map((r) => r.id)).toEqual(['top']);
    expect(tree.folders.map((f) => [f.name, f.count])).toEqual([['builds', 1], ['Tests', 2], ['Zed', 0]]);
    const tests = tree.folders[1];
    expect(tests.rows.map((r) => r.id)).toEqual(['t2']);
    expect(tests.folders.map((f) => f.path)).toEqual(['Tests/Empty', 'Tests/Tycoon']);
    expect(tree.count).toBe(4);
    expect(folderPaths(tree)).toEqual(['builds', 'Tests', 'Tests/Empty', 'Tests/Tycoon', 'Zed']);
  });
  it('moves paths with their folder only', () => {
    expect(movedPath('A/B/C', 'A/B', 'X')).toBe('X/C');
    expect(movedPath('A/B', 'A/B', 'A')).toBe('A');
    expect(movedPath('A', 'A', '')).toBe('');
    expect(movedPath('AB', 'A', 'X')).toBeNull();
  });
  it('remembers empty folders per owner and survives bad storage', () => {
    saveEmptyFolders({ local: ['Tests', ' Q / A '] });
    expect(loadEmptyFolders()).toEqual({ local: ['Tests', 'Q/A'] });
    window.localStorage.setItem('ducky.workflows.emptyFolders.v1', 'not json');
    expect(loadEmptyFolders()).toEqual({});
  });
});
