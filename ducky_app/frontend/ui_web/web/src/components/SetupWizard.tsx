/**
 * First-run setup: Welcome, the starter plugins (one Install, each row with its Store icon
 * and progress), then connecting an AI (an API key, or a coding agent you already pay for).
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { getApi } from "../hooks/usePanelApi";
import { usePluginContributions, type PluginLlmProvider } from "../hooks/usePluginContributions";
import { installPanelPushBus, subscribePanelPush } from "../hooks/usePanelPushBus";
import { peekStoreCatalogCache, rememberStoreCatalog } from "../hooks/storeCatalogCache";
import { refreshModelsCatalog } from "../hooks/modelsCatalogCache";
import { Icons } from "../icons/Icons";
import type { CodingAgentDto, DuckyOSStoreItemDto, StarterPluginDto } from "../types/panel";
import { CodingAgentLoginModal } from "../views/settings/CodingAgentsSection";

export type SetupStep = "welcome" | "plugins" | "ai";
export type InstallPhase = "ready" | "installing" | "installed" | "error";
export type InstallRow = { phase: InstallPhase; detail?: string };

const STEPS: Array<{ id: SetupStep; label: string }> = [
  { id: "welcome", label: "Welcome" },
  { id: "plugins", label: "Plugins" },
  { id: "ai", label: "Connect AI" },
];

export interface SetupWizardProps {
  step: SetupStep;
  onStep: (step: SetupStep) => void;
  plugins: StarterPluginDto[];
  rows: Record<string, InstallRow>;
  installing: boolean;
  installError: string;
  onInstall: () => void;
  onClose: (reason: "skip" | "finish") => void;
  /** Walk through a provider's Settings page with its plugin's tour (the setup steps aside). */
  onShowMe: (provider: PluginLlmProvider) => void;
}

/** Store name, description and icon per slug: the cached catalog first, then a fresh read. */
function useStoreItems(): Record<string, DuckyOSStoreItemDto> {
  const index = (items: DuckyOSStoreItemDto[] | undefined) =>
    Object.fromEntries((items || []).filter((i) => i.slug).map((i) => [String(i.slug).toLowerCase(), i]));
  const [items, setItems] = useState(() => index(peekStoreCatalogCache()?.items));
  useEffect(() => {
    let alive = true;
    const api = getApi();
    if (typeof api?.duckyos_store_catalog !== "function") return;
    void Promise.resolve(api.duckyos_store_catalog())
      .then((next) => {
        if (!alive || !next || next.ok === false || !next.items?.length) return;
        rememberStoreCatalog(next);
        setItems(index(next.items));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  return items;
}

function firstSentence(text: string | undefined): string {
  const t = (text || "").trim();
  const m = /^(.+?[.!?])(\s|$)/.exec(t);
  return m ? m[1] : t;
}

function StepDots({ step }: { step: SetupStep }) {
  const at = STEPS.findIndex((s) => s.id === step);
  return (
    <ol className="setup-wizard-steps" aria-label="Setup steps">
      {STEPS.map((s, i) => (
        <li
          key={s.id}
          className={`setup-wizard-step${i < at ? " is-done" : ""}${i === at ? " is-current" : ""}`}
          aria-current={i === at ? "step" : undefined}
        >
          <span className="setup-wizard-step-num" aria-hidden>
            {i < at ? <Icons.Check /> : i + 1}
          </span>
          <span className="setup-wizard-step-label">{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

function Feature({ icon, tone, title, body }: { icon: ReactNode; tone: string; title: string; body: string }) {
  return (
    <li className="setup-wizard-feature">
      <span className={`setup-wizard-chip is-${tone}`} aria-hidden>
        {icon}
      </span>
      <span>
        <strong>{title}</strong>
        <span className="setup-wizard-muted">{body}</span>
      </span>
    </li>
  );
}

function WelcomeStep() {
  return (
    <>
      <div className="setup-wizard-hero">
        <img className="setup-wizard-logo" src="./OnlineMCPIcon.png" alt="" draggable={false} />
        <h2 id="setup-wizard-title">Welcome to UEFN Ducky</h2>
        <p className="setup-wizard-lead">
          Your AI crew for Fortnite islands. Duckies chat with you, write Verse, build levels, make materials and
          VFX, and work the UEFN editor for you.
        </p>
      </div>
      <ul className="setup-wizard-features">
        <Feature
          icon={<Icons.Duck />}
          tone="amber"
          title="Duckies"
          body="AI helpers you chat with. Each one knows your island and can use UEFN's tools."
        />
        <Feature
          icon={<Icons.Puzzle />}
          tone="purple"
          title="Plugins"
          body="Verse, level design, materials, VFX, animation and more, from the UEFN Ducky Store."
        />
        <Feature
          icon={<Icons.Brain />}
          tone="blue"
          title="Your AI, your choice"
          body="Connect OpenAI, Anthropic or Cursor with an API key, or with a plan you already pay for."
        />
      </ul>
      <p className="setup-wizard-note">Two quick steps: install the starter plugins, then connect an AI.</p>
      <p className="setup-wizard-note setup-wizard-privacy">
        Ducky sends anonymous usage counts (which features, which errors by code, how long it was open) under a
        random install id. Never your chats, files or project names. One switch in Settings → Permissions turns it off.
      </p>
    </>
  );
}

function StatusChip({ row }: { row: InstallRow | undefined }) {
  const phase = row?.phase ?? "ready";
  if (phase === "installing") {
    return (
      <span className="setup-wizard-status is-installing">
        <Icons.Spinner /> Installing
      </span>
    );
  }
  if (phase === "installed") {
    return (
      <span className="setup-wizard-status is-installed">
        <Icons.Check /> Installed
      </span>
    );
  }
  if (phase === "error") {
    return (
      <span className="setup-wizard-status is-error" title={row?.detail}>
        <Icons.AlertTriangle /> Failed
      </span>
    );
  }
  return <span className="setup-wizard-status">Ready</span>;
}

function PluginRow({
  plugin,
  row,
  item,
}: {
  plugin: StarterPluginDto;
  row: InstallRow | undefined;
  item: DuckyOSStoreItemDto | undefined;
}) {
  const icon = item?.icon_data_url;
  const desc = firstSentence(item?.description);
  return (
    <li className={`setup-wizard-plugin is-${row?.phase ?? "ready"}`}>
      <span className="setup-wizard-plugin-icon" aria-hidden>
        {icon ? (
          <img src={icon} alt="" draggable={false} />
        ) : plugin.group === "gateway" ? (
          <Icons.Brain />
        ) : plugin.group === "voice" ? (
          <Icons.Speaker />
        ) : (
          <Icons.Puzzle />
        )}
      </span>
      <span className="setup-wizard-plugin-text">
        <span className="setup-wizard-plugin-name">{item?.name || plugin.label}</span>
        {desc ? (
          <span className="setup-wizard-plugin-desc" title={desc}>
            {desc}
          </span>
        ) : null}
        {row?.phase === "error" && row.detail ? <span className="setup-wizard-plugin-error">{row.detail}</span> : null}
      </span>
      <StatusChip row={row} />
    </li>
  );
}

function PluginsStep({
  plugins,
  rows,
  installing,
  installError,
}: Pick<SetupWizardProps, "plugins" | "rows" | "installing" | "installError">) {
  const items = useStoreItems();
  const gateways = plugins.filter((p) => p.group === "gateway");
  const editor = plugins.filter((p) => p.group === "editor");
  const voices = plugins.filter((p) => p.group === "voice");
  const done = plugins.filter((p) => rows[p.slug]?.phase === "installed").length;
  return (
    <>
      <h2 id="setup-wizard-title">Install the starter plugins</h2>
      <p className="setup-wizard-lead">
        Ducky's features come as plugins. These are the ones most people start with, and they install from the
        UEFN Ducky Store in one go.
      </p>
      <div className="setup-wizard-progress">
        <progress
          className={`setup-wizard-progress-bar${installing ? " is-active" : ""}`}
          value={done}
          max={Math.max(plugins.length, 1)}
          aria-label="Plugins installed"
        />
        <span className="setup-wizard-progress-text">
          {done} of {plugins.length} installed
        </span>
      </div>
      {installError ? <p className="setup-wizard-error">{installError}</p> : null}
      <section className="setup-wizard-group" aria-label="AI gateways">
        <h3>
          AI gateways <span className="setup-wizard-muted">connect Ducky to AI models</span>
        </h3>
        <ul className="setup-wizard-plugin-list">
          {gateways.map((p) => (
            <PluginRow key={p.slug} plugin={p} row={rows[p.slug]} item={items[p.slug]} />
          ))}
        </ul>
      </section>
      <section className="setup-wizard-group" aria-label="UEFN editor tools">
        <h3>
          UEFN editor tools <span className="setup-wizard-muted">what duckies can do in your island</span>
        </h3>
        <ul className="setup-wizard-plugin-list is-grid">
          {editor.map((p) => (
            <PluginRow key={p.slug} plugin={p} row={rows[p.slug]} item={items[p.slug]} />
          ))}
        </ul>
      </section>
      {voices.length ? (
        <section className="setup-wizard-group" aria-label="Voices">
          <h3>
            Voices <span className="setup-wizard-muted">each ducky reads its replies aloud, offline</span>
          </h3>
          <ul className="setup-wizard-plugin-list">
            {voices.map((p) => (
              <PluginRow key={p.slug} plugin={p} row={rows[p.slug]} item={items[p.slug]} />
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

type KeyState = { text: string; ok: boolean; pending?: boolean };

export type AgentConnection = "logged_in" | "ready" | "logged_out" | "missing";

/** Where a coding agent stands on this PC, as Settings → LLMs → Coding agent shows it. */
export function agentConnection(agent: CodingAgentDto): AgentConnection {
  if (!agent.available) return "missing";
  if (agent.logged_in === true) return "logged_in";
  if (agent.logged_in === false) return "logged_out";
  return "ready"; // installed, and it has no account to sign in to
}

const AGENT_STATE_LABEL: Record<AgentConnection, string> = {
  logged_in: "Logged in",
  ready: "Ready",
  logged_out: "Not logged in",
  missing: "Not installed",
};

function isConnectedAgent(agent: CodingAgentDto): boolean {
  const state = agentConnection(agent);
  return state === "logged_in" || state === "ready";
}

/** A coding agent row: its state, Log in (the gateway's own CLI login) and Check (detect again). */
function AgentRow({ agent, onChanged }: { agent: CodingAgentDto; onChanged: () => void }) {
  const [loginOpen, setLoginOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [note, setNote] = useState("");
  const state = agentConnection(agent);
  const ok = isConnectedAgent(agent);

  const check = async () => {
    const api = getApi();
    if (!api?.detect_coding_agent_cli) return;
    setChecking(true);
    setNote("");
    try {
      const res = await api.detect_coding_agent_cli(agent.id);
      if (res && res.ok === false) setNote(String(res.error || res.status || "Check failed"));
      onChanged();
      void refreshModelsCatalog();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Check failed");
    } finally {
      setChecking(false);
    }
  };

  const help = (agent.install_help || "").trim();
  return (
    <li className={`setup-wizard-agent is-${state}`}>
      <span className="setup-wizard-agent-head">
        <span className="setup-wizard-agent-icon" aria-hidden>
          <Icons.Terminal />
        </span>
        <span className="setup-wizard-agent-name">{agent.label}</span>
        <span className={`setup-wizard-pill${ok ? " is-ok" : ""}`} aria-label={`${agent.label}: ${AGENT_STATE_LABEL[state]}`}>
          {ok ? <Icons.Check /> : null} {AGENT_STATE_LABEL[state]}
        </span>
        {agent.can_login && state === "logged_out" ? (
          <button type="button" className="setup-wizard-btn" onClick={() => setLoginOpen(true)}>
            Log in
          </button>
        ) : null}
        {state === "logged_out" || state === "missing" ? (
          <button
            type="button"
            className="setup-wizard-btn is-ghost"
            disabled={checking}
            title="Look again: after you installed it or signed in somewhere else"
            onClick={() => void check()}
          >
            {checking ? "Checking…" : "Check"}
          </button>
        ) : null}
      </span>
      {state === "missing" && help ? <span className="setup-wizard-agent-note">{help}</span> : null}
      {state === "logged_out" && !agent.can_login ? (
        <span className="setup-wizard-agent-note">Sign in with {agent.label} itself, then press Check.</span>
      ) : null}
      {note ? <span className="setup-wizard-agent-note is-error">{note}</span> : null}
      {loginOpen ? (
        <CodingAgentLoginModal
          agentId={agent.id}
          title={`Log in to ${agent.label}`}
          zIndex={2147483300}
          onClose={() => {
            void getApi()?.coding_agent_login_cancel?.(agent.id);
            setLoginOpen(false);
          }}
          onLoggedIn={() => {
            setLoginOpen(false);
            onChanged();
            void refreshModelsCatalog();
          }}
        />
      ) : null}
    </li>
  );
}

function ProviderCard({
  provider,
  agents,
  saved,
  onSaved,
  onShowMe,
}: {
  provider: PluginLlmProvider;
  agents: CodingAgentDto[];
  saved: boolean;
  onSaved: () => void;
  onShowMe: (provider: PluginLlmProvider) => void;
}) {
  const [draft, setDraft] = useState("");
  const [state, setState] = useState<KeyState | null>(null);
  const secretKey = provider.secret_key || provider.id;
  const connected = saved || agents.some(isConnectedAgent);

  const testAndSave = async () => {
    const value = draft.trim();
    if (!value) return;
    setState({ text: "Testing the key…", ok: true, pending: true });
    try {
      const { runBridgeJob } = await import("../hooks/bridgeJobAsync");
      const res = await runBridgeJob<{ ok: boolean; detail?: string; error?: string }>(
        "test_key",
        [secretKey, value],
        300_000,
      );
      if (!res.ok) {
        setState({ text: res.detail || res.error || "That key didn't work.", ok: false });
        return;
      }
      await getApi()?.save_agent_settings({ keys: { [secretKey]: value } });
      setDraft("");
      setState({ text: "Key saved. Duckies can use it now.", ok: true });
      onSaved();
    } catch (err) {
      setState({ text: err instanceof Error ? err.message : "Test failed", ok: false });
    }
  };

  return (
    <li className={`setup-wizard-provider${connected ? " is-connected" : ""}`}>
      <div className="setup-wizard-provider-head">
        <span className="setup-wizard-provider-logo" aria-hidden>
          {provider.icon_data_url ? <img src={provider.icon_data_url} alt="" draggable={false} /> : <Icons.Brain />}
        </span>
        <span className="setup-wizard-provider-name">{provider.label}</span>
        <span
          className={`setup-wizard-pill${connected ? " is-ok" : ""}`}
          aria-label={`${provider.label}: ${connected ? "Connected" : "Not connected"}`}
        >
          {connected ? (
            <>
              <Icons.Check /> Connected
            </>
          ) : (
            "Not connected"
          )}
        </span>
      </div>
      {provider.kind === "secret" ? (
        <div className="setup-wizard-key-label">
          <span>API key</span>
          <span className={`setup-wizard-pill${saved ? " is-ok" : ""}`} aria-label={`${provider.label} API key: ${saved ? "Key saved" : "No key"}`}>
            {saved ? <Icons.Check /> : null} {saved ? "Key saved" : "No key"}
          </span>
        </div>
      ) : null}
      {provider.kind === "secret" ? (
        <div className="setup-wizard-key-row">
          <input
            type="password"
            className="setup-wizard-input"
            placeholder={saved ? "A key is saved. Paste a new one to replace it" : `Paste your ${provider.label} API key`}
            aria-label={`${provider.label} API key`}
            autoComplete="off"
            spellCheck={false}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void testAndSave();
            }}
          />
          <button
            type="button"
            className="setup-wizard-btn"
            disabled={!draft.trim() || !!state?.pending}
            onClick={() => void testAndSave()}
          >
            {state?.pending ? "Testing…" : "Test & save"}
          </button>
        </div>
      ) : null}
      {state ? <p className={`setup-wizard-key-status${state.ok ? "" : " is-error"}`}>{state.text}</p> : null}
      {agents.length ? (
        <ul className="setup-wizard-agents" aria-label={`${provider.label} coding agents`}>
          {agents.map((a) => (
            <AgentRow key={a.id} agent={a} onChanged={onSaved} />
          ))}
        </ul>
      ) : null}
      <div className="setup-wizard-provider-foot">
        <span className="setup-wizard-muted">
          {agents.length && provider.kind === "secret" ? "A key or a logged-in coding agent is enough." : ""}
        </span>
        <button type="button" className="setup-wizard-link" onClick={() => onShowMe(provider)}>
          Show me how
        </button>
      </div>
    </li>
  );
}

/** Coding agents by the gateway plugin that registered them (Ducky's own agent left out). */
export function agentsByPlugin(agents: CodingAgentDto[]): Map<string, CodingAgentDto[]> {
  const out = new Map<string, CodingAgentDto[]>();
  for (const a of agents) {
    const pid = (a.plugin_id || "").trim().toLowerCase();
    if (!pid || a.id === "ducky") continue;
    out.set(pid, [...(out.get(pid) || []), a]);
  }
  return out;
}

function AiStep({ onShowMe, onInstallStep }: { onShowMe: SetupWizardProps["onShowMe"]; onInstallStep: () => void }) {
  const contrib = usePluginContributions();
  const [keySaved, setKeySaved] = useState<Record<string, boolean>>({});
  const [agents, setAgents] = useState<CodingAgentDto[]>([]);

  const refresh = useCallback(() => {
    const api = getApi();
    if (!api) return;
    void Promise.resolve(api.get_key_status())
      .then((s) => setKeySaved(s || {}))
      .catch(() => undefined);
    void Promise.resolve(api.list_coding_agents())
      .then((r) => setAgents(r?.agents || []))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    installPanelPushBus();
    return subscribePanelPush((event) => {
      if (event.type === "coding_agents_updated" || event.type === "uefn_plugins_changed") refresh();
    });
  }, [refresh]);

  const providers = useMemo(
    () =>
      contrib.llm_providers
        .filter((p) => p.chat !== false)
        .slice()
        .sort((a, b) => (a.order ?? 100) - (b.order ?? 100)),
    [contrib.llm_providers],
  );
  const byPlugin = useMemo(() => agentsByPlugin(agents), [agents]);
  // Agents from a gateway that adds no provider row of its own still get a row.
  const shown = new Set(providers.map((p) => p.plugin_id.toLowerCase()));
  const otherAgents = [...byPlugin.entries()].filter(([pid]) => !shown.has(pid)).flatMap(([, list]) => list);

  return (
    <>
      <h2 id="setup-wizard-title">Connect your AI</h2>
      <p className="setup-wizard-lead">
        Duckies think with AI models. Connect at least one provider. There are two ways to do it:
      </p>
      <div className="setup-wizard-ways">
        <div className="setup-wizard-way">
          <span className="setup-wizard-chip is-amber" aria-hidden>
            <Icons.Key />
          </span>
          <span>
            <strong>API key</strong>
            <span className="setup-wizard-muted">
              Paste a key from the provider's website. What you use is billed to your account with that provider.
            </span>
          </span>
        </div>
        <div className="setup-wizard-way">
          <span className="setup-wizard-chip is-blue" aria-hidden>
            <Icons.Terminal />
          </span>
          <span>
            <strong>Coding agent</strong>
            <span className="setup-wizard-muted">
              Sign in to Claude Code, Codex or Cursor and use the plan you already have. No key needed.
            </span>
          </span>
        </div>
      </div>
      {providers.length || otherAgents.length ? (
        <ul className="setup-wizard-providers">
          {providers.map((p) => (
            <ProviderCard
              key={p.id}
              provider={p}
              agents={byPlugin.get(p.plugin_id.toLowerCase()) || []}
              saved={!!keySaved[p.secret_key || p.id]}
              onSaved={refresh}
              onShowMe={onShowMe}
            />
          ))}
          {otherAgents.length ? (
            <li className="setup-wizard-provider">
              <div className="setup-wizard-provider-head">
                <span className="setup-wizard-provider-logo" aria-hidden>
                  <Icons.Terminal />
                </span>
                <span className="setup-wizard-provider-name">Other coding agents</span>
              </div>
              <ul className="setup-wizard-agents" aria-label="Other coding agents">
                {otherAgents.map((a) => (
                  <AgentRow key={a.id} agent={a} onChanged={refresh} />
                ))}
              </ul>
            </li>
          ) : null}
        </ul>
      ) : (
        <div className="setup-wizard-empty">
          <p>No AI gateway is installed yet, so there is nothing to connect.</p>
          <button type="button" className="setup-wizard-link" onClick={onInstallStep}>
            Go back and install the plugins
          </button>
        </div>
      )}
      <p className="setup-wizard-note">You can change all of this later in Settings → LLMs.</p>
    </>
  );
}

export function SetupWizard(props: SetupWizardProps) {
  const { step, onStep, plugins, rows, installing, onInstall, onClose } = props;
  const missing = plugins.filter((p) => rows[p.slug]?.phase !== "installed");
  const failed = plugins.some((p) => rows[p.slug]?.phase === "error");
  const done = plugins.length - missing.length;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !installing) onClose("skip");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [installing, onClose]);

  let footer: ReactNode;
  if (step === "welcome") {
    footer = (
      <>
        <button type="button" className="setup-wizard-btn is-ghost" onClick={() => onClose("skip")}>
          Skip for now
        </button>
        <button type="button" className="setup-wizard-btn is-primary" onClick={() => onStep("plugins")}>
          Get started <Icons.ChevronRight />
        </button>
      </>
    );
  } else if (step === "plugins") {
    let primary: ReactNode;
    if (installing) {
      primary = (
        <button type="button" className="setup-wizard-btn is-primary is-busy" disabled>
          <Icons.Spinner /> Installing {Math.min(done + 1, plugins.length)} of {plugins.length}…
        </button>
      );
    } else if (missing.length === 0) {
      primary = (
        <button type="button" className="setup-wizard-btn is-primary" onClick={() => onStep("ai")}>
          Next <Icons.ChevronRight />
        </button>
      );
    } else {
      primary = (
        <button type="button" className="setup-wizard-btn is-primary" onClick={onInstall}>
          <Icons.Download /> {failed ? "Try again" : `Install ${missing.length} plugin${missing.length === 1 ? "" : "s"}`}
        </button>
      );
    }
    footer = (
      <>
        <button type="button" className="setup-wizard-btn is-ghost" disabled={installing} onClick={() => onStep("welcome")}>
          <Icons.ChevronLeft /> Back
        </button>
        <span className="setup-wizard-foot-right">
          {missing.length > 0 && !installing ? (
            <button type="button" className="setup-wizard-btn is-ghost" onClick={() => onStep("ai")}>
              Skip
            </button>
          ) : null}
          {primary}
        </span>
      </>
    );
  } else {
    footer = (
      <>
        <button type="button" className="setup-wizard-btn is-ghost" onClick={() => onStep("plugins")}>
          <Icons.ChevronLeft /> Back
        </button>
        <button type="button" className="setup-wizard-btn is-primary" onClick={() => onClose("finish")}>
          Finish <Icons.Check />
        </button>
      </>
    );
  }

  return createPortal(
    <div className="setup-wizard-backdrop no-drag">
      <section className="setup-wizard" role="dialog" aria-modal="true" aria-labelledby="setup-wizard-title">
        <header className="setup-wizard-top">
          <StepDots step={step} />
          <button
            type="button"
            className="setup-wizard-close"
            aria-label="Close setup"
            title="Close setup (it waits in the corner)"
            disabled={installing}
            onClick={() => onClose("skip")}
          >
            <Icons.Close />
          </button>
        </header>
        <div className={`setup-wizard-body is-${step}`}>
          {step === "welcome" ? <WelcomeStep /> : null}
          {step === "plugins" ? (
            <PluginsStep plugins={plugins} rows={rows} installing={installing} installError={props.installError} />
          ) : null}
          {step === "ai" ? <AiStep onShowMe={props.onShowMe} onInstallStep={() => onStep("plugins")} /> : null}
        </div>
        <footer className="setup-wizard-foot">{footer}</footer>
      </section>
    </div>,
    document.body,
  );
}
