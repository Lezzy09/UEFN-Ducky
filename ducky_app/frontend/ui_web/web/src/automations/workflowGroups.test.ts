import { describe, expect, it } from 'vitest';
import { cleanGroups, groupBounds, groupNodes, ungroupNodes } from './workflowGroups';
import type { AutomationGraphDto } from '../types/panel';

const graph: AutomationGraphDto = { nodes: ['a', 'b', 'c'].map((id, i) => ({ id, type: 'flow.wait', x: i * 280, y: i * 100, config: {} })), edges: [{ source: 'a', target: 'b', kind: 'main' }] };
describe('workflow groups', () => {
  it('regroups members without nesting or duplicating memberships', () => {
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
