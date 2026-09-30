import { describe, expect, it } from 'vitest';
import { cleanGroups, groupBounds, groupDepth, groupMembers, groupNodes, ungroupNodes } from './workflowGroups';
import type { AutomationGraphDto } from '../types/panel';

const graph: AutomationGraphDto = { nodes: ['a', 'b', 'c'].map((id, i) => ({ id, type: 'flow.wait', x: i * 280, y: i * 100, config: {} })), edges: [{ source: 'a', target: 'b', kind: 'main' }] };
const wide: AutomationGraphDto = { nodes: ['a', 'b', 'c', 'd', 'e'].map((id, i) => ({ id, type: 'flow.wait', x: i * 280, y: 0, config: {} })), edges: [] };
const size = () => ({ width: 200, height: 76 });

describe('workflow groups', () => {
  it('regroups members without duplicating memberships', () => {
    const first = groupNodes(graph, ['a', 'b'], 'g1');
    const second = groupNodes(first, ['b', 'c'], 'g2');
    expect(second.groups).toEqual([{ id: 'g1', name: 'Group', node_ids: ['a'] }, { id: 'g2', name: 'Group 2', node_ids: ['b', 'c'] }]);
    expect(second.nodes).toBe(graph.nodes);
    expect(second.edges).toBe(graph.edges);
    expect(groupNodes(second, ['b', 'c'], 'unused')).toBe(second);
    expect(groupNodes(second, ['missing', 'a'], 'unused')).toBe(second);
  });
  it('fits actual card sizes and removes empty groups without deleting nodes', () => {
    const grouped = groupNodes(graph, ['a', 'b'], 'g1');
    expect(groupBounds(grouped.groups![0], graph.nodes, (node) => ({ width: node.id === 'b' ? 480 : 200, height: node.id === 'b' ? 360 : 76 }))).toEqual({ x: -24, y: -24, width: 808, height: 508 });
    expect(ungroupNodes(grouped, ['a', 'b']).groups).toEqual([]);
    expect(cleanGroups({ ...grouped, nodes: [] }).groups).toEqual([]);
    expect(ungroupNodes(grouped, ['missing'])).toBe(grouped);
  });
});

describe('nested workflow groups', () => {
  it('groups part of a group inside it', () => {
    const outer = groupNodes(wide, ['a', 'b', 'c', 'd'], 'outer');
    const inner = groupNodes(outer, ['a', 'b'], 'inner');
    expect(inner.groups).toEqual([
      { id: 'outer', name: 'Group', node_ids: ['c', 'd'] },
      { id: 'inner', name: 'Group 2', node_ids: ['a', 'b'], parent_id: 'outer' },
    ]);
    expect(groupMembers(inner.groups!, 'outer')).toEqual(['c', 'd', 'a', 'b']);
    expect(groupDepth(inner.groups!, 'inner')).toBe(1);
  });
  it('puts whole groups inside a new group, with loose nodes next to them', () => {
    const one = groupNodes(wide, ['a', 'b'], 'one');
    const two = groupNodes(one, ['c', 'd'], 'two');
    const all = groupNodes(two, ['a', 'b', 'c', 'd', 'e'], 'all');
    expect(all.groups).toEqual([
      { id: 'one', name: 'Group', node_ids: ['a', 'b'], parent_id: 'all' },
      { id: 'two', name: 'Group 2', node_ids: ['c', 'd'], parent_id: 'all' },
      { id: 'all', name: 'Group 3', node_ids: ['e'] },
    ]);
    // A box of boxes holds no node of its own and still stays.
    const boxes = groupNodes(two, ['a', 'b', 'c', 'd'], 'boxes');
    expect(boxes.groups?.find((group) => group.id === 'boxes')).toEqual({ id: 'boxes', name: 'Group 3', node_ids: [] });
    expect(groupNodes(boxes, ['a', 'b', 'c', 'd'], 'again')).toBe(boxes);
  });
  it('opens only the outermost selected group, one level at a time', () => {
    const one = groupNodes(wide, ['a', 'b'], 'one');
    const all = groupNodes(one, ['a', 'b', 'c'], 'all');
    const opened = ungroupNodes(all, ['a', 'b', 'c']);
    expect(opened.groups).toEqual([{ id: 'one', name: 'Group', node_ids: ['a', 'b'] }]);
    const inner = ungroupNodes(all, ['a', 'b']);
    expect(inner.groups).toEqual([{ id: 'all', name: 'Group 2', node_ids: ['c', 'a', 'b'] }]);
    const stepOut = ungroupNodes(all, ['a']);  // one node steps out into the box around it
    expect(stepOut.groups).toEqual([{ id: 'one', name: 'Group', node_ids: ['b'], parent_id: 'all' }, { id: 'all', name: 'Group 2', node_ids: ['c', 'a'] }]);
  });
  it('makes room above nested boxes for their titles', () => {
    const one = groupNodes(wide, ['a', 'b'], 'one');
    const all = groupNodes(one, ['a', 'b', 'c'], 'all');
    const outer = all.groups!.find((group) => group.id === 'all')!;
    expect(groupBounds(outer, wide.nodes, size, all.groups, 40)).toEqual({ x: -48, y: -88, width: 832, height: 212 });
    expect(groupBounds(outer, wide.nodes, size)).toEqual({ x: 536, y: -24, width: 248, height: 124 });  // its own node only when nested boxes are not given
  });
  it('drops broken parents, loops and empty boxes', () => {
    const cleaned = cleanGroups({ ...wide, groups: [
      { id: 'x', name: 'X', node_ids: ['a'], parent_id: 'y' },
      { id: 'y', name: 'Y', node_ids: ['b'], parent_id: 'x' },
      { id: 'lost', name: 'Lost', node_ids: ['c'], parent_id: 'nowhere' },
      { id: 'hollow', name: 'Hollow', node_ids: [] },
    ] });
    expect(cleaned.groups).toEqual([
      { id: 'x', name: 'X', node_ids: ['a'] },
      { id: 'y', name: 'Y', node_ids: ['b'], parent_id: 'x' },
      { id: 'lost', name: 'Lost', node_ids: ['c'] },
    ]);
  });
});
