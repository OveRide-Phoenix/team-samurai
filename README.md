# Team Samurai — AI Idea → Company

An AI company-building workspace for AI Builder Cup 2026. Founders describe a business idea and work with one connected system to validate demand, shape an offer, find customers, coordinate delivery, and improve through business feedback.

Software generation is a supporting capability when the company needs it. The product's goal is business progress, not simply generating an app.

## Current status

Product direction, UI principles, and competition requirements are documented in [AGENTS.md](AGENTS.md). Samurai brand assets are available in [assets/samurai-logo](assets/samurai-logo).

No functional prototype, Google Cloud deployment, or live agent integration is implemented in this repository yet.

## UI direction

A Hark Pro-inspired conversational workspace with an atmospheric background, frosted surfaces, floating controls, and a soft top blur. A persistent left pane shows work in progress, founder decisions, and contextual business panels. Generative UI presents interactive prospects, pricing, offers, campaigns, and performance views as they become useful.

## Intended stack

- Firebase Hosting and Authentication for the founder workspace and sign-in.
- Cloud Firestore for persistent company state and live updates.
- Cloud Run for orchestration, backend APIs, integrations, and execution jobs.
- Gemini for grounded research, reasoning, business artifacts, and tool use.

These are planned services, not existing integrations. See AGENTS.md for the agent responsibilities, verification requirements, and submission checklist.
