# Credits

## Libraries (used as dependencies, not copied)

- [FastAPI](https://fastapi.tiangolo.com/), [Starlette](https://www.starlette.io/), [Uvicorn](https://www.uvicorn.org/), [Pydantic](https://docs.pydantic.dev/): backend and validation
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python): live-mode tool calling
- [pytest](https://pytest.org/): tests; [HTTPX](https://www.python-httpx.org/): OpenRouter requests and API tests
- [React](https://react.dev/), [Vite](https://vite.dev/), [TypeScript](https://www.typescriptlang.org/): frontend

Icons are simple inline SVG paths drawn for this project. No external assets, fonts, or datasets are used; all documents and contacts are synthetic.

## Inspiration (ideas credited; no code used)

- **CaMeL** (Debenedetti et al., "Defeating Prompt Injections by Design", 2025, [arXiv:2503.18813](https://arxiv.org/abs/2503.18813)): policies on tool calls using data provenance. Our session labels are a much simpler, conservative version of that idea, with none of its guarantees.
- **AgentDojo** ([NeurIPS 2024](https://arxiv.org/abs/2406.13352), [repo](https://github.com/ethz-spylab/agentdojo)): a prompt-injection benchmark with a similar email/workspace setting. We borrowed the idea of keeping scenarios separate from runtime behavior.
- **agentgateway** [authorization docs](https://agentgateway.dev/docs/kubernetes/latest/documentation/security/authorization/): the gateway concept is established; this project is a small interactive explainer.
- **Prompt Injection CTF** ([repo](https://github.com/ppradyoth/prompt-injection-ctf)) and Lakera's Gandalf: educational prompt-injection games. AgentGate differs by enforcing rules on *tool calls* rather than prompts, carrying data labels from reads to sends, and binding approval to an exact snapshot.
- [OWASP LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html): layered controls. This project shows one layer, tool authorization.

## AI assistance

Planning and implementation used AI coding assistance from Claude and Codex.

The team also used Google Gemini at several stages of project development. This is a project-level credit, not a claim that Gemini wrote a particular file or that a live run used Gemini. Model names shown in the app should reflect the actual server configuration.

Thanks to Major League Hacking (MLH) and its partners for facilitating access to developer resources, including Backboard and the Google Gemini API. Resource access does not mean those services are integrated into this codebase.


