import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ChoiceDropdown } from "../../components/ChoiceDropdown";
import { getApi } from "../../hooks/usePanelApi";
import { Icons } from "../../icons/Icons";
import type { McpServerConnectionDto } from "../../types/panel";

const TRANSPORTS = [
  { value: "http", label: "http", hint: "Streamable HTTP" },
  { value: "sse", label: "sse", hint: "Server-sent events" },
  { value: "stdio", label: "stdio", hint: "Local subprocess" },
];

type Row = {
  key: number;
  name: string;
  /** The stored row it was loaded from ("" = added here). */
  from: string;
  value: string;
  masked: string;
  secret: string;
  hasValue: boolean;
  show: boolean;
};

/** A nested MCP server's connection on its Settings page: URL (or command), the headers
 *  or env with the keys masked (type to replace one), Save, and Test connection. */
export function McpConnectionEditor({ serverId, testing, onTest, onSaved }: {
  serverId: string;
  testing: boolean;
  onTest: () => Promise<void> | void;
  onSaved?: () => void;
}) {
  const ids = useId();
  const nextKey = useRef(1);
  const [view, setView] = useState<McpServerConnectionDto | null>(null);
  const [transport, setTransport] = useState("http");
  const [url, setUrl] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = useCallback((res: McpServerConnectionDto) => {
    setView(res);
    setTransport(res.transport || "http");
    setUrl(res.url || "");
    setCommand(res.command || "");
    setArgs((res.args || []).join(" "));
    setRows((res.values || []).map((v) => ({
      key: nextKey.current++, name: v.name, from: v.name, value: "", masked: v.masked, secret: v.secret, hasValue: v.has_value, show: false,
    })));
    setDirty(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setView(null);
    setStatus(null);
    void getApi()?.get_mcp_server_connection?.(serverId).then((res) => { if (!cancelled && res) apply(res); });
    return () => { cancelled = true; };
  }, [serverId, apply]);

  if (!view) return null;
  if (!view.ok) return <p className="mcp-conn-status is-error" role="status">{view.error || "Couldn't read this server's settings."}</p>;

  const editable = !!view.editable;
  const http = transport === "http" || transport === "sse";
  const label = http ? "Headers" : "Environment";
  const change = (fn: () => void) => { fn(); setDirty(true); setStatus(null); };
  const setRow = (key: number, patch: Partial<Row>) => change(() => setRows((list) => list.map((row) => (row.key === key ? { ...row, ...patch } : row))));

  const save = async (): Promise<boolean> => {
    const api = getApi();
    if (!api?.save_mcp_server_connection) return false;
    setSaving(true);
    try {
      const res = await api.save_mcp_server_connection(serverId, transport, url, command, args.split(/\s+/).filter(Boolean),
        rows.filter((row) => row.name.trim()).map((row) => ({ name: row.name.trim(), from: row.from || undefined, value: row.value, keep: !row.value && !!row.from })));
      if (!res?.ok) {
        setStatus({ ok: false, text: res?.error || "Couldn't save." });
        return false;
      }
      apply(res);
      setStatus({ ok: true, text: "Saved." });
      onSaved?.();
      return true;
    } catch (error) {
      setStatus({ ok: false, text: error instanceof Error ? error.message : String(error) });
      return false;
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (dirty && !(await save())) return;
    setStatus(null);
    await onTest();
  };

  return (
    <section className="mcp-conn" aria-label="Connection">
      <h5 className="mcp-conn-title">Connection</h5>
      {editable ? (
        <label className="mcp-conn-field">
          <span>Transport</span>
          <ChoiceDropdown className="mcp-create-select" mode="radio" aria-label="Transport" size="compact" value={transport}
            options={TRANSPORTS} onChange={(next) => change(() => setTransport(next))} />
        </label>
      ) : null}
      {http ? (
        <label className="mcp-conn-field" htmlFor={`${ids}-url`}>
          <span>URL</span>
          <input id={`${ids}-url`} className="catalog-slide-search-input" type="url" spellCheck={false} value={url} readOnly={!editable}
            placeholder="https://host/mcp" onChange={(e) => change(() => setUrl(e.target.value))} />
        </label>
      ) : (
        <>
          <label className="mcp-conn-field" htmlFor={`${ids}-cmd`}>
            <span>Command</span>
            <input id={`${ids}-cmd`} className="catalog-slide-search-input" type="text" spellCheck={false} value={command} readOnly={!editable}
              placeholder="e.g. uvx or npx" onChange={(e) => change(() => setCommand(e.target.value))} />
          </label>
          <label className="mcp-conn-field" htmlFor={`${ids}-args`}>
            <span>Args</span>
            <input id={`${ids}-args`} className="catalog-slide-search-input" type="text" spellCheck={false} value={args} readOnly={!editable}
              placeholder="Space-separated" onChange={(e) => change(() => setArgs(e.target.value))} />
          </label>
        </>
      )}
      <div className="mcp-conn-values" role="group" aria-label={label}>
        <span className="mcp-conn-values-label">{label}</span>
        {rows.length === 0 ? <p className="mcp-conn-empty">{http ? "No headers. Add one for an API key or a bearer token." : "No environment variables."}</p> : null}
        {rows.map((row) => (
          <div key={row.key} className="mcp-conn-row">
            <input className="catalog-slide-search-input mcp-conn-name" aria-label={`${label} name`} spellCheck={false} value={row.name}
              readOnly={!editable} placeholder={http ? "Authorization" : "API_KEY"} onChange={(e) => setRow(row.key, { name: e.target.value })} />
            <input className="catalog-slide-search-input mcp-conn-value" aria-label={`${row.name || "New"} value`} spellCheck={false} autoComplete="off"
              type={row.show ? "text" : "password"} value={row.value}
              placeholder={row.hasValue ? `${row.masked} (type to replace)` : http ? "Bearer your-token" : "Value"}
              onChange={(e) => setRow(row.key, { value: e.target.value })} />
            <button type="button" className="mcp-conn-show" aria-label={row.show ? "Hide what you typed" : "Show what you typed"}
              title={row.show ? "Hide" : "Show what you typed"} disabled={!row.value} onClick={() => setRow(row.key, { show: !row.show })}>
              {row.show ? "Hide" : "Show"}
            </button>
            {editable ? (
              <button type="button" className="catalog-slide-action catalog-slide-action--danger" aria-label={`Remove ${row.name || "row"}`} title="Remove"
                onClick={() => change(() => setRows((list) => list.filter((r) => r.key !== row.key)))}>
                <Icons.Close />
              </button>
            ) : null}
            {row.secret ? <small className="mcp-conn-hint">Saved secret {row.secret}</small> : null}
          </div>
        ))}
        {editable ? (
          <button type="button" className="mcp-conn-add" onClick={() => change(() => setRows((list) => [...list, {
            key: nextKey.current++, name: http && !list.some((r) => r.name.toLowerCase() === "authorization") ? "Authorization" : "", from: "", value: "", masked: "", secret: "", hasValue: false, show: false,
          }]))}>
            <Icons.Plus /> {http ? "Add header" : "Add variable"}
          </button>
        ) : null}
        <small className="mcp-conn-hint">A key you type is kept in Ducky's saved secrets, not in the server list.</small>
      </div>
      <div className="mcp-conn-actions">
        <button type="button" className="mcp-conn-button" disabled={!dirty || saving} onClick={() => void save()}>{saving ? "Saving…" : "Save"}</button>
        <button type="button" className="mcp-conn-button is-primary" disabled={saving || testing} onClick={() => void test()}>
          {testing ? "Testing…" : dirty ? "Save and test" : "Test connection"}
        </button>
        {status ? <span className={`mcp-conn-status${status.ok ? " is-ok" : " is-error"}`} role="status">{status.text}</span> : null}
      </div>
    </section>
  );
}
