/**
 * The composer's notice when a chat cannot answer yet, said for people who don't know
 * what an LLM gateway is, with the button that fixes it right there:
 *  - no AI connected at all: Set up an AI, or Connect <each installed gateway>;
 *  - AI connected but this chat has no model: Pick a model (opens the picker), and a
 *    Default Model so new chats start ready;
 *  - the chat's model is on a gateway that isn't connected: Connect it, or pick another.
 */
import type { PluginLlmProvider } from "../hooks/usePluginContributions";
import { openDefaultModelSettings, openLlmsProviderSettings } from "../navigation/openSettingsTab";
import { openGatewaySetup } from "./GatewaySetupNotice";

export type ModelSetupState =
  | { kind: "no_ai"; gateways: PluginLlmProvider[] }
  | { kind: "pick"; held: number; why: string }
  | { kind: "not_connected"; provider: string; label: string };

function Action({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className="rich-md-link model-setup-notice-action" onClick={onClick}>
      {label}
    </button>
  );
}

export function ModelSetupNotice({ state, onPickModel }: { state: ModelSetupState; onPickModel: () => void }) {
  if (state.kind === "no_ai") {
    const gateways = state.gateways.filter((g) => g.chat !== false);
    return (
      <div className="composer-attach-warning model-setup-notice" role="status">
        <strong>Ducky needs an AI to answer.</strong>{" "}
        {gateways.length === 0 ? (
          <>
            It takes a minute: Ducky installs one and helps you sign in.{" "}
            <Action label="Set up an AI" onClick={() => openGatewaySetup() || openLlmsProviderSettings()} />
          </>
        ) : (
          <>
            Sign in or add a key for one of yours:{" "}
            {gateways.map((g) => (
              <Action key={g.id} label={`Connect ${g.label}`} onClick={() => openLlmsProviderSettings(g.id)} />
            ))}
          </>
        )}
      </div>
    );
  }
  if (state.kind === "not_connected") {
    return (
      <div className="composer-attach-warning model-setup-notice" role="status">
        <strong>{state.label} isn't connected yet,</strong> so this chat's model can't answer.{" "}
        <Action label={`Connect ${state.label}`} onClick={() => openLlmsProviderSettings(state.provider)} />
        <Action label="Pick another model" onClick={onPickModel} />
      </div>
    );
  }
  const waiting =
    state.held > 0
      ? `${state.held === 1 ? "A message is" : `${state.held} messages are`} waiting and ${state.held === 1 ? "runs" : "run"} once you pick a model.`
      : state.why || "This chat has no model yet.";
  return (
    <div className="composer-attach-warning model-setup-notice" role="status">
      <span>{waiting}</span> Choose an AI service, then one of its models.{" "}
      <Action label="Pick a model" onClick={onPickModel} />
      <Action label="Set a default for new chats" onClick={openDefaultModelSettings} />
    </div>
  );
}
