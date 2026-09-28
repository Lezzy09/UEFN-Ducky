import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { AutomationTemplatePicker } from "./AutomationTemplatePicker";
import { NodeSettings, hasNodeSettings } from "./NodeSettings";
import { InlineNodeText } from "./InlineNodeText";
import { ChoiceDropdown } from "../components/ChoiceDropdown";
import type {
  AutomationDto,
  AutomationGraphDto,
  AutomationGraphNodeDto,
  AutomationNodeDto,
  AutomationRunDto,
  AutomationSummaryDto,
  AutomationTemplateDto,
} from "../types/panel";
import { getApi } from "../hooks/usePanelApi";
import { takePendingGraphFocus } from "../hooks/graphActivity";
import { Icons } from "../icons/Icons";
import { copyText } from "../utils/copyText";
import { formatRunLog, runLogHasContent } from "./runLog";

import { isEndNode, nodeLabel, NodeIcon, useNodeFaces } from "./NodeVisuals";
import { arrangeGraph, nodeWidth, portPoint, zoomAt, OVERVIEW_ZOOM } from "./graphGeometry";
const LOG_H_MIN = 140;
const LOG_H_MAX = 560;
const LOG_H_DEFAULT = 220;
const GROUP_ORDER = ["Starting", "Triggers", "Agents", "Duckies", "Tools", "Logic", "End"];

export function clampLogHeight(h: number, boardH = 0): number {
  const cap = boardH > 0 ? Math.max(LOG_H_MIN, boardH - 24) : LOG_H_MAX;
  return Math.min(LOG_H_MAX, cap, Math.max(LOG_H_MIN, h));
}

function emptyGraph(): AutomationGraphDto {
  return { nodes: [], edges: [] };
}

function nid(): string {
  return `n${Math.random().toString(36).slice(2, 10)}`;
}

function groupCatalog(catalog: AutomationNodeDto[], query: string) {
  const q = query.trim().toLowerCase();
  const map = new Map<string, AutomationNodeDto[]>();
  for (const n of catalog) {
    if (q && !`${n.label} ${n.type} ${n.group} ${n.description || ""}`.toLowerCase().includes(q)) continue;
    const g = n.group || "Nodes";
    const list = map.get(g) || [];
    list.push(n);
    map.set(g, list);
  }
  const keys = [...map.keys()].sort((a, b) => {
    const ia = GROUP_ORDER.indexOf(a);
    const ib = GROUP_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  return keys.map((k) => [k, map.get(k) || []] as const);
}

type WorkflowKind = "automation" | "pipeline";
const WORKFLOW_SECTIONS = [{ kind: "pipeline", label: "Pipelines" }, { kind: "automation", label: "Automations" }] as const;

export function AutomationsView({ kind: initialKind = "automation" }: { kind?: WorkflowKind }) {
  const sectionId = useId();
  const [kind, setKind] = useState<WorkflowKind>(initialKind);
  const [rows, setRows] = useState<Record<WorkflowKind, AutomationSummaryDto[]>>({ pipeline: [], automation: [] });
  const [sectionsOpen, setSectionsOpen] = useState({ pipeline: true, automation: true });
  const [pickerKind, setPickerKind] = useState<WorkflowKind>(initialKind);
  const listRef = useRef<HTMLElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const [catalog, setCatalog] = useState<AutomationNodeDto[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState<AutomationDto | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [expandedId, setExpandedId] = useState("");
  const [selectedEdge, setSelectedEdge] = useState<number | null>(null);
  const [groupsCollapsed, setGroupsCollapsed] = useState(false);
  const resizeRef = useRef<{ id: string; startX: number; width: number } | null>(null);
  const [pan, setPan] = useState({ x: 280, y: 160 });
  const [zoom, setZoom] = useState(1);
  const [wireFrom, setWireFrom] = useState<string | null>(null);
  const [draftWire, setDraftWire] = useState<{
    sourceId: string;
    fromX: number;
    fromY: number;
    toX: number;
    toY: number;
  } | null>(null);
  const [log, setLog] = useState<AutomationRunDto | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const [logCopied, setLogCopied] = useState(false);
  const [logHeight, setLogHeight] = useState(LOG_H_DEFAULT);
  const logResizeRef = useRef<{ startY: number; startH: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [spawn, setSpawn] = useState<{ x: number; y: number; worldX: number; worldY: number } | null>(null);
  const [spawnFilter, setSpawnFilter] = useState("");
  const spawnSearchRef = useRef<HTMLInputElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const boardRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const panRef = useRef<{ x: number; y: number; px: number; py: number; button: number; moved: boolean } | null>(null);
  const touches = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ distance: number; center: { x: number; y: number }; pan: { x: number; y: number }; zoom: number } | null>(null);
  const suppressMenuUntil = useRef(0);
  const wireRef = useRef<{
    sourceId: string;
    dir: "in" | "out";
    fromX: number;
    fromY: number;
  } | null>(null);

  const byType = useMemo(() => {
    const m = new Map<string, AutomationNodeDto>();
    for (const n of catalog) m.set(n.type, n);
    return m;
  }, [catalog]);

  const isPipeline = kind === "pipeline";

  const refreshList = useCallback(async () => {
    const api = getApi();
    const [pipelines, automations] = await Promise.all([api?.list_pipelines?.(), api?.list_automations?.()]);
    setRows({ pipeline: pipelines?.pipelines || [], automation: automations?.automations || [] });
  }, []);

  useEffect(() => { void refreshList(); }, [refreshList]);

  useEffect(() => {
    let cancelled = false;
    setCatalog([]);
    const load = async () => {
      const api = getApi();
      const result = isPipeline ? await api?.list_pipeline_nodes?.() : await api?.list_automation_nodes?.();
      if (!cancelled) setCatalog(result?.nodes || []);
    };
    void load();
    return () => { cancelled = true; };
  }, [isPipeline]);

  useEffect(() => {
    if (!spawn) return;
    spawnSearchRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSpawn(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [spawn]);

  const loadGen = useRef(0);
  const loadOne = useCallback(async (id: string, targetKind: WorkflowKind) => {
    const gen = ++loadGen.current;
    const api = getApi();
    const res = targetKind === "pipeline" ? await api?.get_pipeline?.(id) : await api?.get_automation?.(id);
    if (gen !== loadGen.current) return;
    const row = res?.automation || res?.pipeline;
    if (row) {
      setKind(targetKind);
      setDraft({ ...row, kind: targetKind });
      setSectionsOpen((current) => ({ ...current, [targetKind]: true }));
      setSelectedId(id);
      setSpawn(null);
      setSelectedNodeId("");
      setSelectedEdge(null);
      setExpandedId("");
      setLog((row.runs || []).slice(-1)[0] || null);
    }
  }, []);

  useEffect(() => {
    const open = (id: string, targetKind: WorkflowKind) => {
      if (!id) return;
      void refreshList();
      void loadOne(id, targetKind);
      setLogOpen(true);
    };
    for (const section of WORKFLOW_SECTIONS) {
      const queued = takePendingGraphFocus(section.kind);
      if (queued) open(queued, section.kind);
    }
    const onFocus = (ev: Event) => {
      const detail = (ev as CustomEvent<{ kind?: WorkflowKind; id?: string }>).detail;
      if (!detail?.id || (detail.kind !== "pipeline" && detail.kind !== "automation")) return;
      takePendingGraphFocus(detail.kind);
      open(detail.id, detail.kind);
    };
    const onDeleted = (ev: Event) => {
      const detail = (ev as CustomEvent<{ kind?: WorkflowKind; id?: string }>).detail;
      if (!detail?.id) return;
      loadGen.current += 1;
      void refreshList();
      setDraft((cur) => (cur?.id === detail.id && cur?.kind === detail.kind ? null : cur));
    };
    window.addEventListener("ducky:focus-graph", onFocus);
    window.addEventListener("ducky:graph-deleted", onDeleted);
    return () => {
      window.removeEventListener("ducky:focus-graph", onFocus);
      window.removeEventListener("ducky:graph-deleted", onDeleted);
    };
  }, [loadOne, refreshList]);

  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [textSaveError, setTextSaveError] = useState(false);
  const persist = useCallback((next: AutomationDto) => {
    const api = getApi();
    const targetKind: WorkflowKind = next.kind === "pipeline" ? "pipeline" : "automation";
    const gen = loadGen.current;
    const operation = saveQueue.current.then(async () => {
    const payload = { ...next, kind: targetKind };
    const res = targetKind === "pipeline" ? await api?.save_pipeline?.(payload) : await api?.save_automation?.(payload);
    const row = res?.automation || res?.pipeline;
    if (row) {
      if (gen === loadGen.current) {
        setKind(targetKind);
        setDraft((current) => !next.id || current === next ? { ...row, kind: targetKind } : current);
        setSelectedId(row.id);
        setSectionsOpen((current) => ({ ...current, [targetKind]: true }));
      }
      await refreshList();
      return row;
    }
    return next;
    });
    saveQueue.current = operation.catch(() => undefined);
    return operation;
  }, [refreshList]);

  const createNew = (targetKind: WorkflowKind) => {
    setPickerKind(targetKind);
    setPickerOpen(true);
  };

  const createFromTemplate = useCallback(
    async (template: AutomationTemplateDto | null) => {
      const gen = ++loadGen.current;
      const created = await persist({
        id: "",
        name: template?.name || "Untitled",
        description: template?.description || "",
        enabled: true,
        kind: pickerKind,
        graph: template?.graph || emptyGraph(),
      } as AutomationDto);
      if (gen !== loadGen.current) return;
      setSelectedNodeId("");
      setSelectedEdge(null);
      setSpawn(null);
      setExpandedId("");
      setLog(null);
      if (created.id) setSelectedId(created.id);
    },
    [persist, pickerKind],
  );

  const graph = draft?.graph || emptyGraph();
  const overview = zoom < OVERVIEW_ZOOM;
  const nodesById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);
  const incomingIds = useMemo(() => new Set(graph.edges.map((edge) => edge.target)), [graph.edges]);
  const faces = useNodeFaces(graph.nodes.some((node) => node.type === "pipeline.agent"));
  const isExpanded = (id: string) => { const node = nodesById.get(id); return !overview && expandedId === id && !!node && hasNodeSettings(node, byType.get(node.type)); };

  const patchGraph = (fn: (g: AutomationGraphDto) => AutomationGraphDto) => {
    if (!draft) return;
    setDraft((current) => current ? { ...current, graph: fn(current.graph) } : current);
  };

  const updateNodeText = (id: string, patch: { label?: string; description?: string }) => {
    if (!draft) return;
    const next = { ...draft, graph: { ...draft.graph, nodes: draft.graph.nodes.map((node) => node.id === id ? { ...node, ...patch } : node) } };
    setDraft(next);
    setTextSaveError(false);
    void persist(next).catch(() => setTextSaveError(true));
  };

  const deleteNode = (id: string) => {
    patchGraph((graph) => ({ nodes: graph.nodes.filter((node) => node.id !== id), edges: graph.edges.filter((edge) => edge.source !== id && edge.target !== id) }));
    setSelectedNodeId("");
    setExpandedId("");
  };

  const addNodeAt = (entry: AutomationNodeDto, worldX: number, worldY: number) => {
    const node: AutomationGraphNodeDto = {
      id: nid(),
      type: entry.type,
      x: worldX,
      y: worldY,
      config: entry.type === "pipeline.agent" ? { ducky: "__new__" } : {},
      label: entry.label,
      description: entry.description || "",
    };
    patchGraph((g) => ({ ...g, nodes: [...g.nodes, node] }));
    setSelectedNodeId(node.id);
    setExpandedId("");
    setSpawn(null);
    setSpawnFilter("");
  };

  const saveDraft = () => {
    if (draft) void persist(draft).then(() => setTextSaveError(false)).catch(() => setTextSaveError(true));
  };

  const runTest = async () => {
    if (!draft?.id) return;
    const gen = loadGen.current;
    setBusy(true);
    try {
      await persist(draft);
      const res = isPipeline
        ? await getApi()?.run_pipeline?.(draft.id)
        : await getApi()?.run_automation?.(draft.id);
      if (res && gen === loadGen.current) {
        setLog(res);
        setLogOpen(true);
      }
    } finally {
      setBusy(false);
    }
  };

  const spawnGroups = useMemo(() => groupCatalog(catalog, spawnFilter), [catalog, spawnFilter]);

  const worldFromClient = (clientX: number, clientY: number) => {
    const board = boardRef.current?.getBoundingClientRect();
    if (!board) return { x: 0, y: 0 };
    return {
      x: (clientX - board.left - pan.x) / zoom,
      y: (clientY - board.top - pan.y) / zoom,
    };
  };

  const onBoardWheel = (e: React.WheelEvent) => {
    if (e.target instanceof Element && e.target.closest(".aw-node-props, .aw-log-dock, .aw-log-fab")) return;
    e.preventDefault();
    const next = Math.min(4, Math.max(0.25, zoom * (e.deltaY < 0 ? 1.08 : 0.92)));
    const box = boardRef.current?.getBoundingClientRect();
    if (box) setPan(zoomAt(pan, zoom, next, { x: e.clientX - box.left, y: e.clientY - box.top }));
    setZoom(next);
  };

  const copyLog = useCallback(
    (override?: string) => {
      const text = override || formatRunLog(log, draft?.name);
      if (!text) return;
      void copyText(text).then((ok) => {
        if (!ok) return;
        setLogCopied(true);
        window.setTimeout(() => setLogCopied(false), 2000);
      });
    },
    [log, draft?.name],
  );

  const onLogResizeDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    logResizeRef.current = { startY: e.clientY, startH: logHeight };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onLogResizeMove = (e: React.PointerEvent) => {
    const drag = logResizeRef.current;
    if (!drag) return;
    e.stopPropagation();
    setLogHeight(clampLogHeight(drag.startH + (drag.startY - e.clientY), boardRef.current?.clientHeight || 0));
  };

  const onLogResizeUp = () => {
    logResizeRef.current = null;
  };

  const onBoardPointerDown = (e: React.PointerEvent) => {
    if (pinch.current || (e.target instanceof Element && e.target.closest("button, input, textarea, select, .aw-node-props, .aw-wire"))) return;
    if ([0, 1, 2].includes(e.button)) {
      e.preventDefault();
      panRef.current = { x: pan.x, y: pan.y, px: e.clientX, py: e.clientY, button: e.button, moved: false };
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    if (e.button === 0) {
      setSelectedNodeId("");
      setWireFrom(null);
      setSelectedEdge(null);
      setSpawn(null);
    }
  };

  const onBoardPointerCapture = (e: React.PointerEvent) => {
    if (e.pointerType !== "touch" || (e.target instanceof Element && e.target.closest(".aw-node-props, .aw-log-dock, .aw-inline-edit, .choice-dropdown-menu, input, textarea, select"))) return;
    touches.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (touches.current.size !== 2) return;
    const [a, b] = [...touches.current.values()];
    const box = boardRef.current!.getBoundingClientRect();
    pinch.current = { distance: Math.max(1, Math.hypot(b.x - a.x, b.y - a.y)), center: { x: (a.x + b.x) / 2 - box.left, y: (a.y + b.y) / 2 - box.top }, pan, zoom };
    dragRef.current = null; resizeRef.current = null; panRef.current = null; wireRef.current = null;
    setWireFrom(null); setDraftWire(null);
    e.currentTarget.setPointerCapture(e.pointerId);
    e.stopPropagation();
  };

  const onBoardPointerMove = (e: React.PointerEvent) => {
    e.stopPropagation();
    if (touches.current.has(e.pointerId)) touches.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch.current && touches.current.size >= 2) {
      const [a, b] = [...touches.current.values()];
      const box = boardRef.current!.getBoundingClientRect();
      const start = pinch.current;
      const next = Math.max(0.25, Math.min(4, start.zoom * Math.hypot(b.x - a.x, b.y - a.y) / start.distance));
      const anchored = zoomAt(start.pan, start.zoom, next, start.center);
      setZoom(next);
      setPan({ x: anchored.x + (a.x + b.x) / 2 - box.left - start.center.x, y: anchored.y + (a.y + b.y) / 2 - box.top - start.center.y });
      return;
    }
    const resize = resizeRef.current;
    if (resize) {
      const width = Math.min(720, Math.max(280, resize.width + (e.clientX - resize.startX) / zoom));
      patchGraph((g) => ({ ...g, nodes: g.nodes.map((n) => n.id === resize.id ? { ...n, width } : n) }));
      return;
    }
    if (wireRef.current) {
      const w = worldFromClient(e.clientX, e.clientY);
      setDraftWire((d) => (d ? { ...d, toX: w.x, toY: w.y } : d));
      return;
    }
    if (panRef.current) {
      if (Math.hypot(e.clientX - panRef.current.px, e.clientY - panRef.current.py) > 5) panRef.current.moved = true;
      setPan({
        x: panRef.current.x + (e.clientX - panRef.current.px),
        y: panRef.current.y + (e.clientY - panRef.current.py),
      });
      return;
    }
    const drag = dragRef.current;
    if (!drag || !draft) return;
    const board = boardRef.current?.getBoundingClientRect();
    if (!board) return;
    const x = (e.clientX - board.left - pan.x) / zoom - drag.dx;
    const y = (e.clientY - board.top - pan.y) / zoom - drag.dy;
    patchGraph((g) => ({
      ...g,
      nodes: g.nodes.map((n) => (n.id === drag.id ? { ...n, x, y } : n)),
    }));
  };

  const connectNodes = (sourceId: string, targetId: string) => {
    if (!sourceId || !targetId || sourceId === targetId || byType.get(nodesById.get(targetId)?.type || "")?.role === "starter") return;
    const source = nodesById.get(sourceId);
    if (source && isEndNode(source)) return;
    patchGraph((g) => {
      const exists = g.edges.some((x) => x.source === sourceId && x.target === targetId);
      return exists ? g : { ...g, edges: [...g.edges, { source: sourceId, target: targetId, kind: "main" }] };
    });
  };

  const finishWire = (clientX: number, clientY: number) => {
    const w = wireRef.current;
    wireRef.current = null;
    setWireFrom(null);
    setDraftWire(null);
    if (!w) return;
    const stack = document.elementsFromPoint(clientX, clientY);
    let tid = "";
    for (const el of stack) {
      if (!(el instanceof Element)) continue;
      const port = el.closest("[data-aw-port]");
      if (port && port.getAttribute("data-aw-port") === w.dir) return;
      const nodeEl = el.closest("[data-aw-node]");
      const id = nodeEl?.getAttribute("data-aw-node") || "";
      if (id && id !== w.sourceId) {
        tid = id;
        break;
      }
    }
    if (!tid) return;
    if (w.dir === "out") connectNodes(w.sourceId, tid);
    else connectNodes(tid, w.sourceId);
  };

  const endPointer = (e: React.PointerEvent) => {
    e.stopPropagation();
    if (e.type === "pointercancel") { touches.current.clear(); pinch.current = null; }
    touches.current.delete(e.pointerId);
    if (pinch.current) {
      pinch.current = null;
      const remaining = [...touches.current.values()][0];
      panRef.current = remaining ? { x: pan.x, y: pan.y, px: remaining.x, py: remaining.y, button: 0, moved: true } : null;
      return;
    }
    if (panRef.current?.button === 2 && panRef.current.moved) suppressMenuUntil.current = Date.now() + 500;
    if (wireRef.current && e.type !== "pointercancel") finishWire(e.clientX, e.clientY);
    else { wireRef.current = null; setWireFrom(null); setDraftWire(null); }
    resizeRef.current = null;
    dragRef.current = null;
    panRef.current = null;
  };

  const startWire = (e: React.PointerEvent, node: AutomationGraphNodeDto, dir: "in" | "out") => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const { x: fromX, y: fromY } = portPoint(node, dir, isExpanded(node.id));
    wireRef.current = { sourceId: node.id, dir, fromX, fromY };
    setWireFrom(node.id);
    setDraftWire({ sourceId: node.id, fromX, fromY, toX: fromX, toY: fromY });
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onBoardContextMenu = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    if (t.closest(".aw-log-dock") || t.closest(".aw-log-fab")) return;
    if (t.closest("input, textarea, select")) return;
    e.preventDefault();
    if (Date.now() < suppressMenuUntil.current || (panRef.current?.button === 2 && panRef.current.moved)) return;
    if (!draft) return;
    const world = worldFromClient(e.clientX, e.clientY);
    setSpawn({ x: Math.max(8, Math.min(e.clientX, window.innerWidth - 328)), y: Math.max(8, Math.min(e.clientY, window.innerHeight - 520)), worldX: world.x, worldY: world.y });
    setSpawnFilter("");
  };

  const startNodeDrag = (e: React.PointerEvent, node: AutomationGraphNodeDto) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    const board = boardRef.current?.getBoundingClientRect();
    if (!board) return;
    dragRef.current = {
      id: node.id,
      dx: (e.clientX - board.left - pan.x) / zoom - node.x,
      dy: (e.clientY - board.top - pan.y) / zoom - node.y,
    };
    setSelectedNodeId(node.id);
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  useEffect(() => {
    const cancel = () => {
      touches.current.clear(); pinch.current = null; panRef.current = null;
      dragRef.current = null; resizeRef.current = null; wireRef.current = null;
      setWireFrom(null); setDraftWire(null);
    };
    window.addEventListener("blur", cancel);
    return () => window.removeEventListener("blur", cancel);
  }, []);

  const fitGraph = () => {
    const box = boardRef.current;
    if (!box || !graph.nodes.length) return;
    const left = Math.min(...graph.nodes.map((n) => n.x));
    const top = Math.min(...graph.nodes.map((n) => n.y));
    const right = Math.max(...graph.nodes.map((n) => n.x + nodeWidth(n, isExpanded(n.id))));
    const bottom = Math.max(...graph.nodes.map((n) => n.y + (isExpanded(n.id) ? 440 : 76)));
    const board = box.getBoundingClientRect();
    const sidebar = listRef.current?.getBoundingClientRect();
    const toolbar = toolbarRef.current?.getBoundingClientRect();
    const compact = box.clientWidth <= 680;
    const insetX = compact ? 24 : Math.max(24, (sidebar?.right || board.left) - board.left + 24);
    const insetY = Math.max(24, (toolbar?.bottom || board.top) - board.top + 24, compact ? (sidebar?.bottom || board.top) - board.top + 24 : 0);
    const width = Math.max(80, box.clientWidth - insetX - 24);
    const height = Math.max(80, box.clientHeight - insetY - (logOpen ? logHeight + 24 : 64));
    const next = Math.min(1, Math.max(0.25, Math.min(width / (right - left), height / (bottom - top))));
    setZoom(next);
    setPan({ x: insetX + (width - (right - left) * next) / 2 - left * next, y: insetY + (height - (bottom - top) * next) / 2 - top * next });
  };

  const logCount = log?.steps?.length || (runLogHasContent(log) ? 1 : 0);

  return (
    <div className="aw-root">
      <aside className="aw-list" ref={listRef} aria-label="Workflows">
        <div className="aw-list-head"><strong>Workflows</strong></div>
        <div className="aw-list-sections">
          {WORKFLOW_SECTIONS.map((section) => (
            <section className="aw-workflow-section" key={section.kind}>
              <div className="aw-section-head">
                <button type="button" className="aw-section-toggle" aria-label={section.label} aria-expanded={sectionsOpen[section.kind]} aria-controls={sectionId + "-" + section.kind} onClick={() => setSectionsOpen((current) => ({ ...current, [section.kind]: !current[section.kind] }))}>
                  <span className="aw-section-chevron" aria-hidden="true">{sectionsOpen[section.kind] ? "▾" : "▸"}</span>
                  <strong>{section.label}</strong><small>{rows[section.kind].length}</small>
                </button>
                <button type="button" className="aw-icon-button" title={"New " + section.kind} aria-label={"New " + section.kind} onClick={() => createNew(section.kind)}><span aria-hidden="true">➕</span></button>
              </div>
              <ul className="aw-list-ul" id={sectionId + "-" + section.kind} hidden={!sectionsOpen[section.kind]}>
                {rows[section.kind].map((row) => (
                  <li key={row.id}>
                    <button type="button" className={"aw-list-row" + (draft && kind === section.kind && row.id === selectedId ? " is-active" : "")} aria-current={draft && kind === section.kind && row.id === selectedId ? "true" : undefined} onClick={() => void loadOne(row.id, section.kind)}>
                      <span>{row.name || "Untitled"}</span>
                      <span className="aw-list-meta" title={row.enabled ? "Enabled" : "Disabled"}>{row.enabled ? "on" : "off"}</span>
                    </button>
                  </li>
                ))}
                {!rows[section.kind].length && <li className="aw-section-empty">No {section.label.toLowerCase()} yet</li>}
              </ul>
            </section>
          ))}
        </div>
      </aside>
      <div className="aw-main">
        <div className="aw-toolbar" ref={toolbarRef} role="toolbar" aria-label="Workflow actions">
          {draft ? (
            <>
              <div className="aw-toolbar-fields">
              <input
                className="aw-name"
                aria-label="Workflow name"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                onBlur={saveDraft}
              />
              {isPipeline ? (
                <input
                  className="aw-name aw-description"
                  aria-label="Workflow description"
                  placeholder="Description (so a ducky can pick this recipe)"
                  value={draft.description || ""}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                  onBlur={saveDraft}
                />
              ) : null}
              </div>
              <div className="aw-toolbar-actions">
              <button type="button" aria-label="Enabled" title={draft.enabled ? "Disable workflow" : "Enable workflow"} aria-pressed={draft.enabled} onClick={() => { const next = { ...draft, enabled: !draft.enabled }; setDraft(next); void persist(next); }}><span aria-hidden="true">{draft.enabled ? "✅" : "⏸️"}</span></button>
              <button type="button" title="Save" aria-label="Save" onClick={saveDraft}><span aria-hidden="true">💾</span></button>
              <button type="button" title={busy ? "Running…" : "Test"} aria-label={busy ? "Running…" : "Test"} onClick={() => void runTest()} disabled={busy || !draft.id}><span aria-hidden="true">{busy ? "⏳" : "▶️"}</span></button>
              <button
                type="button" title="Duplicate" aria-label="Duplicate"
                onClick={async () => {
                  if (!draft.id) return;
                  const copy = {
                    ...draft,
                    id: "",
                    name: `${draft.name} copy`,
                  };
                  await persist(copy);
                }}
              >
                <span aria-hidden="true">📋</span>
              </button>
              <button
                type="button" title="Delete" aria-label="Delete"
                onClick={async () => {
                  if (!draft.id) return;
                  const gen = ++loadGen.current;
                  if (isPipeline) await getApi()?.delete_pipeline?.(draft.id);
                  else await getApi()?.delete_automation?.(draft.id);
                  if (gen === loadGen.current) { setDraft(null); setSelectedId(""); }
                  await refreshList();
                }}
              >
                <span aria-hidden="true">🗑️</span>
              </button>
              </div>
            </>
          ) : (
            <span className="aw-empty-hint">
              Select a pipeline or automation, or use ➕ to create a workflow.
            </span>
          )}
        </div>
        <div
          ref={boardRef}
          className={`aw-board${overview ? " is-overview" : ""}`}
          onWheel={onBoardWheel}
          onPointerDown={onBoardPointerDown}
          onPointerDownCapture={onBoardPointerCapture}
          onPointerMove={onBoardPointerMove}
          onPointerUp={endPointer}
          onPointerCancel={endPointer}
          onContextMenu={onBoardContextMenu}
        >
          <div className="aw-world" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}>
            <svg className="aw-wires" width={8000} height={8000}>
              {graph.edges.map((e, i) => {
                const a = nodesById.get(e.source);
                const b = nodesById.get(e.target);
                if (!a || !b) return null;
                const { x: x1, y: y1 } = portPoint(a, "out", isExpanded(a.id));
                const { x: x2, y: y2 } = portPoint(b, "in", isExpanded(b.id));
                const c = Math.max(40, (x2 - x1) / 2);
                return (
                  <path
                    key={`${e.source}-${e.target}-${e.kind}-${i}`}
                    d={`M ${x1} ${y1} C ${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`}
                    className={`aw-wire aw-wire--${e.kind}${selectedEdge === i || selectedNodeId === e.source || selectedNodeId === e.target ? " is-hot" : ""}`}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      setSelectedEdge(i);
                    }}
                  />
                );
              })}
              {draftWire ? (
                <path
                  d={`M ${draftWire.fromX} ${draftWire.fromY} C ${draftWire.fromX + 40} ${draftWire.fromY}, ${draftWire.toX - 40} ${draftWire.toY}, ${draftWire.toX} ${draftWire.toY}`}
                  className="aw-wire aw-wire--draft"
                />
              ) : null}
            </svg>
            {graph.nodes.map((node) => {
              const meta = byType.get(node.type);
              const expanded = isExpanded(node.id);
              const configurable = hasNodeSettings(node, meta);
              const role = isEndNode(node) ? "end" : meta?.role === "starter" || !incomingIds.has(node.id) ? "starter" : node.type === "pipeline.agent" ? "agent" : "action";
              const label = nodeLabel(node, meta);
              return (
                <div
                  key={node.id}
                  data-aw-node={node.id}
                  className={`aw-node aw-node--${role}${selectedNodeId === node.id ? " is-selected" : ""}${wireFrom === node.id ? " is-wiring" : ""}${expanded ? " is-expanded" : ""}`}
                  style={{ left: node.x, top: node.y, width: nodeWidth(node, expanded) }}
                >
                  {meta?.role !== "starter" ? <button
                    type="button"
                    aria-label={`Connect to ${label}`}
                    data-aw-port="in"
                    className="aw-port aw-port--in"
                    data-aw-node={node.id}
                    onPointerDown={(e) => startWire(e, node, "in")}
                    onPointerMove={onBoardPointerMove}
                    onPointerUp={endPointer}
                    onPointerCancel={endPointer}
                  /> : null}
                  <div className="aw-node-card">
                    <div className="aw-node-body" onPointerDown={(e) => startNodeDrag(e, node)}
                      onDoubleClick={() => { if (configurable) { setExpandedId(expandedId === node.id ? "" : node.id); if (overview) setZoom(1); } }}
                      title={label}>
                      <NodeIcon meta={meta} node={node} faces={faces} />
                      <div className="aw-node-heading">
                        <InlineNodeText key={selectedId + node.id + "-label"} value={label} label="Node name" onCommit={(value) => updateNodeText(node.id, { label: value })} />
                        {!overview ? <InlineNodeText key={selectedId + node.id + "-description"} value={node.description ?? meta?.description ?? ""} label="Node description" placeholder="Add description" multiline onCommit={(value) => updateNodeText(node.id, { description: value })} /> : null}
                      </div>
                    </div>
                    <div className="aw-node-actions">
                    {!overview && configurable ? <button
                      type="button"
                      title={expanded ? "Collapse node" : "Edit node"}
                      aria-label={expanded ? "Collapse node" : "Edit node"}
                      className="aw-node-expand-toggle"
                      aria-expanded={expanded}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedNodeId(node.id);
                        setExpandedId(expanded ? "" : node.id);
                      }}
                    >
                      {expanded ? <Icons.ChevronDown /> : <Icons.Sliders />}
                    </button> : null}
                    <button type="button" className="aw-node-delete" title="Delete node" aria-label={"Delete " + label} onPointerDown={(event) => event.stopPropagation()} onClick={() => deleteNode(node.id)}>🗑️</button>
                    </div>
                    {expanded ? (
                      <div className="aw-node-props aw-node-props--open" onPointerDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()}>
                        <NodeSettings
                          node={node}
                          meta={meta}
                          onChange={(next) =>
                            patchGraph((g) => ({
                              ...g,
                              nodes: g.nodes.map((n) => (n.id === next.id ? next : n)),
                            }))
                          }
                        />
                      </div>
                    ) : null}
                  </div>
                  {expanded ? <button type="button" className="aw-node-resize" aria-label="Resize node" title="Drag to make wider"
                    onPointerDown={(e) => {
                      if (e.button !== 0) return;
                      e.preventDefault(); e.stopPropagation();
                      resizeRef.current = { id: node.id, startX: e.clientX, width: nodeWidth(node, true) };
                      e.currentTarget.setPointerCapture(e.pointerId);
                    }}
                    onKeyDown={(e) => { if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); const width = Math.min(720, Math.max(280, nodeWidth(node, true) + (e.key === "ArrowRight" ? 20 : -20))); patchGraph((g) => ({ ...g, nodes: g.nodes.map((n) => n.id === node.id ? { ...n, width } : n) })); } }}
                  /> : null}
                  {!isEndNode(node) && <button
                    type="button"
                    aria-label={`Connect from ${label}`}
                    data-aw-port="out"
                    className="aw-port aw-port--out"
                    data-aw-node={node.id}
                    onPointerDown={(e) => startWire(e, node, "out")}
                    onPointerMove={onBoardPointerMove}
                    onPointerUp={endPointer}
                    onPointerCancel={endPointer}
                  />}
                </div>
              );
            })}
          </div>
        </div>
        {textSaveError ? <p className="aw-text-save-error" role="alert">Could not save changes. Use Save to retry.</p> : null}
        <div className="aw-canvas-controls">
          <button type="button" title="Add nodes" aria-label="Add nodes" onClick={() => { const box = boardRef.current?.getBoundingClientRect(); if (!box) return; const world = worldFromClient(box.left + box.width / 2, box.top + box.height / 2); setSpawn({ x: Math.max(8, Math.min(box.left + 12, window.innerWidth - 328)), y: Math.max(8, Math.min(box.top + 12, window.innerHeight - 520)), worldX: world.x, worldY: world.y }); setSpawnFilter(""); }} disabled={!draft}>➕</button>
          <button type="button" title="Zoom out" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.25, z / 1.2))}>➖</button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(4, z * 1.2))}>➕</button>
          <button type="button" title="Fit graph" aria-label="Fit graph" onClick={fitGraph}>🔍</button>
        </div>
        {selectedEdge !== null && graph.edges[selectedEdge] ? <div className="aw-connection-tools">
          <span>Connection</span>
          <ChoiceDropdown aria-label="Connection route" value={graph.edges[selectedEdge].kind} options={[{ value: "main", label: "Next" }, { value: "true", label: "True" }, { value: "false", label: "False" }, { value: "each", label: "Each item" }, { value: "done", label: "Done" }]} onChange={(value) => patchGraph((g) => ({ ...g, edges: g.edges.map((edge, i) => i === selectedEdge ? { ...edge, kind: value } : edge) }))} size="compact" />
          <button type="button" onClick={() => { patchGraph((g) => ({ ...g, edges: g.edges.filter((_, i) => i !== selectedEdge) })); setSelectedEdge(null); }}>Disconnect</button>
          <button type="button" aria-label="Close connection controls" onClick={() => setSelectedEdge(null)}><Icons.Close /></button>
        </div> : null}
        <button
          type="button"
          className={`aw-log-fab${logOpen ? " is-open" : ""}`}
          title={logOpen ? "Hide run log" : "Run log"}
          aria-expanded={logOpen}
          onClick={() => setLogOpen((v) => !v)}
        >
          <Icons.Sliders />
          {logCount ? <span className="aw-log-fab-badge">{logCount}</span> : null}
        </button>
        {logOpen ? (
          <div
            className="aw-log-dock"
            style={{ height: logHeight }}
            onPointerDown={(e) => e.stopPropagation()}
            onPointerMove={(e) => e.stopPropagation()}
            onPointerUp={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
              const picked = window.getSelection()?.toString().trim();
              copyLog(picked || undefined);
            }}
          >
            <div
              className="aw-log-resize"
              title="Drag to resize"
              onPointerDown={onLogResizeDown}
              onPointerMove={onLogResizeMove}
              onPointerUp={onLogResizeUp}
              onPointerCancel={onLogResizeUp}
            />
            <div className="aw-log-dock-head">
              <strong>Run log</strong>
              <button
                type="button"
                className="aw-log-copy"
                title="Copy log"
                disabled={!runLogHasContent(log)}
                onClick={() => copyLog()}
              >
                {logCopied ? "Copied" : "Copy log"}
              </button>
              <button type="button" className="icon-btn" title="Hide" onClick={() => setLogOpen(false)}>
                ×
              </button>
            </div>
            <div className="aw-log-dock-body selectable-text">
              {runLogHasContent(log) ? (
                <ol>
                  {log?.ok === false && log.error ? <li className="is-err">{log.error}</li> : null}
                  {(log?.steps || []).map((s, i) => (
                    <li key={i} className={s.ok === false ? "is-err" : ""}>
                      {s.label || s.type} {s.ok === false ? `— ${s.error}` : "ok"}
                    </li>
                  ))}
                </ol>
              ) : (
                <p>
                  {isPipeline
                    ? "Test a pipeline to see steps here. Return to user sends results back to your chat."
                    : "Test a graph to see steps here. Timers only fire while the panel is running."}
                </p>
              )}
            </div>
          </div>
        ) : null}
      </div>
      {spawn ? (
        <div className="aw-spawn-scrim" onMouseDown={() => setSpawn(null)}>
          <div
            className="aw-spawn-menu"
            role="dialog"
            aria-label="Add node"
            style={{ left: spawn.x, top: spawn.y, maxHeight: `min(512px, calc(100dvh - ${spawn.y + 8}px))` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="aw-menu-actions" role="toolbar" aria-label="Node actions">
              <button type="button" title="Collapse all nodes" aria-label="Collapse all nodes" onClick={() => setExpandedId("")}><span aria-hidden="true">📦</span></button>
              <button type="button" title="Arrange nodes" aria-label="Arrange nodes" onClick={() => { patchGraph((g) => arrangeGraph(g, overview ? "" : expandedId)); setSpawn(null); }}><span aria-hidden="true">🧹</span></button>
              <button type="button" title="Fit graph" aria-label="Fit graph" onClick={() => { fitGraph(); setSpawn(null); }}><span aria-hidden="true">🔍</span></button>
            </div>
            <input
              ref={spawnSearchRef}
              className="aw-spawn-search"
              aria-label="Filter nodes"
              placeholder="Filter nodes"
              value={spawnFilter}
              onChange={(e) => setSpawnFilter(e.target.value)}
            />
            <div className="aw-spawn-section"><span>Add a node</span><button type="button" onClick={() => setGroupsCollapsed((v) => !v)}>{groupsCollapsed ? "Expand groups" : "Collapse groups"}</button></div>
            <div className="aw-spawn-scroll">
              {spawnGroups.length ? (
                spawnGroups.map(([name, tiles]) => (
                  <details key={`${name}-${groupsCollapsed}-${!!spawnFilter}`} className="aw-acc" open={!groupsCollapsed || !!spawnFilter}>
                    <summary><NodeIcon meta={tiles[0]} /><span>{name}</span><small>{tiles.length}</small></summary>
                    {tiles.map((t) => (
                      <button
                        key={t.type}
                        type="button"
                        className="aw-tile"
                        onClick={() => addNodeAt(t, spawn.worldX, spawn.worldY)}
                      >
                        <NodeIcon meta={t} />
                        <span className="aw-tile-text"><strong>{t.label}</strong><small>{t.description}</small></span>
                      </button>
                    ))}
                  </details>
                ))
              ) : (
                <p className="aw-empty-hint">No matching nodes.</p>
              )}
            </div>
          </div>
        </div>
      ) : null}
      <AutomationTemplatePicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={(t) => void createFromTemplate(t)}
        currentGraph={draft?.kind === pickerKind ? draft.graph : null}
        system={pickerKind}
      />
    </div>
  );
}
