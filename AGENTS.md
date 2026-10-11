# AI Builder Cup 2026

## Working conventions

- Read the applicable AGENTS.md in every repository before working in it.
- Always use the ponytail skill for coding: make the smallest complete change, preserve working behavior, and verify meaningful logic.

## Chosen product: AI Idea → Company

The team is Samurai. The chosen product helps founders build and run a company from the ground up. The user explicitly chose this topic on 11 October 2026; do not reopen topic selection without their direction.

The promise is “Build my business.” The founder enters an idea, such as “An AI receptionist for Indian dental clinics,” and works with one connected system. Software generation is an optional supporting capability when the business needs it. The primary outcome is a stronger, functioning business: validated demand, a clear offer, qualified prospects, sales, delivery, and improvement through feedback.

Treat company building as a connected journey: validate demand → shape an offer → find customers → support sales and delivery → measure results → improve the business. Generated documents and websites are intermediate outputs; measure actual business progress where possible. Do not imply that revenue or customers are guaranteed.

### Proposed agent responsibilities

These are the product vision, not a claim of implemented capabilities or a requirement to ship every role by the submission deadline.

| Role | Responsibility |
|---|---|
| Researcher | Find competitors, pricing, target markets, reviews, and pain points, preserving sources and uncertainties. |
| Strategist | Develop the ideal customer profile, positioning, offer, pricing, and business model from evidence. |
| Product Manager | Define the minimum viable offering, delivery requirements, user stories, and roadmap; architecture when software is needed. |
| Builder | Create the software the company needs, including schemas, APIs, UI, and deployment configuration where appropriate. |
| Marketer | Develop landing pages, advertising, social content, and email campaigns aligned with the offer. |
| Sales | Identify and qualify prospects, prepare outreach, sales scripts, and objection handling, and track feedback. |
| Analyst | Assess real performance and recommend improvements to the offer, acquisition, conversion, and operations. |
| Verifier | Check evidence, detect contradictions and unsupported assumptions, and run appropriate checks on generated software and business artifacts. |

Research must inform strategy; strategy must inform execution; sales and customer feedback must update subsequent decisions. Avoid disconnected agents producing independent documents. Verification must use sources, tool results, or executable checks; a second model agreeing with the first is insufficient evidence.

The orchestrator coordinates research, planning, execution, and verification using shared company state. Agent roles do not require separate deployed services. Use deterministic code for routing, validation, arithmetic, persistence, and rendering where possible, and Gemini for reasoning that benefits from it.

### Competition positioning and scope

- Retail & Commerce is the current leaning if the core demo proves customer acquisition → sale → delivery → improvement. Future of Work & Enterprise Productivity remains a plausible fit for broader cross-function company workflows. The user has not finalized the submission category; choose exactly one before submitting.
- The version submitted by 18 October must be strong enough for shortlisting: a focused, reliable, end-to-end company-building journey, meaningful GenAI, differentiated execution, and clear user value.
- Prioritize technical merit (40%), then problem alignment and impact (25%), innovation (25%), and UX (10%). Do not expand the agent count or feature list at the expense of a convincing core journey.
- An illustrative demo opportunity is to discover evidence that challenges the original idea, verify it, adjust the offer or strategy, and carry that change into execution.
- The public timeline lists evaluation on 19 October–6 November, finalists on 7 November, and the finale on 4 December. Public rules reviewed on 11 October do not explicitly settle whether post-deadline commits or redeployments count. Preserve the submitted version and confirm the policy with organisers before relying on later changes.

## UI direction: Hark Pro-inspired company workspace

References: [Introducing Hark Pro](https://hark.com/articles/introducing-hark-pro), [Using Hark Pro](https://hark.com/using-hark), and the actual signed-in Hark app. On 11 October, the article was read and the Home/chat and Projects surfaces were inspected. Active agent execution and panel creation were not observed; inspect these before claiming interaction fidelity. Use public or sanitized references for design artifacts; exclude private account content.

The user specifically likes Hark's conversational interface, persistent left pane, custom panels, visible activity, atmospheric background, and blur at the top. Preserve this direction. The experience should feel like a working company directed through conversation, with short messages and interactive results rather than long generic answers.

### Layout and interaction

- Chat is the main interaction surface. The founder interacts with one system, not seven separate agent chats.
- The persistent left pane shows useful company context: what is happening, decisions requiring the founder, and custom business panels. Keep it contextual and calm; avoid a dense feature inventory.
- Show understandable work status, such as “Researcher is checking competitor pricing” or “Sales is qualifying prospects,” with evidence and results available when needed. Do not display simulated activity as live work.
- Surface actionable decisions such as reviewing an offer, approving outreach, or resolving conflicting evidence. Controls must have clear outcomes and visible pending, success, and failure states.
- Use brief conversational updates and embedded actions. Reveal detailed evidence and artifacts progressively instead of flooding the chat.
- Keep ongoing company work, decisions, files, and outputs persistent across sessions. Longer undertakings may have dedicated project contexts without fragmenting the company state.

### Generative UI

- Render contextual interactive business views from structured agent outputs: prospect tables, pricing comparisons, offer reviews, campaign previews, and performance charts.
- For example, “Who should we sell to first?” can produce a prospect table; “Is this pricing viable?” can produce a pricing comparison.
- Useful views can remain pinned in the left pane and update from the underlying company state. Support asking questions about a panel's data.
- Use validated structured data and reusable UI components. Model output must not become arbitrary executable UI code in the founder's session.
- The conversation directs the work; the panels show durable business state. Show agent activity through meaningful progress, decisions, and results.
- Distinguish sourced facts, hypotheses, and measured results. A continuous analyst requires real measurements; label illustrative or demo data clearly.

### Visual language

- Soft atmospheric backgrounds, subtle gradients, translucent frosted surfaces, restrained floating navigation, generous spacing, and readable business content.
- The top blur should soften scrolling content behind floating controls and create depth. Keep text and primary actions crisp and accessible.
- Hark's article describes a changing atmospheric simulation. This is inspiration, not a requirement to implement weather integration or WebGL before the core flow works.
- Keep motion subtle, respect reduced motion, and provide usable layouts on smaller screens. Visual polish should support comprehension and useful action.

### Product principles learned from Hark

- Memory should affect future decisions rather than merely preserve chat history.
- Connected tools should turn intent into completed work, with progress and outcomes visible.
- Proactivity should surface timely, relevant next steps and pace them appropriately.
- Action buttons should help complete work, not just add notifications.
- Custom panels should be useful, interactive views over connected data, not decorative widgets.
- The founder must retain control over consequential actions and connected accounts. Publishing, sending outreach, spending money, and commitments need appropriate explicit authorization; this product vision does not authorize those actions.
- Hark's privacy, vault, and execution claims are its stated capabilities, not proof that this project provides equivalent guarantees. Describe only safeguards and integrations actually implemented.

## Intended Google stack

| Service | Intended responsibility |
|---|---|
| Firebase Hosting and Authentication | Host the founder workspace and handle sign-in. |
| Cloud Firestore | Persist company research, strategy, prospects, tasks, approvals, outputs, and results; expose live state updates. |
| Cloud Run | Run backend APIs, orchestration, integrations, and durable execution or verification jobs. |
| Gemini | Reason over business context, perform grounded research, generate business artifacts, invoke tools, and recommend evidence-based changes. |

Google Search grounding can support current research and citations; the verifier must still assess whether sources support a claim. Outreach, ads, payments, and sales measurement require their relevant APIs and connected accounts. These services are intended architecture, not existing integrations. Begin with the smallest coherent backend and shared company state; add infrastructure only when the workflow needs it.

## Judging rubric

Keep this rubric explicit in every project, product, technical, deck, and demo decision:

1. **Technical Merit & GenAI Implementation — 40%**: GenAI must directly solve the problem; the prototype must be functional, technically sound, and credible at scale.
2. **Problem Alignment & Impact — 25%**: The chosen theme, users, and measurable value must be unmistakable.
3. **Innovation & Creativity — 25%**: Show a differentiated approach and non-superficial use of GenAI.
4. **User Experience & Solution Design — 10%**: Make the end-to-end experience intuitive, accessible, and cohesive.

The prototype must use Gemini or Gemma, or a listed agentic platform, and be deployed on Google Cloud through Cloud Run or Firebase. Before calling work complete, verify that the working prototype and three-minute demo visibly prove the four rubric areas, in that priority order.

## Mandatory submission checklist

- **Proposal PDF:** use the prescribed [pitch deck template](https://docs.google.com/presentation/d/13rg7vW43mEH6DkpuusAE6fdoEylSFz8waNpE4RLzoUg/edit), then export the final deck to PDF. Cover the AI vision, positive impact, one problem statement, user benefit, feasibility, and scalability.
- **Functional prototype:** a working Google Cloud AI solution deployed through Cloud Run, GCP, or Firebase, with its capabilities and benefits demonstrated.
- **Documentation:** a public YouTube, Vimeo, or Google Drive link to a working-product video no longer than three minutes. The submission instructions also say 3–4 minutes, but the form says "up to 3 minutes" and the FAQ says "under 3 minutes"; use the stricter limit.
- **Category specification:** choose exactly one of the six challenge options in the submission form: BFSI; Retail & Commerce; Manufacturing; Media, Content & Digital Experiences; Future of Work & Enterprise Productivity; Sustainability & Social Impact. The separate five-category list on the public themes page conflicts with the form; use the actual form's options when submitting.
- **Submission form:** provide an accessible deployed prototype URL, public GitHub URL, final deck PDF, public demo video URL, and a solution description of at most 1,024 characters explaining the Google services actually used. The form explicitly asks about Firebase, Firestore, Cloud Run, and Gemini; do not claim an integration that the prototype does not use. Check every link from a signed-out session and keep the app available through evaluation. The form states a deadline of 18 October 2026, 11:59 PM IST.

## Official FAQ requirements

- Submission requires all four: a working deployed prototype link, a public GitHub repository, a solution deck, and a video demo under three minutes.
- The prototype must be a fresh project created during the hackathon and primarily use Google Cloud; other-cloud-first solutions are ineligible.
- A build team must have 2–4 members. Solo registration is allowed only while forming or joining a team; solo competition is not.
- Every member must be age 21+, based in JAPAC, and be a working professional, entrepreneur, or startup member. Students are not eligible; one student disqualifies the full team.
- A participant may be in only one team. Cross-country JAPAC teams are allowed; members outside JAPAC are not.
- Team changes are allowed only while registration is open. The official FAQ and main timeline currently state 11 October 2026 as the closure date; recheck it before making a team change.
- Only two members of a shortlisted team may attend the Singapore finale.
- Event-specific registration or waitlist issues: `support+aibuildercup@hack2skill.com`.

## Prize objectives

Target the overall prizes first: **Winner — USD 10,000**, **First Runner-up — USD 7,000**, then **Second Runner-up — USD 5,000**. Every project decision should also preserve a credible path to one or more specialist awards: **Best Use of Google Cloud AI Tools — USD 2,000**, **Most Impactful Solution — USD 2,000**, **Social Choice Award — USD 2,000**, and **Best UI/UX — USD 2,000**.
