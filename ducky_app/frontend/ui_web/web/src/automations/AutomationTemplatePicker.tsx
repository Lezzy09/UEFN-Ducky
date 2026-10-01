import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";

import { ChoiceDropdown } from "../components/ChoiceDropdown";
import { Modal } from "../components/Modal";
import { Icons } from "../icons/Icons";
import { useConfirmModal } from "../contexts/ConfirmModalContext";
import { getApi } from "../hooks/usePanelApi";
import { subscribePanelPush } from "../hooks/usePanelPushBus";
import { handleDeepLink } from "../navigation/deepLinks";
import type { AutomationGraphDto, AutomationTemplateDto, WorkflowOwnerDto } from "../types/panel";
import { IconPicker } from "./IconPicker";
import { WorkflowMiniature } from "./WorkflowHoverCard";
import { ownerName } from "./WorkflowList";
import { targetRef } from "../ui-targets/registry";

const BLANK_ID = "__blank__";
const ALL = "All";
/** Shelves in this order; plugin and custom categories follow. */
export const TEMPLATE_CATEGORIES = ["Images", "3D", "Characters", "Text & AI", "Documents", "Play tests", "UEFN", "Plugins", "Yours"];

export function templateCategory(template: AutomationTemplateDto): string {
  return template.category || (template.kind === "custom" ? "Yours" : template.kind === "plugin" ? "Plugins" : "UEFN");
}

function byShelf(a: string, b: string) {
  const ia = TEMPLATE_CATEGORIES.indexOf(a), ib = TEMPLATE_CATEGORIES.indexOf(b);
  return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
}

interface AutomationTemplatePickerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (template: AutomationTemplateDto | null) => void;
  currentGraph?: AutomationGraphDto | null;
  /** Where the new workflow will live ("Local", "Team · Alpha Studio"). */
  ownerLabel?: string;
  /** Local and each team. The footer lets you pick before the workflow is created. */
  owners?: WorkflowOwnerDto[];
  ownerId?: string;
  onOwnerChange?: (ownerId: string) => void;
}

const CloseIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const Check = () => (
  <span className="vtm-card-check" aria-hidden>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6L9 17l-5-5" />
    </svg>
  </span>
);

export function AutomationTemplatePicker({
  open,
  onClose,
  onSelect,
  currentGraph,
  ownerLabel = "Local",
  owners = [],
  ownerId = "",
  onOwnerChange,
}: AutomationTemplatePickerProps) {
  const { confirm } = useConfirmModal();
  const [view, setView] = useState<"picker" | "creator">("picker");
  const [templates, setTemplates] = useState<AutomationTemplateDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(BLANK_ID);
  const [searchQuery, setSearchQuery] = useState("");
  const [shelf, setShelf] = useState(ALL);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AutomationTemplateDto | null>(null);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formCategory, setFormCategory] = useState("Yours");
  const [formIcon, setFormIcon] = useState("⚡");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const refresh = useCallback(async () => {
    const api = getApi();
    if (!api?.list_workflow_templates) {
      setTemplates([]);
      return;
    }
    setLoading(true);
    try {
      const res = await api.list_workflow_templates();
      setTemplates(res?.templates || []);
    } catch {
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    return subscribePanelPush((event) => {
      if (event.type === "templates_changed") void refresh();
    });
  }, [open, refresh]);

  useEffect(() => {
    if (!open) {
      setView("picker");
      setSearchQuery("");
      setShelf(ALL);
      setEditing(null);
      setCreating(false);
      setFormError("");
      return;
    }
    void refresh();
    setSelectedId(BLANK_ID);
  }, [open, refresh]);

  const shelves = useMemo(() => [...new Set(templates.map(templateCategory))].sort(byShelf), [templates]);

  // A tour or Show me can open a shelf.
  useEffect(() => {
    if (!open) return;
    const onShelf = (event: Event) => {
      const want = String((event as CustomEvent<{ shelf?: string }>).detail?.shelf || "").toLowerCase();
      if (want) setShelf((cur) => [ALL, ...shelves].find((name) => name.toLowerCase() === want) ?? cur);
    };
    window.addEventListener("ducky:templates-shelf", onShelf);
    return () => window.removeEventListener("ducky:templates-shelf", onShelf);
  }, [open, shelves]);

  // Search matches every word across name, description, category and plugin.
  const filtered = useMemo(() => {
    const words = searchQuery.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return templates.filter((t) => {
      if (shelf !== ALL && templateCategory(t) !== shelf) return false;
      const text = `${t.name} ${t.label || ""} ${t.description || ""} ${templateCategory(t)} ${t.plugin_id || ""}`.toLowerCase();
      return words.every((word) => text.includes(word));
    });
  }, [searchQuery, shelf, templates]);

  const sections = useMemo(() => {
    const map = new Map<string, AutomationTemplateDto[]>();
    for (const t of filtered) map.set(templateCategory(t), [...(map.get(templateCategory(t)) || []), t]);
    return [...map.entries()].sort(([a], [b]) => byShelf(a, b));
  }, [filtered]);

  const selected = selectedId === BLANK_ID ? null : templates.find((t) => t.id === selectedId) || null;
  const blankMatches = shelf === ALL && (() => {
    const q = searchQuery.trim().toLowerCase();
    return !q || "blank empty workflow".includes(q);
  })();

  const locked = Boolean(selected && selected.ready === false);
  const missing = selected?.missing_plugins || [];

  const openStoreSlug = useCallback((slug: string) => {
    handleDeepLink(`uefn-ducky://store/${slug}`);
  }, []);

  const handleCreate = useCallback(() => {
    if (loading || creating) return;
    if (locked) {
      const slug = missing[0] || "";
      if (slug) openStoreSlug(slug);
      return;
    }
    setCreating(true);
    window.setTimeout(() => {
      onSelect(selectedId === BLANK_ID ? null : selected);
      onClose();
      setCreating(false);
    }, 200);
  }, [creating, loading, locked, missing, onClose, onSelect, openStoreSlug, selected, selectedId]);

  const openCreateView = useCallback((row: AutomationTemplateDto | null) => {
    setEditing(row);
    setFormName(row?.name || "");
    setFormDesc(row?.description || "");
    setFormCategory(row ? templateCategory(row) : shelf !== ALL ? shelf : "Yours");
    setFormIcon(row?.icon || "⚡");
    setFormError("");
    setView("creator");
  }, [shelf]);

  const handleDelete = useCallback(
    async (template: AutomationTemplateDto, e: MouseEvent) => {
      e.stopPropagation();
      if (
        !(await confirm({
          message: `Delete template "${template.name}"?`,
          confirmLabel: "Delete",
          danger: true,
        }))
      ) {
        return;
      }
      const ok = await getApi()?.delete_workflow_template?.(template.id);
      if (ok?.ok) {
        setTemplates((prev) => prev.filter((t) => t.id !== template.id));
        if (selectedId === template.id) setSelectedId(BLANK_ID);
      }
    },
    [confirm, selectedId],
  );

  const savedGraph = editing?.graph || currentGraph || { nodes: [], edges: [] };

  const handleSaveCustom = useCallback(async () => {
    const name = formName.trim();
    if (!name) {
      setFormError("It needs a name.");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      const res = await getApi()?.save_workflow_template?.(
        name,
        formDesc,
        formIcon || "⚡",
        JSON.stringify(savedGraph),
        editing?.kind === "custom" ? editing.id : "",
        formCategory,
      );
      if (!res?.ok || !res.template) {
        setFormError(res?.error || "Could not save");
        return;
      }
      await refresh();
      setSelectedId(res.template.id);
      setView("picker");
      setEditing(null);
    } finally {
      setSaving(false);
    }
  }, [editing, formCategory, formDesc, formIcon, formName, refresh, savedGraph]);

  const handleClose = useCallback(() => {
    setView("picker");
    setEditing(null);
    onClose();
  }, [onClose]);

  const hasOpenGraph = (currentGraph?.nodes?.length || 0) > 0;
  const categoryOptions = [...new Set([...TEMPLATE_CATEGORIES.filter((c) => c !== "Plugins"), ...shelves.filter((c) => c !== "Plugins"), formCategory])]
    .sort(byShelf).map((c) => ({ value: c, label: c }));

  const card = (template: AutomationTemplateDto) => {
    const isSelected = template.id === selectedId;
    const isLocked = template.ready === false;
    const need = template.missing_plugins || [];
    const badge = isLocked ? `Needs ${need.join(", ")}` : template.kind === "plugin" ? `Plugin (${template.plugin_id || "store"})`
      : template.kind === "custom" ? "Yours" : template.requires_plugins?.length ? `Uses ${template.requires_plugins.join(", ")}` : "Built in";
    return (
      <button
        key={template.id}
        ref={targetRef(`workflows.template.${template.id}`, { route: "workflows", label: template.name })}
        type="button"
        role="option"
        aria-selected={isSelected}
        className={`vtm-card${isSelected ? " is-selected" : ""}${isLocked ? " is-locked" : ""}`}
        title={template.description || template.name}
        onClick={() => setSelectedId(template.id)}
        onDoubleClick={() => {
          if (isLocked) {
            if (need[0]) openStoreSlug(need[0]);
            return;
          }
          onSelect(template);
          onClose();
        }}
      >
        <span className={`vtm-card-icon${isSelected ? " is-selected" : ""}`} aria-hidden>{template.icon || "⚡"}</span>
        <span className="vtm-card-body">
          <span className="vtm-card-name">{template.name}</span>
          {template.description ? <span className="vtm-card-desc">{template.description}</span> : null}
          <span className={`vtm-badge${template.kind === "plugin" ? " vtm-badge--system" : ""}${isLocked ? " vtm-badge--warn" : ""}`}>{badge}</span>
          {isLocked
            ? need.map((slug) => (
                <span key={slug} role="link" className="vtm-chip" onClick={(e) => { e.stopPropagation(); openStoreSlug(slug); }}>
                  Get {slug}
                </span>
              ))
            : null}
        </span>
        {isSelected ? <Check /> : null}
        {template.kind === "custom" ? (
          <span className="vtm-card-actions">
            <span role="button" tabIndex={0} className="vtm-card-action" aria-label={`Edit ${template.name}`} title={`Edit ${template.name}`}
              onClick={(e) => { e.stopPropagation(); openCreateView(template); }}>
              <Icons.Pencil />
            </span>
            <span role="button" tabIndex={0} className="vtm-card-action vtm-card-action--danger" aria-label={`Delete ${template.name}`} title={`Delete ${template.name}`}
              onClick={(e) => void handleDelete(template, e)}>
              <Icons.Trash />
            </span>
          </span>
        ) : null}
      </button>
    );
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={view === "creator" ? "Save Template" : "New workflow"}
      width={820}
      hideHeader
      hideClose
      className={`vtm-modal vtm-modal--workflows${view === "creator" ? " vtm-modal--compact" : ""}`}
      bodyClassName="vtm-modal-body"
    >
      <div className="vtm vtm--workflows">
        <div className={`vtm-view${view === "picker" ? " vtm-view--active" : " vtm-view--hidden"}`}>
          <div className="vtm-header">
            <div className="vtm-header-left">
              <h2 className="vtm-title">New workflow</h2>
              {owners.length > 1 && onOwnerChange ? (
                <ChoiceDropdown
                  aria-label="Save in"
                  size="compact"
                  value={ownerId}
                  minWidth={220}
                  options={owners.map((owner) => ({
                    value: owner.id,
                    label: ownerName(owner),
                    disabled: !!owner.readOnly,
                    hint: owner.readOnly ? owner.reason || "Read-only" : undefined,
                  }))}
                  onChange={onOwnerChange}
                />
              ) : (
                <small className="vtm-owner">in {ownerLabel}</small>
              )}
            </div>
            <button type="button" className="vtm-icon-btn" onClick={handleClose} aria-label="Close"><CloseIcon /></button>
          </div>
          <div className="vtm-search">
            <div className="vtm-search-wrap">
              <span className="vtm-search-icon" aria-hidden>
                <svg className="vtm-search-svg" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </span>
              <input
                type="text"
                className="vtm-input vtm-search-input"
                ref={targetRef("workflows.templates.search", { route: "workflows", label: "Search templates", kind: "input" })}
                placeholder="Search templates..."
                aria-label="Search templates"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                autoFocus={view === "picker"}
              />
            </div>
            {shelves.length > 1 ? (
              <div className="vtm-shelves" role="tablist" aria-label="Template categories">
                {[ALL, ...shelves].map((name) => {
                  const count = name === ALL ? templates.length : templates.filter((t) => templateCategory(t) === name).length;
                  return (
                    <button key={name} ref={targetRef(`workflows.templates.tab.${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`, { route: "workflows", label: name, kind: "tab" })} type="button" role="tab" aria-selected={shelf === name} className={`vtm-shelf${shelf === name ? " is-active" : ""}`} onClick={() => setShelf(name)}>
                      {name}<span className="vtm-shelf-count">{count}</span>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
          <div className="vtm-body vtm-picker-body" role="listbox" aria-label="Workflow templates">
            {loading ? <div className="vtm-status">Loading templates…</div> : null}
            {blankMatches ? (
              <div className="vtm-grid">
                <button
                  ref={targetRef("workflows.template.blank", { route: "workflows", label: "Blank workflow" })}
                  type="button"
                  role="option"
                  aria-selected={selectedId === BLANK_ID}
                  className={`vtm-card${selectedId === BLANK_ID ? " is-selected" : ""}`}
                  onClick={() => setSelectedId(BLANK_ID)}
                  onDoubleClick={() => {
                    onSelect(null);
                    onClose();
                  }}
                >
                  <span className={`vtm-card-icon${selectedId === BLANK_ID ? " is-selected" : ""}`} aria-hidden>∅</span>
                  <span className="vtm-card-body">
                    <span className="vtm-card-name">Blank workflow</span>
                    <span className="vtm-badge">Empty canvas</span>
                  </span>
                  {selectedId === BLANK_ID ? <Check /> : null}
                </button>
              </div>
            ) : null}
            {sections.map(([name, rows]) => (
              <section key={name} className="vtm-section" aria-label={name}>
                {shelf === ALL ? <h3 className="vtm-section-title">{name}<span>{rows.length}</span></h3> : null}
                <div className="vtm-grid">{rows.map(card)}</div>
              </section>
            ))}
            {!loading && filtered.length === 0 && !blankMatches ? (
              <div className="vtm-empty">
                <div className="vtm-empty-icon" aria-hidden>🔍</div>
                <p className="vtm-empty-text">No matching templates</p>
              </div>
            ) : null}
            <div className="vtm-create-custom">
              <button type="button" className="vtm-create-custom-btn" onClick={() => openCreateView(null)}>
                <span className="vtm-create-custom-icon" aria-hidden><Icons.Plus /></span>
                <span className="vtm-create-custom-body">
                  <span className="vtm-create-custom-name">Save as template</span>
                  <span className="vtm-create-custom-desc">
                    {hasOpenGraph ? "Keep the open workflow as a reusable template" : "Name a blank template you can fill in later"}
                  </span>
                </span>
              </button>
            </div>
          </div>
          <div className="vtm-footer">
            {selected?.ready === false ? <span className="vtm-footer-note">Needs {missing.join(", ")}: Get it opens the Store.</span> : null}
            <button type="button" className="vtm-btn vtm-btn--ghost" onClick={handleClose}>Cancel</button>
            <button ref={targetRef("workflows.templates.create", { route: "workflows", label: "Create workflow" })} type="button" className="vtm-btn vtm-btn--primary" disabled={loading || creating} onClick={handleCreate}>
              {creating ? (
                <>
                  <span className="vtm-spin" aria-hidden><Icons.Spinner /></span>
                  Processing...
                </>
              ) : locked ? `Get ${missing[0] || "plugin"}` : "Create workflow"}
            </button>
          </div>
        </div>

        {view === "creator" ? (
          <div className="vtm-view vtm-view--active vtm-creator">
            <div className="vtm-header">
              <div className="vtm-header-left">
                <button type="button" className="vtm-icon-btn vtm-icon-btn--back" onClick={() => { setView("picker"); setEditing(null); }} title="Back to Templates" aria-label="Back">
                  <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="15 18 9 12 15 6" />
                  </svg>
                </button>
                <h2 className="vtm-title">{editing ? "Edit template" : "Save as template"}</h2>
              </div>
              <button type="button" className="vtm-icon-btn" onClick={handleClose} aria-label="Close"><CloseIcon /></button>
            </div>
            <div className="vtm-creator-body">
              <div className="vtm-creator-preview" aria-label="What gets saved">
                {savedGraph.nodes.length ? <WorkflowMiniature graph={savedGraph} /> : <div className="aw-mini aw-mini--empty">Empty canvas</div>}
                <small>{editing ? "The graph stays as saved." : hasOpenGraph ? `The open workflow: ${savedGraph.nodes.length} node${savedGraph.nodes.length === 1 ? "" : "s"}.` : "An empty graph: build it on the canvas, then save again."}</small>
              </div>
              <div className="vtm-creator-fields">
                <div className="vtm-creator-row">
                  <IconPicker icon={formIcon} shown={<span className="vtm-creator-icon">{formIcon || "⚡"}</span>} label="Template icon" onChange={(icon) => setFormIcon(icon || "⚡")} />
                  <label className="vtm-field vtm-field--grow">
                    <span className="vtm-label">Name</span>
                    <input className={`vtm-input vtm-input--solid${formError && !formName.trim() ? " is-invalid" : ""}`} value={formName} aria-label="Template name"
                      onChange={(e) => setFormName(e.target.value)} placeholder="Prompt to character in UEFN" autoFocus
                      onKeyDown={(e) => { if (e.key === "Enter") void handleSaveCustom(); }} />
                  </label>
                </div>
                <div className="vtm-field">
                  <span className="vtm-label">Category</span>
                  <ChoiceDropdown aria-label="Category" size="compact" value={formCategory} options={categoryOptions} onChange={setFormCategory} />
                </div>
                <label className="vtm-field">
                  <span className="vtm-label">Description</span>
                  <textarea className="vtm-input vtm-input--solid vtm-textarea" rows={2} value={formDesc} aria-label="Template description"
                    onChange={(e) => setFormDesc(e.target.value)} placeholder="What it makes and what it needs" />
                </label>
                {formError ? <p className="vtm-form-error" role="alert">{formError}</p> : null}
              </div>
            </div>
            <div className="vtm-footer">
              <button type="button" className="vtm-btn vtm-btn--ghost" onClick={() => { setView("picker"); setEditing(null); }}>Back</button>
              <button type="button" className="vtm-btn vtm-btn--primary" disabled={saving} onClick={() => void handleSaveCustom()}>
                {saving ? "Saving…" : editing ? "Save changes" : "Save template"}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
