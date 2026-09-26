import { useEffect, useState } from "react";
import type { Catalog, DecisionKind, Policy } from "../types";
import { Icon, LabelChip } from "./ui";

interface Props {
  catalog: Catalog;
  policy: Policy;
  runId: number;
  disabled: boolean;
  hasPending: boolean;
  onApply: (p: Omit<Policy, "version">) => void;
}

const RULE_WORD: Record<DecisionKind, string> = { allow: "Allow", deny: "Deny", require_approval: "Approval" };
const RULE_CLS: Record<DecisionKind, string> = { allow: "badge-allow", deny: "badge-deny", require_approval: "badge-wait" };

export function PolicyPanel({ catalog, policy, runId, disabled, hasPending, onApply }: Props) {
  const [docs, setDocs] = useState<string[]>(policy.allowed_documents);
  const [recipients, setRecipients] = useState<string[]>(policy.allowed_recipients);
  const [approval, setApproval] = useState(policy.always_require_approval);

  // Reset the form when the server accepts an edit or starts a new run.
  useEffect(() => {
    setDocs(policy.allowed_documents);
    setRecipients(policy.allowed_recipients);
    setApproval(policy.always_require_approval);
  }, [policy, runId]);

  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((x) => x !== value) : [...list, value];

  const dirty =
    approval !== policy.always_require_approval ||
    [...docs].sort().join() !== [...policy.allowed_documents].sort().join() ||
    [...recipients].sort().join() !== [...policy.allowed_recipients].sort().join();

  return (
    <section className="panel" aria-labelledby="policy-h">
      <div className="panel-head">
        <h2 id="policy-h"><span className="step-num">2</span>Permissions</h2>
        <span className="small muted">policy v{policy.version}</span>
      </div>
      <div className="panel-body">
        <div className="perm-group">
          <div className="eyebrow">The assistant may read</div>
          {catalog.documents.map((d) => (
            <div className="perm-row" key={d.id}>
              <label>
                <input type="checkbox" checked={docs.includes(d.id)} disabled={disabled}
                  onChange={() => setDocs(toggle(docs, d.id))} />
                <span className="who"><div>{d.title}</div><div className="mono muted">{d.id}</div></span>
              </label>
              <LabelChip label={d.label} />
            </div>
          ))}
        </div>

        <div className="perm-group">
          <div className="eyebrow">Allowed recipients</div>
          {catalog.contacts.map((c) => (
            <div className="perm-row" key={c.email}>
              <label>
                <input type="checkbox" checked={recipients.includes(c.email)} disabled={disabled}
                  onChange={() => setRecipients(toggle(recipients, c.email))} />
                <span className="who"><div>{c.name}</div><div className="mono muted">{c.email}</div></span>
              </label>
              <span className="class-chip">{c.class}</span>
            </div>
          ))}
        </div>

        <div className="toggle-row">
          <label htmlFor="always-approve" className="small"><strong>Always require approval to send</strong></label>
          <span className="switch">
            <input id="always-approve" type="checkbox" role="switch" checked={approval} disabled={disabled}
              onChange={(e) => setApproval(e.target.checked)} />
            <span />
          </span>
        </div>

        <details>
          <summary className="small" style={{ cursor: "pointer", fontWeight: 600 }}>Data label rules (fixed)</summary>
          <table className="rule-table" style={{ marginTop: 8 }}>
            <thead><tr><th>Draft label</th><th>Internal</th><th>External</th></tr></thead>
            <tbody>
              {catalog.label_rules.map((r) => (
                <tr key={r.label}>
                  <td><LabelChip label={r.label} /></td>
                  <td><span className={`badge ${RULE_CLS[r.internal]}`}>{RULE_WORD[r.internal]}</span></td>
                  <td><span className={`badge ${RULE_CLS[r.external]}`}>{RULE_WORD[r.external]}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted">A draft inherits the highest label the session has read. Deny always wins; approval never overrides it.</p>
        </details>

        {dirty && (
          <div>
            <p className="dirty-note"><Icon name="info" size={13} /> Unsaved changes.
              {hasPending && " Applying cancels the pending approval."}</p>
            <div className="perm-actions">
              <button className="btn btn-primary" disabled={disabled}
                onClick={() => onApply({ allowed_documents: docs, allowed_recipients: recipients, always_require_approval: approval })}>
                Apply permissions
              </button>
              <button className="btn" disabled={disabled} onClick={() => {
                setDocs(policy.allowed_documents); setRecipients(policy.allowed_recipients); setApproval(policy.always_require_approval);
              }}>Undo</button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
