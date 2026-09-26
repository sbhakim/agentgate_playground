import { useEffect, useRef } from "react";
import type { PendingApproval } from "../types";
import { Icon, LabelChip } from "./ui";

interface Props {
  pending: PendingApproval;
  busy: boolean;
  onDecide: (approve: boolean) => void;
  onClose: () => void;
}

export function ApprovalDialog({ pending, busy, onDecide, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    return () => opener?.focus?.();
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
    if (e.key !== "Tab" || !dialogRef.current) return;
    const items = dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled])");
    if (!items.length) { e.preventDefault(); return; }
    const first = items[0], last = items[items.length - 1];
    const atDialog = document.activeElement === dialogRef.current;
    if (e.shiftKey && (atDialog || document.activeElement === first)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (atDialog || document.activeElement === last)) { e.preventDefault(); first.focus(); }
  }

  const minutes = Math.max(0, Math.round((pending.expires_at * 1000 - Date.now()) / 60000));

  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title"
        tabIndex={-1} ref={dialogRef} onKeyDown={onKeyDown}>
        <div className="dialog-head">
          <span className="dialog-icon"><Icon name="pause" size={20} /></span>
          <div>
            <h2 id="approval-title">Approve this exact send?</h2>
            <p className="small muted" style={{ margin: "2px 0 0" }}>
              The assistant cannot approve its own actions. Only this button can.
            </p>
          </div>
        </div>
        <div className="dialog-body">
          <dl style={{ margin: 0 }}>
            <div className="field"><dt>To</dt><dd>{pending.recipient} {pending.recipient_class && <span className="class-chip">{pending.recipient_class}</span>}</dd></div>
            <div className="field"><dt>Subject</dt><dd>{pending.subject}</dd></div>
            <div className="field"><dt>Data label</dt><dd><LabelChip label={pending.label} /></dd></div>
            <div className="field"><dt>Body</dt><dd className="body">{pending.body}</dd></div>
          </dl>
        </div>
        <p className="dialog-note">
          This approval is bound to this exact content, data label and policy version. It expires in about {minutes} min.
          A policy change or label change cancels it.
        </p>
        <div className="dialog-foot">
          <button className="btn" onClick={onClose} disabled={busy}>Later</button>
          <button className="btn btn-danger" onClick={() => onDecide(false)} disabled={busy}>
            <Icon name="x" size={14} />Reject
          </button>
          <button className="btn btn-allow" onClick={() => onDecide(true)} disabled={busy}>
            <Icon name="check" size={14} />Approve &amp; send (simulated)
          </button>
        </div>
      </div>
    </div>
  );
}
