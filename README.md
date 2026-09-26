# AgentGate Playground

A small sandbox where an AI assistant proposes tool calls and a policy gate decides whether each one runs. All tools are simulated; no real email or file access.

## What it shows

- The assistant reads synthetic club documents and proposes actions: read a document, write a draft, send a draft.
- Each proposal is checked against explicit rules and is **allowed**, **denied**, or **held for human approval**.
- Documents carry a data label (`public`, `internal`, `confidential`), and drafts inherit the highest label read, so sensitive content can't be sent to the wrong people.
- Hidden instructions inside documents can't press the approval button.

## Status

Built on an existing prototype; work during hackUMBC 2026 (September 26–27) is committed here in stages. Setup and run instructions will be added once the app code is in place.

Here are the link to the Slides of AgentPlayground created on HackUMBC 2026 ( https://drive.google.com/file/d/1Wmle25lBTUHrTIq3dQIS7yHTcB2r3Rxr/view?usp=drivesdk )

Infographic Poster Simple made in AI (https://drive.google.com/file/d/1ppJHhx0uRkV_1f2pGMt3KwKLJKUoy9Ro/view?usp=drivesdk )

Infographic Poster initial Canva draft (https://canva.link/x3sukdnx0kvvdy1 ) 
