# Three-minute demo script

**Before judges arrive:** run `./run_demo.sh`, open http://127.0.0.1:8000, choose **Replay**, and select card 1. Decide *now* whether you will show Live mode; don't decide mid-pitch. Keep a recorded live run as a backup and label it as a recording.

| Time | Do | Say |
|---|---|---|
| 0:00–0:25 | Point at the banner | "An assistant may read an instruction inside a document. That doesn't mean the instruction should control its tools. Everything here is simulated." |
| 0:25–1:05 | Card **2 Restricted document**. Point at the red hidden-instruction box. Press **N** twice. Click card 2 in the timeline | "The notes try to make the assistant open the member roster. It *proposed* that read, and the gate denied it: rule `document_not_permitted`. No text came back." |
| 1:05–1:55 | Card **4 Sensitive information**, **Public notes**, press **N** three times (sent). Switch to **Confidential budget**, press **N** three times | "Same sponsor, same permissions. The only difference is which document was read. The budget made the session confidential, the draft inherited that label, and confidential data can't go external." Point at *Previous run vs this run*. |
| 1:55–2:30 | Card **1 Normal work**, press **N** three times. The approval dialog opens | "Even allowed sends wait for a human. This approval is bound to this exact content. Text in a document can't press this button." Approve and show one outbox entry. |
| 2:30–3:00 | Show one screenshot of `dispatch_action` in `backend/app/dispatcher.py` | "The model proposes, the policy decides, and the tool runs only after the check. It's three simulated tools, not a universal prompt-injection defense." |

**If Live mode is on:** say "Live" before starting. Try the **Sounds helpful** example in card 1. If the model ignores it, say so; do not promise that an attack will work. Switch explicitly to Replay to demonstrate the policy check. Invite visitor-written attacks after the timed pitch.

**Browser walkthrough:**

- [ ] All four cards finish in Replay, and their decisions match the table in the README.
- [ ] Card 4: public → 1 outbox entry; confidential → 0, rule `confidential_external`.
- [ ] Approval dialog: Tab cycles its buttons, Escape closes without deciding, "Review send" reopens it.
- [ ] Clicking Approve twice → still 1 outbox entry.
- [ ] Changing a permission while a send is pending → the timeline shows the send as *Stale*.
- [ ] Restart the server with the page open → the page recovers with a fresh session.
- [ ] First Shift+Tab in the approval dialog stays inside; Tab also stays inside while a request is pending.
- [ ] A previous-run comparison identifies whether it came from live or replay mode.
