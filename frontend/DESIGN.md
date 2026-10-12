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
Artifact lineage uses a wrapping preformatted details block with a 240px vertical cap and its own scroll for technical JSON. Message and panel content can shrink and wrap unbroken URLs/IDs within their existing width. Research blockers remain explicit in plain language; no source-free result is presented as validated.
