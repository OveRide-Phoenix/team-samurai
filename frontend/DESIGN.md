# Samurai design contract

This documents the existing UI moved from ui/ into frontend/. This migration preserves appearance, DOM, callbacks and browser storage; it is not a redesign. Detailed user decisions remain in AGENTS.md.

## 1. Direction
Airy company workspace with tinted liquid-glass chrome, warm peach/lavender atmosphere and minimal copy. Hark inspired materials; Samurai owns the layout and palette.

## 2. Colors
Source of truth: src/styles.css :root and :root[data-mode='dark']. Light background #f7f3ee, foreground #352e2b, secondary #73635b, primary #695043. Dark background #201d1c, foreground #f4eee6, secondary #c0afa1, primary #e6c8a4. Glass tint is warm porcelain rgba(255,248,238,.94) or smoky champagne rgba(65,54,45,.94). Shader palettes live in src/Atmosphere.tsx.

## 3. Typography
Self-hosted Inter Variable. Existing hierarchy: 11–14px metadata/body controls, 18px expanded team heading, 25px wordmark, 28–40px company headings, 32–48px onboarding. Preserve the current CSS scale and responsive rules.

## 4. Spacing and layout
Existing desktop Home width 348px; conversation width 600px. Fixed 84px header, independent pane scroll, full-width dashboard masonry with 360px column target. Small-screen team stays present. Source: src/styles.css responsive rules.

## 5. Reused primitives
BusinessPanel: offer, prospects, pricing, evidence, launch plan; compact/expanded, pinned, editable local actions. TeamPanel: idle, working, waiting, done, stopped; compact or expanded. Floating tabs: Chat/Company, selected indicator with equal insets. Composer: editable, submitting, cancellable. Settings: anchored dropdown; card order editing opt-in. Onboarding: required fields, validation, Back; company created only after completion.

## 6. Motion and interaction
All page/view reveals: 850ms ease-in-out, opacity plus blur 10px to 0 and translateY 6px to 0, transient grain. Reduced motion disables transitions and freezes shader. Chat stays mounted to preserve drafts/scroll. Keyboard alternatives accompany card dragging.

## 7. Depth and surface
Strong theme tint on navigation/composer; sharp foreground; selective refraction via LiquidBackdrop. Quiet card shadows and concentric rounded surfaces; no fake 3D bevel. Cards and team share styling from src/styles.css.

## 8. Accessibility and existing limitations
Keep named controls, visible keyboard focus, required input validation, responsive layouts and reduced-motion behavior. No live AgentOS transport, cloud deployment or end-user authorization is implied. Safari/Firefox refraction support is partial. Existing bundle-size warning remains; no Lighthouse or dev-tool instrumentation audit is part of this folder migration. These limitations predate the move and remain follow-up work rather than new implementation.

## Refinement — 12 October 2026
Landing omits the team and dental-demo shortcut. Company-name intake is one floating pill with an inset circular upward-arrow submit (same send primitive), 40px target, disabled empty state. Pointer focus has no outline; a surface/shadow change retains visible input focus, and the send button keeps keyboard focus. Company workspaces retain the team. Dark content surfaces become lighter taupe: card rgba(76,65,57,.97), glass rgba(75,64,56,.88), supporting surface rgba(83,69,57,.90); atmosphere remains unchanged. Dark reveal grain peaks at .045, fades through .02, blends soft-light, and blurs by .4px. Light reveal remains .22/.12; both last 850ms and reduced motion removes grain.

## Live journey activity
Prerequisite pages come from the backend and cover every required founder context field. Team roles expand in place with native details/summary controls to show retained step events. Completed details remain visible. No invented percentage or simulated worker. Existing theme tokens and card geometry apply.

## Long artifact content
Artifact lineage is retained in validated state, outside founder-facing cards; present known responses through the panel catalog. Message and panel content can shrink and wrap unbroken URLs/IDs within their existing width. Research blockers remain explicit in plain language; no source-free result is presented as validated.

## Clean founder output
No raw artifact JSON, wire-status chat labels or repeated evidence badges in the founder flow. Company brief is one definition-list card containing idea, customer, market, budget, skills and milestone; extra context stays in Details. Evidence has one quiet aggregate review label, source links and expandable additional findings. Full validated provenance remains stored, not printed as JSON. Preserve draft/assumption distinctions at panel level.

Collapsed Details retains all validated findings, source excerpts, conflicts and plan steps. Bounded native payloads may contain up to 500 draft/evidence entries, 400 plan steps and 100 sources per finding. Show only the first three findings/steps and two source links initially; keep overflow readable through Details. Mobile dashboard Team scrolls with cards so it cannot cover results.

Mobile result disclosures retain native indicators and at least 44px tap height. Source-support excerpts identify their finding inside Details.

## Interactive business panels — 13 October 2026

Known views use purpose-built interactive layouts, not paragraphs of artifact fields: Brief Overview/Inputs with customer/market context and a milestone; evidence review counts, filters and source disclosures; offer/inclusions and saved review; selectable pricing hypotheses and a discussion draft; a real checklist progress ring; filterable prospects with a saved shortlist. Discussion controls fill the existing composer without submitting a run. Preserve company-scoped callbacks, uncertainty and source lineage.

Shared controls live in `src/panel-controls.css`, used by the host and the custom-view shell. Custom components get a transparent, content-sized frame and a first important CSS layer that protects theme tokens, typography and control styling from generated CSS. Inline style attributes are rejected by the frame CSP. A size-only message accepts only the exact opaque iframe window and bounded integer height; it cannot invoke host functions. The previous fixed tinted calculator block is removed.

Local development exposes labelled sample previews at `?preview=panels` and `?preview=intake`; production excludes that loader. They make no backend or provider calls.

Default panels keep copy concise: idle team roles show names/icons with descriptions on expansion; pricing explanations, prospect reasons, owners and notes sit behind disclosures. Brief labels and actions are short. Preserve primary values, evidence status, scenario labels and every saved action. No information is discarded to make the view lighter.


## Team areas — 13 October 2026

Company has a centered liquid-glass workflow filter bar with independently toggled Researcher, Strategist, Verifier and Sales buttons. There is no Overview button. With nothing selected, show all current panels including the brief and uncategorized company outputs; multiple selections show the union of those workflows; Researcher holds research evidence; Strategist holds the offer, pricing and delivery plan; Verifier holds verification reviews; Sales holds prospects and sales drafts. Show only the latest native result of each artifact/component type while retaining older lineage and conversations. Custom/composed views remain with their creation area.

Each selected role starts with a full-width dashboard and the original floating bottom chat bar. Opening the bar reveals panels on the left and its focused conversation on the right; closing restores the dashboard. Mobile opens the conversation in the content area and the close control returns to panels. Keep the conversation mounted and retain drafts and scroll position. The centered workflow filter uses actual backdrop refraction, a restrained tint and clear icon circles. Selected filters stay visibly pressed; mobile shows all four choices without horizontal clipping. Keep area drafts, selected area, saved actions and old workspace data. Main Chat remains the company-wide conversation. A suggested handoff opens the other area with the original request as a draft; it never submits automatically. Preserve cancellation and single-run behavior when navigating during work. Do not redesign intake in this pass; company creation remains brief-first.

Scope requests through the exact typed team_area navigation choice in CopilotKit forwardedProps. Backend tool/stage guards enforce execution scope and prerequisites; topic redirection uses the bounded handoff tool and scope instructions. Keep identity/state/tools/dependency overrides rejected and JWT scopes unchanged. Backend model access is verified separately from the labelled local preview.

Opening or closing the floating chat bar slides panel positions with a gentle spring; do not blur or replay grain for this motion. Other page/view reveals retain their existing timing. One workflow focuses its conversation; zero or multiple selected workflows use the general Samurai conversation and existing general backend scope. Clearing filters fades the chat back to general context. Keep typed single-area transport validation, run cancellation, keyboard focus and reduced motion. Persist filter selections and migrate the previous single choice without discarding saved work.

Workflow filtering keeps existing dashboard cards mounted. Hide excluded cards and reveal the same instances so choices, disclosures and sandbox input values survive toggles. Only newly revealed cards fade in; never replay a reveal for cards already visible. Keep the chat-open spring separate and preserve accessible card ordering.

Workflow selections retain click order; a newly selected or reselected workflow appends its cards after the existing groups. Use measured masonry positions in Company: place each card in the shortest column, so new cards fill gaps without rebalancing the existing cards. Use CSS order without moving mounted card DOM or sandbox frames. With filters active, manual card ordering stays inside its workflow group; clearing filters restores the saved company-wide order. Newly revealed cards use the same 850 ms ease-in-out blur/fade/lift frames as page reveals, scoped to the card interior so the chat-open spring remains independent.

Removing a workflow reverses the same 850 ms page reveal before its cards leave the layout. Keep outgoing cards mounted and in their slots until completion, with interaction disabled. Rapid reselection reverses the in-progress fade without losing card state. Remaining cards then move smoothly to fill the gap; reduced motion removes immediately.

Home retains the original portfolio layout: the centered idea heading, floating company-name field and saved company tiles. The local panel preview Home button and intake cancel return to the normal portfolio Home; do not replace Home with an isolated demo-entry screen when refining the Company dashboard. Preview workspaces stay in their separate cache.

Do not show search controls anywhere in the product UI: Home, workspace headers, prospect cards or generated tables. Remove the Cmd/Ctrl+K search shortcut. Keep workflow filters, prospect fit/shortlist filters and panel actions.

The Chat sidebar uses the plus control beside Pinned to add panels. Do not repeat an Add a panel button at the bottom of the sidebar; keep the existing composer and Company-header controls.


## OpenUI composed views — 16 October 2026

OpenUI owns the text/metric/list/table composition renderer. Its allowlisted components retain the existing `declarative-*` markup, Inter, theme tokens, native table semantics and scroll container. The surrounding BusinessPanel still owns title, pinning and assumptions. The shared preview includes an illustrative Pilot comparison; no new visual theme or chat shell is introduced.


## Calm panels — 16 October 2026

Use generous shared card padding and a quiet title without decorative category icons. Keep controls visible and keyboard accessible. Replace nested segmented-control shells with simple underlined choices; soften pricing selection and remove nested milestone/metric boxes. OpenUI metrics use unboxed large values and share a two-column layout when adjacent. Tables keep semantic headers and a screen-reader row-count caption, with fine dividers instead of toolbars and framed grids. Preserve draft/source distinctions, disclosures, company-scoped actions, both themes and mobile tap targets. Hide the upstream development inspector in founder previews.


## Visual prompt results — 16 October 2026

The default company entry is the dashboard. Evidence/prospect mixes and delivery completion use data-derived rings with short legends. OpenUI's Table component projects compatible two-column numeric data into comparison bars; full original tables stay in Details, and mixed currencies/cadences stay as tables. Scenario lines connect only supplied endpoints and retain explicit synthetic labels, exact values, assumptions and constraints. Pricing choices use three tinted visual tiles. The charts use native SVG/CSS and existing beUI motion tokens; Bklit's rings, legends and quiet chart surfaces are design references, not a vendored dependency. All founder controls and full findings remain available. The multi-panel preview is a component catalog; one prompt does not automatically generate its entire contents.


## Field and scrollbar polish — 16 October 2026

Share quiet porcelain/champagne field fills, fine theme-aware borders, generous
text padding, rounded selects and clear keyboard focus. Keep the company-name
pill and OpenUI composer; the composer starts at one line and grows for longer
drafts. Scrollable content uses thin rounded theme-aware thumbs on transparent
tracks rather than hiding navigation or showing heavy native rails. Preserve
resizeable long-answer fields, labels, native semantics, disabled states and
reduced-motion/forced-color preferences.


## Progressive brief and compact utilities — 16 October 2026

Use one small OpenUI brief card with five Back/Next reading steps rather than an
all-at-once overview. Each step presents one topic and at most two primary facts.
Long answers remain available through Read full answer; evidence, assumptions
and framework lineage sit under Evidence & context on the final step. Change
this opens an existing chat draft for the current topic without submitting it.
Files and Founder operations use ordinary measured masonry slots, never a
full-width utility row on desktop. Learning, Scenarios and Schedules start
collapsed. Mobile keeps readable single-column cards and the same navigation.


## Saved launch drafts and measurements — 16 October 2026

Native Builder, Marketing, Sales and analysis artifacts use the allowlisted
OpenUI WorkDraft reader, with one short item at a time, direct section choices
and Back/Next. Keep full long content, source links and review notes in
disclosures, and keep workflow-filter toggles from resetting the reading step.
These are draft outputs, not evidence coverage scores. Supplied measurements
show their actual value, unit, period and source, without rounding tiny values
to zero or claiming independent verification. No button here sends outreach,
publishes, deploys or changes backend approval. The isolated `?preview=drafts`
route uses illustrative fixtures and the same canonical projection/renderer.

Generated business results settle into the requested card order after reveal,
ahead of Files and Founder operations that load first. Preserve the same mounted
cards and reading steps across workflow filters; utilities must not displace the
brief below the fold on mobile merely because they arrived earlier.
