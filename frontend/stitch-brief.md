# Samurai — Stitch design brief

Submitted 11 October 2026 with four screenshots. Project: https://stitch.google.com/projects/14188965435196838608

Design a premium responsive web application named Samurai: AI Idea → Company. A founder describes a business idea and directs a coordinated team to research demand, shape an offer, find customers, support sales and delivery, and improve the business. We help create and run a company; generating an app is only a supporting capability when needed. Example: “Build an AI receptionist for dental clinics in India with a budget of ₹2 lakh.”

Use the attached screenshots as a visual starting point, not a fixed wireframe. Hark inspires the UI materials and components: airy atmospheric backgrounds, floating pill navigation, a soft masked blur along the top header, a full-width bottom blur behind a crisp chat composer, and useful translucent contextual panels. Explore a better UX flow and layout for company building. Do not copy Hark’s navigation or force every interaction into chat.

Give the product a restrained liquid-glass feel: real optical backdrop refraction, clear thin surfaces, restrained edge highlights and gentle spring motion. No fake 3D bevels, heavy drop shadows, glossy raised cards or embossed controls. Text must stay sharp while the background bends through the lens. Preserve readable solid content inside business panels. Avoid neon, excessive distortion, thick borders, dense dashboards, and generic chatbot styling. Use bold, beautiful Inter typography with short copy and minimal small helper labels.

Use warm porcelain, sand and peach with graphite text for light mode, and charcoal with champagne highlights for dark mode. No green. Keep both modes airy and polished; do not use Samurai logo colors as the whole palette.

Design these states:

1. First landing: “An idea is just the beginning.” Invite the founder to describe their business, then ask only essential follow-up questions. Show their persistent agent team. Include access to existing companies when present.
2. Fresh company: no seeded conversation or fabricated panels. Give a clear starting action and keep the team visible.
3. Working company: show coordinated Researcher, Strategist, Verifier and Sales activity, concise conversational updates, and contextual interactive results. Generate only panels useful to the current task; useful results can be pinned.
4. Company progress: a coherent journey from validation through first customers and delivery. Surface the next decision, evidence, assumptions and actionable outputs. Let the founder edit or regenerate one deliverable.
5. Multi-company switcher: separate company context and history; easy switching without losing work.
6. Mobile: a usable composer, readable panels and a persistent compact team presence.

Show concrete panels: a competitor/evidence comparison, an offer with pricing and assumptions, a prospect shortlist with filters, a launch plan, and a decision awaiting approval. Distinguish sourced facts, hypotheses, sample data and measured results. Consequential actions like sending outreach or buying ads need founder approval.

Global search should be an inline field focused by Cmd/Ctrl+K with results directly below it and soft blur behind; no command-palette modal. Add subtle motion concepts for panel arrival, progress, hover and the navigation indicator, with reduced-motion support.

Make the PRIMARY direction an adaptive dashboard of generative UI panels rather than a large central chat thread. The whole company workspace is a calm, spacious canvas of panels that changes with the founder’s current goal. Show market evidence, a company offer, prospects, pricing, a launch plan, next decisions and team activity in a cohesive layout. Keep a compact chat-results area for brief progress and responses, plus a persistent chat button at the bottom that opens a focused conversational composer. A request such as “Find our first customers” should reshape the relevant dashboard panels instead of filling the screen with paragraphs. Retain useful pinned panels and give changes understandable transitions. Avoid a wall of tiny identical KPI cards. Explore two variations of this panel-first dashboard and one alternative layout for comparison. Show the light desktop dashboard, its dark counterpart, fresh landing/empty company and mobile adaptation. Keep this a product UI, not a marketing-only website.

Technical context: frontend React/TypeScript, assistant-ui, reusable validated generative UI panels; planned Gemini intelligence and Agno AgentOS backend with Google Cloud infrastructure. Backend integration is forthcoming; the attached screens are a local UI preview. Do not present simulated activity as live work.

## Screenshots to attach

- `design-evidence/landing-light.png`: current light landing.
- `design-evidence/empty-dark.png`: current empty company and persistent team.
- `design-evidence/liquid-workspace-light.png`: current conversation and interactive panels with glass refinement.
- `design-evidence/liquid-workspace-dark.png`: dark counterpart.
- `design-evidence/company-mobile.png`: current mobile constraints and team presence.

Do not upload private signed-in Hark account screenshots. Use our sanitized product screenshots and the public Hark article at https://hark.com/articles/introducing-hark-pro for visual context.

## Generated exploration and refinement

Stitch created a first panel-first dashboard, then a focused refinement with four panels: Next Decision, Market Evidence, Offer Architecture, and First Customers. The refinement requested shorter copy, Inter throughout, explicit sample labels, restrained optical glass rather than bevels, and matching light/dark modes. Both refined desktop screens were generated. These are visual proposals; no mock figures, verification labels, agent activity, approvals or integrations are evidence of a live backend. The local UX has not been replaced.

My recommendation: retain the adaptive canvas, prominent next decision, compact team and bottom chat dock; simplify the navigation and remaining panel copy further, and preserve our original atmospheric background. Evaluate freshness and panel transitions in an interactive prototype before adopting the whole layout.
