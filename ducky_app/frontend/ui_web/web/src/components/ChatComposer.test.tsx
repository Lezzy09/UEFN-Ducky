// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ChatTab } from "../types/panel";

// Every panel call answers with an empty list: enough for the composer to settle.
const api = vi.hoisted(() => new Proxy({}, {
  get: (_target, prop) => (prop === "then" ? undefined : () => Promise.resolve([])),
}));
vi.mock("../hooks/usePanelApi", () => ({ getApi: () => api, isRemote: () => false, isPanelApiReady: () => true }));
vi.mock("../remote/directTransport", () => ({ getDirectTransport: () => null }));
vi.mock("../voice/VoiceControls", () => ({ VoiceControls: () => null }));
vi.mock("../voice/VoiceOverlay", () => ({ VoiceOverlay: () => null }));
vi.mock("./ModelSelector", () => ({ ModelSelector: () => null }));

import { ChatComposer, type ChatComposerProps } from "./ChatComposer";
import { ConfirmModalProvider } from "../contexts/ConfirmModalContext";

const chat: ChatTab = { id: "composer-chat", name: "Builder" };
const noop = () => {};

function Composer({ onSend }: { onSend: (text?: string) => void }) {
  const [inputText, setInputText] = useState("hello");
  const [caret, setCaret] = useState(5);
  const textareaRef = useRef<HTMLDivElement>(null);
  const props = {
    chat, allChats: [chat], visible: true, isPopup: false, paneHost: null, textareaRef,
    inputText, setInputText, caret, setCaret, onHistoryKey: () => false,
    isDragOver: false, changesOpen: false, onToggleChanges: noop, onCloseChanges: noop,
    liveVoice: false, liveVoiceHandlers: null, onLiveVoiceChange: noop,
    agentMode: "agent", setAgentMode: noop, selectedModel: "m", setSelectedModel: noop,
    codingAgent: "ducky", setCodingAgent: noop, thinkingEffort: "off", setThinkingEffort: noop,
    modelPickerSignal: 0, onPickModel: noop, onModelMetaChange: noop,
    showDefaultModelCta: false, pickModelFirst: false, notConnected: null, llmProviders: [],
    heldForModel: 0, noModelText: "", visionBlocked: false, attachmentError: null, displayModelLabel: "m",
    slashStatus: "", availableCommands: [], runSlashCommand: noop, waitingOnAgents: [],
    attachments: [], readInParts: false, removeAttachment: noop, retryVideo: noop,
    updateAttachmentImage: noop, addFiles: noop, clearAttachments: noop,
    sessionFiles: [], contextPanelOpen: false, onToggleContextPanel: noop, onCloseContextPanel: noop,
    onContextChanged: noop, onOpenFile: noop, onOpenChat: noop, groupMemberCount: 0,
    agentRunning: false, noModelsAvailable: false, modelsUnavailable: false, streamBuffer: "",
    hasContent: true, canQueue: false, canSend: true, onSend, onStop: noop,
  } as unknown as ChatComposerProps;
  return <ChatComposer {...props} />;
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("renders the draft and sends from the Send button", () => {
  const onSend = vi.fn();
  render(<ConfirmModalProvider><Composer onSend={onSend} /></ConfirmModalProvider>);
  expect(screen.getByRole("textbox").textContent).toBe("hello");
  fireEvent.click(screen.getByTitle("Send"));
  expect(onSend).toHaveBeenCalledTimes(1);
});
