import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useWorkflowHistory, editableWorkflow } from "./useWorkflowHistory";
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
  WorkflowOwnersDto,
} from "../types/panel";
import { getApi } from "../hooks/usePanelApi";
import { useConfirmModal } from "../contexts/ConfirmModalContext";
import { installPanelPushBus, subscribePanelPush } from "../hooks/usePanelPushBus";
import { setVisibleInterval } from "../utils/visibleInterval";
import { LOCAL_OWNER, OwnerIcon, WorkflowList, ownerHelp, ownerName } from "./WorkflowList";
import { takePendingGraphFocus } from "../hooks/graphActivity";
import { Icons } from "../icons/Icons";
import { copyText } from "../utils/copyText";
import { formatRunLog, runLogHasContent } from "./runLog";

import { isEndNode, nodeLabel, NodeIcon, useNodeFaces } from "./NodeVisuals";
import { cleanGroups, groupBounds, groupNodes, intersects, selectionRect, ungroupNodes, type GraphRect } from "./workflowGroups";
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

/** Team rounds while this view is open (on open, on focus, each minute); the host caps
 * one per team per minute. */
const SYNC_EVERY_MS = 60_000;

export function AutomationsView() {
  const sectionId = useId();
  const { confirm } = useConfirmModal();
  const [listCollapsed, setListCollapsed] = useState(false);
  const [rows, setRows] = useState<AutomationSummaryDto[]>([]);
  const [owners, setOwners] = useState<WorkflowOwnersDto>({ owners: [LOCAL_OWNER] });
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [pickerOwner, setPickerOwner] = useState(LOCAL_OWNER.id);
  const [actionError, setActionError] = useState("");
  const listRef = useRef<HTMLElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const [catalog, setCatalog] = useState<AutomationNodeDto[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const history = useWorkflowHistory();
  const { draft, setDraft, replace: acknowledgeDraft, reset: resetDraft, begin: beginEdit, end: endEdit } = history;
  const [versions, setVersions] = useState<{ id: string; name: string; saved_at: number; node_count: number; note?: string }[]>([]);
  const [historyStatus, setHistoryStatus] = useState("");
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [nodeHeights, setNodeHeights] = useState<Record<string, number>>({});
  const [marquee, setMarquee] = useState<GraphRect | null>(null);
  const marqueeRef = useRef<{ pointerId: number; start: { x: number; y: number }; base: string[] } | null>(null);
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
  const dragRef = useRef<{ start: { x: number; y: number }; origins: { id: string; x: number; y: number }[]; clickIds: string[]; moved: boolean } | null>(null);
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

  const refreshList = useCallback(async () => {
    const api = getApi();
    const [listed, folders] = await Promise.all([api?.list_workflows?.(), api?.workflow_owners?.()]);
    setRows(listed?.workflows || []);
    if (folders?.owners?.length) setOwners(folders);
    setNowMs(Date.now());
  }, []);

  useEffect(() => { void refreshList(); }, [refreshList]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await getApi()?.list_workflow_nodes?.();
      if (!cancelled) setCatalog(result?.nodes || []);
    })();
    return () => { cancelled = true; };
  }, []);

  // Teams: ask the Store which teams this account has once per open, then sync each
  // visible team while the view is open. Another chat's edits and finished rounds
  // arrive as graphs_changed.
  const hasTeams = !!owners.owners?.some((owner) => owner.kind === "team");
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const folders = await getApi()?.workflow_owners?.(true);
      if (!cancelled && folders?.owners?.length) setOwners(folders);
    })();
    installPanelPushBus();
    const stop = subscribePanelPush((event) => {
      // A team round started elsewhere (a plugin's scope bar) can bring workflow changes too.
      const workflowsSynced = event.type === "plugin_scope_changed" && !!event.plugins?.includes("ducky.automations");
      if (event.type === "graphs_changed" || event.type === "duckyos_account_changed" || workflowsSynced) void refreshList();
    });
    return () => { cancelled = true; stop(); };
  }, [refreshList]);
  useEffect(() => {
    if (!hasTeams) return;
    const sync = () => void getApi()?.workflow_sync?.(false);
    sync();
    window.addEventListener("focus", sync);
    const stop = setVisibleInterval(() => { sync(); void refreshList(); }, SYNC_EVERY_MS);
    return () => { window.removeEventListener("focus", sync); stop(); };
  }, [hasTeams, refreshList]);

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
  const loadOne = useCallback(async (id: string) => {
    const gen = ++loadGen.current;
    const res = await getApi()?.get_workflow?.(id);
    if (gen !== loadGen.current) return;
    const row = res?.workflow;
    if (row) {
      resetDraft(row);
      setVersions([]);
      setHistoryStatus("");
      setActionError("");
      setSelectedId(id);
      setSpawn(null);
      setSelectedNodeIds([]);
      setSelectedEdge(null);
      setExpandedId("");
      setLog((row.runs || []).slice(-1)[0] || null);
    }
  }, [resetDraft]);

  useEffect(() => {
    const open = (id: string) => {
      if (!id) return;
      void refreshList();
      void loadOne(id);
      setLogOpen(true);
    };
    open(takePendingGraphFocus());
    const onFocus = (ev: Event) => {
      const detail = (ev as CustomEvent<{ id?: string }>).detail;
      if (!detail?.id) return;
      takePendingGraphFocus();
      open(detail.id);
    };
    const onDeleted = (ev: Event) => {
      const detail = (ev as CustomEvent<{ id?: string }>).detail;
      if (!detail?.id) return;
      loadGen.current += 1;
      void refreshList();
      setDraft((cur) => (cur?.id === detail.id ? null : cur));
    };
    window.addEventListener("ducky:focus-graph", onFocus);
    window.addEventListener("ducky:graph-deleted", onDeleted);
    return () => {
      window.removeEventListener("ducky:focus-graph", onFocus);
      window.removeEventListener("ducky:graph-deleted", onDeleted);
    };
  }, [loadOne, refreshList, setDraft]);

  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [textSaveError, setTextSaveError] = useState(false);
  const readOnly = !!draft?.owner?.readOnly;
  const persist = useCallback((next: AutomationDto, owner = "") => {
    const api = getApi();
    const gen = loadGen.current;
    const operation = saveQueue.current.then(async () => {
    if (next.id && next.owner?.readOnly) return next;  // someone else's team workflow: never pushed from here
    const res = await api?.save_workflow?.(next, owner || undefined);
    const row = res?.workflow;
    if (row) {
      if (gen === loadGen.current) {
        acknowledgeDraft((current) => !next.id || current === next ? row : current);
        setSelectedId(row.id);
      }
      await refreshList();
      return row;
    }
    throw new Error(res?.error || "Could not save workflow");
    });
    saveQueue.current = operation.catch(() => undefined);
    return operation;
  }, [refreshList, acknowledgeDraft]);

  const createNew = (ownerId: string) => {
    setPickerOwner(ownerId);
    setPickerOpen(true);
  };

  const createFromTemplate = useCallback(
    async (template: AutomationTemplateDto | null) => {
      const gen = ++loadGen.current;
      let created: AutomationDto;
      try {
        created = await persist({
          id: "",
          name: template?.name || "Untitled",
          description: template?.description || "",
          enabled: true,
          graph: template?.graph || emptyGraph(),
        } as AutomationDto, pickerOwner);
      } catch (error) {
        setActionError(error instanceof Error ? error.message : "Could not create workflow");
        return;
      }
      if (gen !== loadGen.current) return;
      setSelectedNodeIds([]);
      setSelectedEdge(null);
      setSpawn(null);
      setExpandedId("");
      setLog(null);
      setActionError("");
      if (created.id) setSelectedId(created.id);
    },
    [persist, pickerOwner],
  );

  /** Copy (new id) or move a workflow to Local or a team. */
  const sendTo = async (value: string) => {
    if (!draft?.id) return;
    const [action, target] = [value.slice(0, 4), value.slice(5)];
    const from = draft.owner || LOCAL_OWNER;
    const to = owners.owners?.find((owner) => owner.id === target) || LOCAL_OWNER;
    if (action === "move" && from.kind === "team") {
      const ok = await confirm({ title: `Move out of ${from.label}?`, message: `Members of ${from.label} will lose this workflow. It moves to ${ownerName(to)}.`, confirmLabel: "Move" });
      if (ok !== true) return;
    }
    await saveQueue.current;
    const res = await getApi()?.copy_workflow?.(draft.id, target, action === "move");
    if (!res?.workflow) { setActionError(res?.error || "Could not copy workflow"); return; }
    setActionError("");
    await refreshList();
    await loadOne(res.workflow.id);
  };

  const graph = draft?.graph || emptyGraph();
  const overview = zoom < OVERVIEW_ZOOM;
  const nodesById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);
  const incomingIds = useMemo(() => new Set(graph.edges.map((edge) => edge.target)), [graph.edges]);
  const faces = useNodeFaces(graph.nodes.some((node) => node.type === "pipeline.agent"));
  const isExpanded = (id: string) => { const node = nodesById.get(id); return !overview && expandedId === id && !!node && hasNodeSettings(node, byType.get(node.type)); };

  const patchGraph = (fn: (g: AutomationGraphDto) => AutomationGraphDto) => {
    if (!draft || readOnly) return;
    setDraft((current) => current ? { ...current, graph: cleanGroups(fn(current.graph)) } : current);
  };

  const updateNodeText = (id: string, patch: { label?: string; description?: string }) => {
    if (!draft || readOnly) return;
    const next = { ...draft, graph: { ...draft.graph, nodes: draft.graph.nodes.map((node) => node.id === id ? { ...node, ...patch } : node) } };
    setDraft(next);
    setTextSaveError(false);
    void persist(next).catch(() => setTextSaveError(true));
  };

  const deleteNode = (id: string) => {
    patchGraph((graph) => ({ ...graph, nodes: graph.nodes.filter((node) => node.id !== id), edges: graph.edges.filter((edge) => edge.source !== id && edge.target !== id) }));
    setSelectedNodeIds([]);
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
    setSelectedNodeIds([node.id]);
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
      const res = await getApi()?.run_workflow?.(draft.id);
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

  const nodeSize = (node: AutomationGraphNodeDto) => ({
    width: nodeWidth(node, isExpanded(node.id)),
    height: nodeHeights[node.id] || (isExpanded(node.id) ? 440 : 76),
  });
  const groupBoxes = (graph.groups || []).map((group) => ({ group, bounds: groupBounds(group, graph.nodes, nodeSize) })).filter((entry) => entry.bounds !== null);

  // Measure real settings panels so boxes also follow expanding/resizing node cards.
  const nodeIdsKey = graph.nodes.map((node) => node.id).join("\n");
  useEffect(() => {
    const cards = [...(boardRef.current?.querySelectorAll<HTMLElement>(".aw-node-card") || [])];
    const measure = () => {
      const heights: Record<string, number> = {};
      for (const card of cards) {
        const id = card.closest("[data-aw-node]")?.getAttribute("data-aw-node");
        if (id && card.offsetHeight) heights[id] = card.offsetHeight;
      }
      setNodeHeights((previous) => Object.keys(previous).length === Object.keys(heights).length && Object.keys(heights).every((id) => heights[id] === previous[id]) ? previous : heights);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    cards.forEach((card) => observer.observe(card));
    return () => observer.disconnect();
  }, [nodeIdsKey, selectedId, expandedId, overview]);

  const saveGraphChange = (fn: (current: AutomationGraphDto) => AutomationGraphDto) => {
    if (!draft || readOnly) return;
    const nextGraph = fn(draft.graph);
    if (nextGraph === draft.graph) return;
    const next = { ...draft, graph: nextGraph };
    setDraft(next);
    setTextSaveError(false);
    void persist(next).catch(() => setTextSaveError(true));
  };

  const goToEdit = (index: number) => {
    if (readOnly) return;
    const next = history.go(index);
    if (!next) return;
    setSelectedNodeIds([]); setSelectedEdge(null); setSpawn(null);
    void persist(next).then(() => setTextSaveError(false)).catch(() => setTextSaveError(true));
  };

  const loadVersions = async () => {
    if (!draft?.id) return;
    const gen = loadGen.current;
    setVersions([]); setHistoryStatus("Loading saved versions…");
    try {
      await saveQueue.current;
      const result = await getApi()?.list_workflow_versions?.(draft.id);
      if (gen !== loadGen.current) return;
      if (!result || result.ok === false) throw new Error("Could not load versions");
      setVersions(result.versions || []); setHistoryStatus("");
    } catch { if (gen === loadGen.current) setHistoryStatus("Could not load saved versions. Reopen History to retry."); }
  };

  const restoreVersion = async (versionId: string) => {
    const current = history.current.current;
    if (!current) return;
    const gen = loadGen.current;
    try {
      const result = await getApi()?.get_workflow_version?.(current.id, versionId);
      if (gen !== loadGen.current) return;
      if (!result?.workflow || result.ok === false) throw new Error("Version not found");
      // Keep any in-flight edits in the journal and retain the current identity and run log.
      const next = { ...history.current.current!, ...editableWorkflow(result.workflow) };
      endEdit(); setDraft(next, "Restore saved version");
      setSelectedNodeIds([]); setSelectedEdge(null); setExpandedId("");
      await persist(next); setTextSaveError(false); setHistoryStatus("");
    } catch { if (gen === loadGen.current) { setTextSaveError(true); setHistoryStatus("Could not restore version."); } }
  };

  const onGraphKeyDown = (event: React.KeyboardEvent) => {
    if (event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable='true']")) return;
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && !event.altKey && (key === "z" || key === "y") && draft) {
      event.preventDefault(); event.stopPropagation();
      goToEdit(history.index + (key === "y" || event.shiftKey ? 1 : -1));
      return;
    }
    if ((event.ctrlKey || event.metaKey) && !event.altKey && key === "g" && draft) {
      event.preventDefault();
      event.stopPropagation();
      if (event.repeat) return;
      saveGraphChange((current) => event.shiftKey ? ungroupNodes(current, selectedNodeIds) : groupNodes(current, selectedNodeIds, nid()));
    } else if (event.key === "Escape") {
      endEdit();
      if (marqueeRef.current) setSelectedNodeIds(marqueeRef.current.base);
      else setSelectedNodeIds([]);
      marqueeRef.current = null;
      setMarquee(null);
      dragRef.current = null;
    }
  };

  const toggleNodeSelection = (event: React.PointerEvent, id: string) => {
    if (event.button !== 0 || !(event.ctrlKey || event.metaKey) || event.shiftKey) return;
    if (event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable='true']")) return;
    event.preventDefault();
    event.stopPropagation();
    boardRef.current?.focus({ preventScroll: true });
    setSelectedEdge(null);
    setSelectedNodeIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  };

  const startSelectionDrag = (event: React.PointerEvent, ids: string[], clickIds = ids) => {
    event.preventDefault();
    event.stopPropagation();
    boardRef.current?.focus({ preventScroll: true });
    setSelectedEdge(null);
    setSelectedNodeIds(ids);
    beginEdit();
    dragRef.current = {
      start: worldFromClient(event.clientX, event.clientY),
      origins: graph.nodes.filter((node) => ids.includes(node.id)).map(({ id, x, y }) => ({ id, x, y })),
      clickIds, moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const updateMarquee = (clientX: number, clientY: number) => {
    const selection = marqueeRef.current;
    if (!selection) return;
    const bounds = selectionRect(selection.start, worldFromClient(clientX, clientY));
    setMarquee(bounds);
    setSelectedNodeIds([...new Set([...selection.base, ...graph.nodes.filter((node) => intersects(bounds, { x: node.x, y: node.y, ...nodeSize(node) })).map((node) => node.id)])]);
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
    if (marqueeRef.current || pinch.current || (e.target instanceof Element && e.target.closest("button, input, textarea, select, .aw-node-props, .aw-wire"))) return;
    if ([0, 1, 2].includes(e.button)) {
      e.preventDefault();
      panRef.current = { x: pan.x, y: pan.y, px: e.clientX, py: e.clientY, button: e.button, moved: false };
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    if (e.button === 0) {
      setSelectedNodeIds([]);
      setWireFrom(null);
      setSelectedEdge(null);
      setSpawn(null);
    }
  };

  const onBoardPointerCapture = (e: React.PointerEvent) => {
    if (draft && e.button === 0 && (e.ctrlKey || e.metaKey) && e.shiftKey && !(e.target instanceof Element && e.target.closest("input, textarea, select, [contenteditable='true']"))) {
      e.preventDefault(); e.stopPropagation();
      boardRef.current?.focus({ preventScroll: true });
      marqueeRef.current = { pointerId: e.pointerId, start: worldFromClient(e.clientX, e.clientY), base: selectedNodeIds };
      dragRef.current = null; panRef.current = null; resizeRef.current = null;
      setSelectedEdge(null); setSpawn(null);
      setMarquee({ ...marqueeRef.current.start, width: 0, height: 0 });
      e.currentTarget.setPointerCapture(e.pointerId);
      return;
    }
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
    if (marqueeRef.current) {
      if (e.pointerId === marqueeRef.current.pointerId) updateMarquee(e.clientX, e.clientY);
      return;
    }
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
    const point = worldFromClient(e.clientX, e.clientY);
    const dx = point.x - drag.start.x, dy = point.y - drag.start.y;
    if (Math.hypot(dx, dy) * zoom > 3) drag.moved = true;
    if (!drag.moved) return;
    const origins = new Map(drag.origins.map((node) => [node.id, node]));
    patchGraph((g) => ({ ...g, nodes: g.nodes.map((node) => {
      const origin = origins.get(node.id);
      return origin ? { ...node, x: origin.x + dx, y: origin.y + dy } : node;
    }) }));
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
    endEdit();
    if (marqueeRef.current) {
      if (e.pointerId !== marqueeRef.current.pointerId) return;
      if (e.type === "pointercancel") setSelectedNodeIds(marqueeRef.current.base);
      else updateMarquee(e.clientX, e.clientY);
      marqueeRef.current = null; setMarquee(null);
      return;
    }
    if (dragRef.current && !dragRef.current.moved && e.type !== "pointercancel") setSelectedNodeIds(dragRef.current.clickIds);
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
    startSelectionDrag(e, selectedNodeIds.includes(node.id) ? selectedNodeIds : [node.id], [node.id]);
  };

  useEffect(() => {
    const cancel = () => {
      endEdit();
      if (marqueeRef.current) setSelectedNodeIds(marqueeRef.current.base);
      marqueeRef.current = null; setMarquee(null);
      touches.current.clear(); pinch.current = null; panRef.current = null;
      dragRef.current = null; resizeRef.current = null; wireRef.current = null;
      setWireFrom(null); setDraftWire(null);
    };
    window.addEventListener("blur", cancel);
    return () => window.removeEventListener("blur", cancel);
  }, [endEdit]);

  const fitGraph = () => {
    const box = boardRef.current;
    if (!box || !graph.nodes.length) return;
    const left = Math.min(...graph.nodes.map((n) => n.x), ...groupBoxes.map(({ bounds }) => bounds!.x));
    const top = Math.min(...graph.nodes.map((n) => n.y), ...groupBoxes.map(({ bounds }) => bounds!.y - 44 / zoom));
    const right = Math.max(...graph.nodes.map((n) => n.x + nodeWidth(n, isExpanded(n.id))), ...groupBoxes.map(({ bounds }) => bounds!.x + bounds!.width));
    const bottom = Math.max(...graph.nodes.map((n) => n.y + nodeSize(n).height), ...groupBoxes.map(({ bounds }) => bounds!.y + bounds!.height));
    const board = box.getBoundingClientRect();
    const sidebar = listRef.current?.getBoundingClientRect();
    const toolbar = toolbarRef.current?.getBoundingClientRect();
    const insetX = listCollapsed ? 24 : Math.max(24, (sidebar?.right || board.left) - board.left + 24);
    const insetY = Math.max(24, (toolbar?.bottom || board.top) - board.top + 24, listCollapsed ? (sidebar?.bottom || board.top) - board.top + 24 : 0);
    const width = Math.max(80, box.clientWidth - insetX - 24);
    const height = Math.max(80, box.clientHeight - insetY - (logOpen ? logHeight + 24 : 64));
    const next = Math.min(1, Math.max(0.25, Math.min(width / (right - left), height / (bottom - top))));
    setZoom(next);
    setPan({ x: insetX + (width - (right - left) * next) / 2 - left * next, y: insetY + (height - (bottom - top) * next) / 2 - top * next });
  };

  const logCount = log?.steps?.length || (runLogHasContent(log) ? 1 : 0);

  return (
    <div className={`aw-root${listCollapsed ? " is-list-collapsed" : ""}${draft ? " has-workflow" : ""}`} onKeyDown={onGraphKeyDown}
      onFocusCapture={(event) => { if (event.target.matches("input:not(.aw-spawn-search), textarea")) beginEdit(); }}
      onBlurCapture={(event) => { if (event.target.matches("input, textarea")) endEdit(); }}>
      <WorkflowList listId={sectionId + "-list"} listRef={listRef} owners={owners} rows={rows} activeId={draft ? selectedId : ""}
        collapsed={listCollapsed} nowMs={nowMs} onToggleCollapsed={() => setListCollapsed((collapsed) => !collapsed)}
        onOpen={(id) => void loadOne(id)} onCreate={createNew}
        onImportLocal={() => void getApi()?.import_local_workflows?.().then(() => refreshList())} />
      <div className="aw-main">
        {draft ? (
          <div className="aw-toolbar" ref={toolbarRef} role="toolbar" aria-label="Workflow actions">
              <div className="aw-toolbar-fields">
              <span className={`aw-owner-chip aw-owner-chip--${draft.owner?.kind || "local"}`} title={ownerHelp(draft.owner)}>
                <OwnerIcon owner={draft.owner} /><span>{draft.owner?.kind === "team" ? `TEAM · ${draft.owner.label}` : "LOCAL"}</span>
                {readOnly ? <Icons.Lock /> : null}
              </span>
              <input
                className="aw-name"
                aria-label="Workflow name"
                value={draft.name}
                readOnly={readOnly}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                onBlur={saveDraft}
              />

              </div>
              <div className="aw-toolbar-actions">
              <button type="button" aria-label="Undo" title="Undo (Ctrl+Z)" disabled={readOnly || history.index <= 0} onClick={() => goToEdit(history.index - 1)}><Icons.Undo /></button>
              <button type="button" aria-label="Redo" title="Redo (Ctrl+Y)" disabled={readOnly || history.index >= history.entries.length - 1} onClick={() => goToEdit(history.index + 1)}><Icons.Redo /></button>
              <ChoiceDropdown aria-label="History" trigger={<Icons.Clock />} hideChevron minWidth={300}
                value={"edit:" + history.index} onOpen={() => void loadVersions()}
                header={<strong>History</strong>} footer={<small>{historyStatus || "Choose an edit to revisit it, or restore a saved version."}</small>}
                options={[
                  ...history.entries.map((entry, index) => ({ value: "edit:" + index, label: entry.label, hint: index === history.index ? "Current edit" : "Edit " + index, group: "This session" })).reverse(),
                  ...versions.map((version, index) => ({ value: "version:" + version.id, label: "Version " + (versions.length - index) + " · " + version.name + (version.note ? " · " + version.note : ""), hint: new Date(version.saved_at * 1000).toLocaleString() + " · " + version.node_count + " nodes", group: "Saved versions" })),
                ]}
                onChange={(value) => { if (value.startsWith("edit:")) goToEdit(Number(value.slice(5))); else void restoreVersion(value.slice(8)); }} />
              <button type="button" aria-label="Enabled" title={draft.enabled ? "Disable workflow" : "Enable workflow"} aria-pressed={draft.enabled} disabled={readOnly} onClick={() => { const next = { ...draft, enabled: !draft.enabled }; setDraft(next); void persist(next); }}>{draft.enabled ? <Icons.Check /> : <Icons.Pause />}</button>
              {draft.owner?.kind === "team" && ["start.cron", ...catalog.filter((n) => n.role === "starter" && n.plugin_id).map((n) => n.type)].some((type) => draft.graph.nodes.some((node) => node.type === type)) ? (
                <button type="button" aria-label="Run on this PC" aria-pressed={!!draft.run_here}
                  title={draft.run_here ? "This PC runs its schedule and triggers. Click to stop." : "Its schedule and triggers run on other members' PCs only. Click to run them here too."}
                  onClick={async () => { const res = await getApi()?.set_workflow_run_here?.(draft.id, !draft.run_here); if (res?.workflow) { acknowledgeDraft((current) => current && current.id === draft.id ? { ...current, run_here: !!res.workflow?.run_here } : current); await refreshList(); } }}>
                  <Icons.Monitor />
                </button>
              ) : null}
              <ChoiceDropdown aria-label="Move or copy" trigger={<Icons.Share />} hideChevron minWidth={240} value=""
                header={<strong>Move or copy</strong>} footer={<small>Moving keeps its history on this PC. A copy gets a new id.</small>}
                options={(owners.owners || [LOCAL_OWNER]).filter((owner) => owner.id !== (draft.owner?.id || LOCAL_OWNER.id) && !owner.readOnly).flatMap((owner) => [
                  { value: "copy:" + owner.id, label: "Copy to " + ownerName(owner), group: ownerName(owner) },
                  { value: "move:" + owner.id, label: "Move to " + ownerName(owner), group: ownerName(owner), disabled: readOnly },
                ])}
                emptyLabel="Nowhere else to put it"
                onChange={(value) => void sendTo(value)} />
              <button type="button" title="Save" aria-label="Save" disabled={readOnly} onClick={saveDraft}><Icons.Save /></button>
              <button type="button" title={busy ? "Running…" : "Test"} aria-label={busy ? "Running…" : "Test"} onClick={() => void runTest()} disabled={busy || !draft.id}>{busy ? <span className="aw-spin"><Icons.Spinner /></span> : <Icons.Play />}</button>
              <button
                type="button" title="Duplicate" aria-label="Duplicate"
                onClick={async () => {
                  if (!draft.id) return;
                  const copy = {
                    ...draft,
                    id: "",
                    name: `${draft.name} copy`,
                    owner: undefined,
                  };
                  // Next to the original, or in Local when this one is read-only here.
                  await persist(copy, readOnly ? LOCAL_OWNER.id : draft.owner?.id || LOCAL_OWNER.id).catch((error: Error) => setActionError(error.message));
                }}
              >
                <Icons.Copy />
              </button>
              <button
                type="button" title="Delete" aria-label="Delete" disabled={readOnly}
                onClick={async () => {
                  if (!draft.id) return;
                  if (draft.owner?.kind === "team") {
                    const ok = await confirm({ title: `Delete for everyone in ${draft.owner.label}?`, message: "Every member loses this workflow.", confirmLabel: "Delete" });
                    if (ok !== true) return;
                  }
                  const gen = ++loadGen.current;
                  const res = await getApi()?.delete_workflow?.(draft.id);
                  if (res?.ok === false) { setActionError(res.error || "Could not delete workflow"); return; }
                  if (gen === loadGen.current) { setDraft(null); setSelectedId(""); }
                  await refreshList();
                }}
              >
                <Icons.Trash />
              </button>
              </div>
          </div>
        ) : null}
        <div
          ref={boardRef}
          tabIndex={-1}
          aria-label="Workflow canvas"
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
            {groupBoxes.map(({ group, bounds }) => bounds ? (
              <div key={group.id} data-aw-group={group.id} className={`aw-group${group.node_ids.every((id) => selectedNodeIds.includes(id)) ? " is-selected" : ""}`}
                style={{ left: bounds.x, top: bounds.y, width: bounds.width, height: bounds.height }}
                role="button" tabIndex={0} aria-label={`Select group ${group.name}`}
                onPointerDown={(event) => {
                  if (event.button !== 0 || (event.target instanceof Element && event.target.closest(".aw-inline-edit"))) return;
                  if (event.ctrlKey || event.metaKey) {
                    event.preventDefault(); event.stopPropagation(); boardRef.current?.focus({ preventScroll: true });
                    setSelectedEdge(null);
                    setSelectedNodeIds((current) => group.node_ids.every((id) => current.includes(id)) ? current.filter((id) => !group.node_ids.includes(id)) : [...new Set([...current, ...group.node_ids])]);
                  } else startSelectionDrag(event, group.node_ids);
                }}
                onKeyDown={(event) => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); setSelectedNodeIds(group.node_ids); setSelectedEdge(null); } }}
              >
                <div className="aw-group-title" style={{ transform: `scale(${1 / zoom})` }}>
                  <InlineNodeText value={group.name} label="Group name" onCommit={(name) => saveGraphChange((current) => ({ ...current, groups: current.groups?.map((item) => item.id === group.id ? { ...item, name } : item) }))} />
                </div>
              </div>
            ) : null)}
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
                    className={`aw-wire aw-wire--${e.kind}${selectedEdge === i || selectedNodeIds.includes(e.source) || selectedNodeIds.includes(e.target) ? " is-hot" : ""}`}
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
                  onPointerDownCapture={(event) => toggleNodeSelection(event, node.id)}
                  onClickCapture={(event) => { if ((event.ctrlKey || event.metaKey) && !(event.target instanceof Element && event.target.closest("input, textarea, select"))) { event.preventDefault(); event.stopPropagation(); } }}
                  className={`aw-node aw-node--${role}${selectedNodeIds.includes(node.id) ? " is-selected" : ""}${wireFrom === node.id ? " is-wiring" : ""}${expanded ? " is-expanded" : ""}`}
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
                        setSelectedNodeIds([node.id]);
                        setExpandedId(expanded ? "" : node.id);
                      }}
                    >
                      {expanded ? <Icons.ChevronDown /> : <Icons.Sliders />}
                    </button> : null}
                    <button type="button" className="aw-node-delete" title="Delete node" aria-label={"Delete " + label} onPointerDown={(event) => event.stopPropagation()} onClick={() => deleteNode(node.id)}><Icons.Trash /></button>
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
                      beginEdit();
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
            {marquee ? <div className="aw-selection-box" aria-hidden="true" style={{ left: marquee.x, top: marquee.y, width: marquee.width, height: marquee.height }} /> : null}
          </div>
        </div>
        {textSaveError ? <p className="aw-text-save-error" role="alert">Could not save changes. Use Save to retry.</p> : null}
        {actionError ? <p className="aw-text-save-error" role="alert">{actionError}</p> : null}
        {draft && readOnly ? <p className="aw-readonly-note" role="note"><Icons.Lock /> {draft.owner?.reason || "Read-only here."} Duplicate it to change a Local copy.</p> : null}
        <div className="aw-canvas-controls">
          <button type="button" title="Add nodes" aria-label="Add nodes" onClick={() => { const box = boardRef.current?.getBoundingClientRect(); if (!box) return; const world = worldFromClient(box.left + box.width / 2, box.top + box.height / 2); setSpawn({ x: Math.max(8, Math.min(box.left + 12, window.innerWidth - 328)), y: Math.max(8, Math.min(box.top + 12, window.innerHeight - 520)), worldX: world.x, worldY: world.y }); setSpawnFilter(""); }} disabled={!draft}><Icons.Plus /></button>
          <button type="button" title="Zoom out" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.25, z / 1.2))}><Icons.ZoomOut /></button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(4, z * 1.2))}><Icons.ZoomIn /></button>
          <button type="button" title="Fit graph" aria-label="Fit graph" onClick={fitGraph}><Icons.FitView /></button>
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
              <button type="button" className="icon-btn" title="Hide" aria-label="Hide run log" onClick={() => setLogOpen(false)}>
                <Icons.Close />
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
                  Test a workflow to see steps here. Return to user sends results back to your chat. Schedules only fire while the panel is running.
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
              <button type="button" title="Collapse all nodes" aria-label="Collapse all nodes" onClick={() => setExpandedId("")}><Icons.CollapseAll /></button>
              <button type="button" title="Arrange nodes" aria-label="Arrange nodes" onClick={() => { patchGraph((g) => arrangeGraph(g, overview ? "" : expandedId)); setSpawn(null); }}><Icons.Arrange /></button>
              <button type="button" title="Fit graph" aria-label="Fit graph" onClick={() => { fitGraph(); setSpawn(null); }}><Icons.FitView /></button>
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
                    <summary><span className="aw-accordion-chevron" aria-hidden="true"><Icons.ChevronDown /></span><NodeIcon meta={tiles[0]} /><span>{name}</span><small>{tiles.length}</small></summary>
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
        currentGraph={draft?.graph || null}
        ownerLabel={ownerName((owners.owners || []).find((owner) => owner.id === pickerOwner) || LOCAL_OWNER)}
      />
    </div>
  );
}
