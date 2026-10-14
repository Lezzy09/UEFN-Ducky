/**
 * Ducky's own model picker, opened by a plugin panel (bridge `ui.pickModel`).
 *
 * The panel lives in a sandboxed iframe, so it cannot render app components itself; it asks
 * the host, which shows the same ModelSelector as the chat composer in a dialog and returns
 * the qualified `backend:model` id (what `llm.complete` takes). `purpose: "video"` keeps only
 * models that can read pictures, the ones that can judge footage frames.
 */
import { useEffect, useState } from "react";

import { getCachedModels } from "../hooks/modelsCatalogCache";
import { ModelSelector } from "../components/ModelSelector";
import { Modal, ModalActions } from "../components/Modal";
import { qualifyModelPick } from "../components/ducky/DuckyModelPicker";

export type ModelPickPurpose = "video" | "chat";
export interface ModelPickResult {
  model: string;
  name: string;
}
interface PickRequest {
  purpose: ModelPickPurpose;
  current: string;
  title: string;
  resolve: (result: ModelPickResult | null) => void;
}

let openPicker: ((request: PickRequest) => void) | null = null;

export function pickModelFromHost(options: {
  purpose?: string;
  current?: string;
  title?: string;
}): Promise<ModelPickResult | null> {
  if (!openPicker) return Promise.reject(new Error("model picker is not mounted"));
  const show = openPicker;
  return new Promise((resolve) =>
    show({
      purpose: options.purpose === "video" ? "video" : "chat",
      current: String(options.current || ""),
      title: String(options.title || ""),
      resolve,
    }),
  );
}

export function PluginModelPickerHost() {
  const [request, setRequest] = useState<PickRequest | null>(null);
  const [picked, setPicked] = useState("");
  const [openSignal, setOpenSignal] = useState(0);

  useEffect(() => {
    openPicker = (next) => {
      setRequest((previous) => {
        previous?.resolve(null);
        return next;
      });
      const current = next.current.includes(":") ? next.current.slice(next.current.indexOf(":") + 1) : next.current;
      setPicked(current);
      setOpenSignal((n) => n + 1);
    };
    return () => {
      openPicker = null;
    };
  }, []);

  if (!request) return null;
  const rows = (getCachedModels() ?? []).filter((row) => request.purpose !== "video" || row.supportsVision);
  const finish = (result: ModelPickResult | null) => {
    request.resolve(result);
    setRequest(null);
  };
  const confirm = () => {
    const id = picked.trim();
    if (!id) return finish(null);
    const row = rows.find((r) => r.id === id);
    finish({ model: qualifyModelPick("ducky", id), name: row?.name || id });
  };
  const title =
    request.title || (request.purpose === "video" ? "Pick the model that plans your video" : "Pick a model");

  return (
    <Modal
      open
      onClose={() => finish(null)}
      title={title}
      width={460}
      footer={
        <ModalActions
          onCancel={() => finish(null)}
          onConfirm={confirm}
          confirmLabel="Use this model"
          confirmDisabled={!picked.trim()}
        />
      }
    >
      <p className="confirm-modal-message">
        {request.purpose === "video"
          ? rows.length
            ? "Only models that can read pictures are listed: they judge your footage frames."
            : "No model that can read pictures is set up. Add one in Settings → LLMs."
          : "The same models as the chat."}
      </p>
      <ModelSelector
        selectedModel={picked}
        setSelectedModel={setPicked}
        catalogRows={rows}
        preserveSelection
        openSignal={openSignal}
        labeled
      />
    </Modal>
  );
}
