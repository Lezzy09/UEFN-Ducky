import type { OpenFileHandler } from "../../types/richContent";
import { autoFormatToolJson } from "../rich-content/autoFormatToolJson";
import { RichBlockList } from "../rich-content/RichBlockList";
import { resolveToolPresenterBlocks, resolveToolPresenterView } from "./resolveToolPresenter";

interface ToolPresenterViewProps {
  toolName: string;
  arguments: Record<string, unknown>;
  resultText: string;
  isSuccess: boolean;
  onOpenFile?: OpenFileHandler;
}

export function ToolPresenterView({
  toolName,
  arguments: args,
  resultText,
  onOpenFile,
}: ToolPresenterViewProps) {
  const View = resolveToolPresenterView(toolName, resultText);
  if (View) {
    return (
      <div className="tool-result-rich-view">
        <View toolName={toolName} arguments={args} resultText={resultText} isSuccess onOpenFile={onOpenFile} />
      </div>
    );
  }
  const custom = resolveToolPresenterBlocks({
    toolName,
    arguments: args,
    resultText,
    isSuccess: true,
    onOpenFile,
  });
  const blocks = custom ?? autoFormatToolJson(resultText);
  if (blocks.length === 0) return null;
  return (
    <div className="tool-result-rich-view">
      <RichBlockList blocks={blocks} onOpenFile={onOpenFile} />
    </div>
  );
}
