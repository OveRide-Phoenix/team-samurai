## Required intake and shared grain fades

Landing removes the kicker and centers the floating company input. Start company opens three placeholder prerequisite pages, preserving Back answers and creating only after required validation. The saved company brief drives a four-role cancellable template preview and a company-specific starting plan. The run starts once in StrictMode and is not replayed after reload. Home cancels onboarding without creating a company.

All view/page reveals use 850 ms ease-in-out blur plus transient SVG grain, including Company → Chat. Reduced motion disables both. Form controls remain above the mobile footer blur; fixed team positioning is restored after transitions.

Fourteen tests and the production build passed. Browser assertions passed for centered input, required fields, Back/forward persistence, deferred creation, saved brief, automatic run, custom-business plan (no dental fixture), cancellation without output, no reload replay, matching Chat timing, transient grain, reduced motion and fixed mobile team. Light/dark desktop/mobile screenshots inspected under `design-evidence/intake-*`. A page/grain sibling key collision was corrected; fresh back/forward/cancel checks recorded zero console errors. Questions remain local placeholders; no backend/Gemini run was tested. Unfinished answers persist only while onboarding is open, not across reloads. The existing bundle-size warning remains.

## Full-width company dashboard and Home-only switching

Company view fills the page: one bold heading at the far left, expanded team card and full-width masonry panels. The old action rail and Add a panel row appear only in chat. Panel creation remains available through the header plus. Idle roles explain intended responsibilities; working/waiting activity details take precedence, retaining explicit preview labeling.

Eleven tests and the production build passed. Browser assertions passed for one visible company heading, absent selector, absent expanded sidebar actions, four role descriptions, title left alignment, desktop/390 px overflow, switching companies through Home, working-to-idle role updates, edit-mode reorder/Done and the panel chooser. Light/dark desktop and mobile screenshots inspected; evidence uses `design-evidence/full-dashboard-*`. The integrated browser could not be controlled in this session; QA used a separate local browser. No live backend was tested.

Workspace settings dropdown/edit mode: browser assertions passed for hidden initial handles, Edit card order, button reorder, Done hiding controls, Escape focus restoration and mobile overflow. Screenshots inspected at desktop/390 px; 320 px header controls do not overlap. Mobile header position no longer transitions during resize. Production build passed. Physical touch drag remains untested.

## Themed selector and reorderable masonry — 11 October 2026

The company switch uses Radix Select with themed trigger, menu, hover and checked state. Business, team and action cards have subtle theme-aware shadows. Dashboard panels use CSS masonry columns with drag handles and earlier/later buttons. Stable panel IDs persist order in each company workspace; old records default to an empty order and new panels append without losing saved ordering.

Eleven tests and the production build passed. Browser checks passed for real drag-and-drop, button reorder, reload persistence, switching companies via pointer and keyboard, independent company orders, dark/light menus and 390 px overflow. Desktop and mobile screenshots were inspected: `design-evidence/masonry-light.png`, `company-menu-light.png`, `company-menu-dark.png`, `masonry-mobile.png`. Physical touch dragging was not tested; the move buttons provide a touch/keyboard alternative. Order is saved in this browser, with no cloud sync. The existing bundle-size warning remains.

Light gradient refinement: richer peach/lavender/cream shader and matching static fallback. Desktop and 390 px screenshots inspected; no horizontal overflow, controls aligned and panels readable. TypeScript check passed. Evidence: `design-evidence/gradient-light-desktop.png` and `gradient-light-mobile.png`.

## Dashboard motion and shader atmosphere — 11 October 2026

The dashboard expand/collapse control now sits beside the company selector. Rendered centre alignment was exact; the Pinned heading no longer contains the control. View changes reveal through a 360 ms blur/fade, preserve the conversation draft, and skip animation for reduced motion.

The Be UI reference uses Paper Design’s mesh shader engine. Samurai uses that engine with its own light/dark palettes, quiet motion, and a capped rendering resolution. Browser assertions confirmed changing shader frames, identical frames after enabling reduced motion, and a usable CSS atmosphere with WebGL2 disabled.

Desktop (1647 × 1111) and mobile (390 px) checks passed in both themes: no horizontal overflow, visible team, and tab indicator bounds matching the selected trigger. Evidence: `design-evidence/shader-1647-light.png`, `shader-1647-dark.png`, `shader-390-light.png`, and `shader-390-dark.png`. The production build passed. Physical-device GPU performance was not measured; the existing bundle-size warning remains.

# First UI slice — QA

Status: **passed for the local frontend slice**, 11 October 2026.

## Tinted glass controls — 11 October

Applied a strong warm porcelain / smoky champagne tint (94% fill) and 16 px frosting to the decorative glass backdrop of the tab group, composer and inline search. Refraction remains beneath the tint; foreground controls stay crisp. Eight browser cases passed across both views, themes and 1647/390 px sizes: tint present, glass bounds matched, indicator geometry preserved and no horizontal overflow. Reviewed [dark desktop](design-evidence/glass-tint-1647-dark.png) and [light desktop](design-evidence/glass-tint-1647-light.png). Production build passed. Chromium only; no behavior or backend changes.

## Generative UI catalog — 11 October

Extended the installed assistant-ui tool renderer with validated evidence-review and launch-plan panels. Existing offer, prospects and pricing views remain. Evidence requires sources for supported claims and permits only HTTP(S) links; source attachment is not labelled independent verification. Launch completion is local founder progress with per-company persistence. Stable panel IDs replace pinned/dashboard contents without duplicate cards or lost task progress.

Production build and nine tests passed, covering catalog validation, safe sources, unique task IDs, legacy state migration, newest panel revisions and existing routing/cancellation. Browser checks passed for requesting both new views, inline expansion, pinning, launch completion/progress, reload persistence, and repeated results preserving completion without duplicate dashboard panels. Both themes passed at 1647 and 390 px with visible team, square action controls, aligned tab indicator, and no horizontal overflow. Reviewed [desktop](design-evidence/genui-1647-light.png) and [mobile](design-evidence/genui-390-light.png); the final progress bar uses Samurai's theme instead of native green.

This is the frontend generative UI rendering layer, exercised with explicitly labelled fixture events. Gemini/AgentOS generation is not connected. Backend payload details are in BACKEND_CONTRACT.md. The existing bundle warning remains (~306 KB gzipped JavaScript); checks used local Chromium.

## Inline panels and expandable Home — 11 October

Inspected the signed-in Hark reference through reversible expand/collapse controls. A chat card grew from 320 px to approximately 775 px at unchanged 512 px width, with `aria-expanded=true` and no dialog. Restored its collapsed state. No private reference content is included in these design artifacts.

Samurai now expands pinned panels in place; search and offer review reveal the panel in Home. Company view extends Home into a full-width dashboard, with the persistent team and a bottom chat button. The conversation stays mounted so its draft and scroll position survive switching views. Mobile opens searched panels in the dashboard rather than the compact team strip. The rejected Stitch mockup was not adopted.

Browser checks passed for offer expansion (approximately 259 → 350 px at unchanged position), collapse, inline search without a dialog, full-width Home, draft/scroll retention, prospect filtering, shortlisting, pinning, offer review, reload persistence, empty-company isolation and reduced motion. Twelve layout cases passed across Chat/Company, light/dark and 1647/1440/390 px widths: shared control heights and vertical centres, equal tab insets, glass bounds, team visibility, and no horizontal overflow. Four additional checks confirmed that the selected tab indicator exactly matches its trigger after desktop/mobile resizing. Unpinned-panel search and mobile search both revealed the existing panel without a dialog. Reviewed [inline panel](design-evidence/panel-inline-expanded.png), [desktop dashboard](design-evidence/dashboard-1647-light.png) and [mobile dashboard](design-evidence/dashboard-390-dark.png).

Production build and six existing state/schema/cancellation tests passed. The existing bundle warning remains (approximately 305 KB gzipped JavaScript). Verification is local Chromium only; no backend or live agents are connected.

## Latest company workspace refinement

Header alignment follow-up: corrected the glass lens's missing centre coordinates, removed the duplicate selected-tab background, and made header controls share a 44 px desktop / 38 px mobile height. The selected indicator matches its trigger with equal 3 px vertical insets. A ResizeObserver remounts only the decorative lens when its host size changes, correcting stale rim dimensions after responsive resizing or search expansion. Twelve geometry checks passed across both tabs, themes and 1647/1440/390 px viewports; sixteen further lens/rim checks passed through repeated desktop/mobile transitions. Reviewed [desktop](design-evidence/aligned-desktop.png) and [mobile](design-evidence/aligned-mobile.png). Production build passed. These checks verify the current header and glass controls; they are not a cross-browser or whole-product accessibility audit.

Follow-up: replaced the rejected bevel/shadow experiment with `liquid-glass-react` backdrop refraction on the view switcher, inline search and composer; panel content remains unchanged. Verified the SVG filter is active in Chromium, mode icons are centred within one pixel in light/dark desktop and mobile views, and mobile has no horizontal overflow. Production build passed (approximately 304 KB gzipped JavaScript). Refraction support in Safari and Firefox is partial according to the component documentation; those engines were not tested. Latest references: [light](design-evidence/liquid-workspace-light.png), [dark](design-evidence/liquid-workspace-dark.png), [mobile](design-evidence/liquid-workspace-mobile.png). Stitch received a separate brief exploring a panel-first dashboard; this has not replaced the local UX.

The current preview uses warm porcelain/peach/graphite light mode and charcoal/champagne dark mode, self-hosted Inter, the original clean controls, and Be UI only for the sliding navigation indicator. A masked footer blur spans the entire viewport, including the left pane, while the composer remains crisp. Subtle entrance and interaction motion respects reduced motion.

Reviewed [light landing](design-evidence/landing-light.png), [dark landing](design-evidence/landing-dark.png), [empty company](design-evidence/empty-dark.png), [mobile workspace](design-evidence/company-mobile.png), and [mobile landing](design-evidence/landing-mobile.png). The landing supports creating separate companies; each new company starts without seeded messages or panels. The team stays visible on desktop and mobile. Cmd/Ctrl+K focuses the inline search field, with results underneath rather than a dialog.

Six schema/routing/cancellation/portfolio tests and the production build passed. Browser checks passed for creating an empty company, cancellation without a generated panel, sample prospects, pinning, inline keyboard search, reload persistence, mobile overflow, team visibility, and reduced motion. Earlier checks also covered company isolation, filtering, shortlisting, offer review, and panel dialogs. The fresh browser session recorded no errors; Motion logged the expected reduced-motion notice. Current JavaScript is approximately 270 KB gzipped; the build still reports its bundle-size warning. No live Gemini request was made.

The earlier evidence and results below describe previous visual iterations, rather than the current palette and navigation.

## Samurai identity refinement

The latest user feedback keeps the airy look and rejects forcing the logo palette. Removed decorative headings, repeated instructions, idle-agent descriptions, and the duplicate price hypothesis label. Shortened action labels and increased the remaining provenance text. Working activity details and explicit preview/sample labels remain.

Reviewed [refined desktop](design-evidence/airy-desktop.png) and [refined mobile](design-evidence/airy-mobile.png). Build/typecheck and four logic tests passed. Browser checks passed for customer generation, shortlist actions, Company view, and mobile overflow; no new browser errors appeared. Earlier screenshots below describe the original slice.

This is a Hark-inspired company workspace adaptation, not a pixel clone. The public reference demonstrates atmospheric conversation styling; the previously inspected app and root AGENTS.md provide the Home pane, actions, panels, and floating navigation direction. The public reference is from [Hark](https://hark.com/). No private account content is included.

## Visual evidence

- [Source and implementation comparison](design-evidence/comparison.jpg)
- [Desktop, 1440 × 1000](design-evidence/desktop.png)
- [Mobile, 390 × 844](design-evidence/mobile.png)
- [Generated prospects and pinned panel](design-evidence/panels.png)

Inspected atmospheric sky/dusk backgrounds, floating navigation, top blur, readable text, rounded conversation cards, Home actions, activity rows, custom panels, and responsive composer. The source's darker conversation and the implementation's lighter business cards are an intentional adaptation. The screenshot comparison is visual direction evidence, not an exact fidelity claim.

## Functional verification

Real browser checks passed for sending a request; prospect generation, filtering, and shortlisting; pricing generation; stopping a request; pinning; offer review; Chat/Company switching; local search; dialog Escape; theme changes; and saved state after reload. Mobile starts with Home closed and has no horizontal page overflow. Initial conversation position was checked after correcting the runtime's automatic scroll behavior. The initial favicon 404 was fixed; subsequent page loads showed no browser errors.

Typecheck and production build passed. Four schema/routing/cancellation tests and four inherited packaging tests passed. Build emits a bundle-size warning (approximately 214 KB gzipped JavaScript); low-bandwidth performance has not been measured.

## Limits

Activity and panels use explicitly labelled deterministic fixtures. No Gemini, Firebase, Firestore, Cloud Run, sign-in, live research, real prospects, or outreach is connected. Keyboard interactions were checked, but a screen-reader audit and cross-browser testing were not performed. The backend event contract is proposed for Kalyan to integrate, not a verified backend integration.


## Landing and dark-surface refinement — 12 October 2026

Removed the landing Team and dental-demo shortcut; the company-name pill now contains the existing circular send control. Pointer focus has no outline, while the surface/shadow response and submit keyboard focus remain. Dark cards, team, actions and messages share lighter warm surface tokens; the shader is unchanged. The dark grain reveal uses lower opacity and soft-light blending; the 850 ms light-mode reveal is preserved.

Production build and TypeScript passed. Desktop/390 px landing, dark dashboard, 250/600 ms transition frames and scrolled mobile content were inspected. Two independent read-only visual reviews approved the final screenshots. The mobile footer allows the entire card to scroll above the chat dock.

A fresh local Gemini 3.5 Flash-Lite intake returned a Company brief and the missing-founder-skills question. Pinning, dark dashboard and reload recovery succeeded. An earlier reload encountered temporary PostgreSQL recovery (503); a subsequent backend read returned 200, and the fresh recording completed without that error. No production deployment or complete research/launch journey was tested.
