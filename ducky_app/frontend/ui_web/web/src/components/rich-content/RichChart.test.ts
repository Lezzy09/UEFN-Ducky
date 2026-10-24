// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { graphLayers, niceTicks, parseChartSpec, sanitizeSvg } from "./RichChart";

describe("graphLayers", () => {
  it("puts each node one layer past its deepest parent", () => {
    const nodes = ["a", "b", "c", "d"].map((id) => ({ id }));
    const layers = graphLayers(nodes, [{ from: "a", to: "b" }, { from: "b", to: "d" }, { from: "a", to: "c" }, { from: "c", to: "d" }]);
    expect([...layers.entries()]).toEqual([["a", 0], ["b", 1], ["c", 1], ["d", 2]]);
  });

  it("survives cycles and edges to unknown nodes", () => {
    const layers = graphLayers([{ id: "a" }, { id: "b" }], [{ from: "a", to: "b" }, { from: "b", to: "a" }, { from: "a", to: "zzz" }]);
    expect(layers.get("a")).toBe(0);
    expect(layers.get("b")).toBe(1);
  });
});

describe("diagram specs", () => {
  it("accepts graph and tree, rejects broken ones", () => {
    expect(parseChartSpec('{"type":"graph","nodes":[{"id":"a"}]}')?.edges).toEqual([]);
    expect(parseChartSpec('{"type":"graph","nodes":[{"label":"no id"}]}')).toBeNull();
    expect(parseChartSpec('{"type":"tree","root":{"label":"r","children":[{"label":"c"}]}}')?.type).toBe("tree");
    expect(parseChartSpec('{"type":"tree","root":{}}')).toBeNull();
  });
});

describe("parseChartSpec", () => {
  it("accepts a bar spec and pie values shorthand", () => {
    expect(parseChartSpec('{"type":"bar","labels":["a"],"series":[{"data":[1]}]}')?.type).toBe("bar");
    expect(parseChartSpec('{"type":"pie","labels":["a","b"],"values":[1,2]}')?.series?.[0].data).toEqual([1, 2]);
  });

  it("rejects half-streamed JSON and unknown types", () => {
    expect(parseChartSpec('{"type":"bar","series":[{"data":[1')).toBeNull();
    expect(parseChartSpec('{"type":"radar","series":[]}')).toBeNull();
    expect(parseChartSpec('{"type":"sequence","lanes":["A"]}')).toBeNull();
  });
});

describe("niceTicks", () => {
  it("covers the range in round steps from zero", () => {
    expect(niceTicks(3, 87)).toEqual([0, 20, 40, 60, 80, 100]);
    expect(niceTicks(-12, 30)[0]).toBeLessThanOrEqual(-12);
    expect(niceTicks(5, 5)).toEqual([0, 1, 2, 3, 4, 5]);
  });
});

describe("sanitizeSvg", () => {
  it("strips scripts, handlers and outside links", () => {
    const out = sanitizeSvg(
      '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50" onload="x()">'
      + '<script>alert(1)</script><foreignObject><div/></foreignObject>'
      + '<a href="https://evil"><rect/></a><use href="#ok"/><rect fill="url(https://x/y)" onclick="y()"/></svg>',
    )!;
    expect(out).toContain('viewBox="0 0 100 50"');
    expect(out).not.toMatch(/script|onload|onclick|foreignObject|evil|https:\/\/x/);
    expect(out).toContain('href="#ok"');
  });

  it("returns null for non-SVG", () => {
    expect(sanitizeSvg("<div>hi</div>")).toBeNull();
    expect(sanitizeSvg("<svg")).toBeNull();
  });
});
