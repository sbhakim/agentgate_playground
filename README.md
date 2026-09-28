<p align="center">
  <img src="docs/images/agentgate-logo.png" alt="AgentGate Playground logo" width="420">
</p>

# AgentGate Playground

A small sandbox where an AI assistant proposes tool calls and a policy gate decides whether each one runs. All tools are simulated; no real email or file access.

![AgentGate Playground showing a restricted document request denied by the policy gate](docs/images/agentgate-panel.png)

*Replay demo: reading the meeting notes is allowed, but the hidden instruction's request for the member roster is blocked.*

## What it shows

- The assistant reads synthetic club documents and proposes actions: read a document, write a draft, send a draft.
- Each proposal is checked against explicit rules and is **allowed**, **denied**, or **held for human approval**.
- Documents carry a data label (`public`, `internal`, `confidential`), and drafts inherit the highest label read, so sensitive content can't be sent to the wrong people.
- Hidden instructions inside documents can't press the approval button.

## Setup

Needs Python 3.11 and Node 20.19+ or 22.12+. Run these from the repository root.

```bash
conda env create -f environment.yml   # or: pip install -r backend/requirements.txt
conda activate agentgate
./run_demo.sh
```

`run_demo.sh` installs frontend packages, builds the UI, runs the backend tests, and serves everything at http://127.0.0.1:8000. Restarting clears all demo state.

For development with hot reload, run `cd backend && uvicorn app.main:app --reload --port 8000` in one terminal and `cd frontend && npm run dev` in another, then open http://localhost:5173.

**Tests:** `cd backend && python -m pytest -q` (no API key or network needed).

## Replay and live mode

Replay mode needs no key: it plays scripted proposals through the real policy checks. For live mode, copy `.env.example` to `.env` and choose a provider:

- Gemini: `AGENTGATE_PROVIDER=gemini` with `GOOGLE_API_KEY` or `GEMINI_API_KEY` exported in your shell. If both exist, `GOOGLE_API_KEY` takes precedence. The example configuration selects Gemini with `gemini-3.5-flash-lite` as its default model.
- Anthropic: `AGENTGATE_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`.
- OpenRouter: `AGENTGATE_PROVIDER=openrouter` with `OPENROUTER_API_KEY`.

Set `AGENTGATE_MODEL` to override the selected provider's model; remove an old model setting when switching providers. Restart the server after configuration changes. Without a provider setting, the app keeps its original Anthropic default.

An exported Google key needs no copy in `.env`. Keep real keys out of Git. Key detection does not verify model access or free quota; check your account's billing before live requests. Tests use mock responses and spend no API credits.

Live runs are capped at 6 model turns and 8 tool proposals. Gemini proposals pass through the same policy checks and human approval as the other providers; failures never silently switch to replay.

## Limitations

- A teaching sandbox with three simulated tools, not a general prompt-injection defense or a production gateway.
- State lives in memory and is lost on restart. Run it on localhost only.
- Labels are coarse and can block harmless drafts; they depend on documents being labeled correctly.
- The model provider still sees whatever the model reads. Labels control tool effects, not prompts.

More detail: [`docs/architecture.md`](docs/architecture.md) and [`docs/demo.md`](docs/demo.md). Credits and inspiration (CaMeL, AgentDojo, and others) are in [`docs/credits.md`](docs/credits.md).

## Presentation materials

- [Presentation slides](https://drive.google.com/file/d/1hFf6BMZFWwRppH1aowtE1NWaxkRCvFcz/view?usp=sharing) — an overview of the project and how it works.
- [Infographic poster](https://drive.google.com/file/d/1EC5mUUZwFC5WpKTHOkC6occjGbtfWIc2/view?usp=sharing) — a visual walkthrough of how AgentGate works.
- [Demo video (3 minutes)](https://photos.app.goo.gl/eQbybRXJjxQCRKUH6) — watch the playground in action.
- [Detailed Infographic poster](https://canva.link/x3sukdnx0kvvdy1).
