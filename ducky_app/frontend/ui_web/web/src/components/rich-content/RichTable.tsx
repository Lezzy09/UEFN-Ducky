import { useLayoutEffect, useRef, type ReactNode } from "react";
import type { OpenFileHandler } from "../../types/richContent";
import { RichInline } from "./RichInline";

interface RichTableProps {
  headers: string[];
  rows: string[][];
  onOpenFile?: OpenFileHandler;
}

/** The table box. Each cell gets its column's heading as data-label, which a narrow
 *  chat shows above the value when rows stack as cards (rich-content.css). */
export function RichTableWrap({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const wrap = ref.current;
    if (!wrap) return;
    const heads = Array.from(wrap.querySelectorAll("thead th")).map((th) => (th.textContent || "").trim());
    wrap.querySelectorAll("tbody tr").forEach((tr) => {
      Array.from(tr.children).forEach((cell, i) => {
        if (heads[i]) cell.setAttribute("data-label", heads[i]);
      });
    });
  });
  return (
    <div className="rich-table-wrap" ref={ref}>
      <table className="rich-table">{children}</table>
    </div>
  );
}

export function RichTable({ headers, rows, onOpenFile }: RichTableProps) {
  if (headers.length === 0 && rows.length === 0) return null;
  return (
    <RichTableWrap>
      {headers.length > 0 ? (
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} className="rich-table-th">
                <RichInline text={h} onOpenFile={onOpenFile} />
              </th>
            ))}
          </tr>
        </thead>
      ) : null}
      <tbody>
        {rows.map((row, ri) => (
          <tr key={`row-${ri}`}>
            {row.map((cell, ci) => (
              <td key={`cell-${ri}-${ci}`} className="rich-table-td">
                <RichInline text={cell} onOpenFile={onOpenFile} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </RichTableWrap>
  );
}
