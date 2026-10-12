// noqa: SIZE_OK - single self-contained artifact script so slide content, notes, export, and validation stay reviewable together.
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
const workspaceDir = path.resolve(here, "../../..");
const buildDir = path.join(here, ".build");
const outputDir = path.join(here, "output");
const runtimeModules = process.env.RUNTIME_NODE_MODULES;
const skillDir = process.env.PRESENTATION_SKILL_DIR;
const runtimePython = process.env.RUNTIME_PYTHON;
if (!runtimeModules || !skillDir || !runtimePython) {
  throw new Error("Set RUNTIME_NODE_MODULES, PRESENTATION_SKILL_DIR, and RUNTIME_PYTHON from load_workspace_dependencies before building.");
}
const { Presentation, PresentationFile, registerPdfFontFace } = await import(
  pathToFileURL(path.join(runtimeModules, "@oai/artifact-tool/dist/artifact_tool.mjs")).href,
);
const logoPath = path.join(workspaceDir, "assets/samurai-logo/samurai-transparent.png");
const finalPptx = path.join(outputDir, "samurai-working-draft-local-evidence.pptx");
const finalPdf = path.join(outputDir, "samurai-working-draft-local-evidence.pdf");
const systemFonts = process.env.PRESENTATION_FONT_DIR ?? "/System/Library/Fonts/Supplemental";

const color = {
  ink: "#0C1B33",
  muted: "#526174",
  paper: "#F8F7F2",
  white: "#FFFFFF",
  navy: "#10213B",
  teal: "#1AA6A0",
  sky: "#D9F1EF",
  coral: "#F06D58",
  sand: "#EDE6D6",
  line: "#D6DCE3",
  faint: "#EFF3F5",
};

await Promise.all([
  registerPdfFontFace({ family: "Arial", weight: 400, style: "normal", source: await fs.readFile(path.join(systemFonts, "Arial.ttf")) }),
  registerPdfFontFace({ family: "Arial", weight: 700, style: "normal", source: await fs.readFile(path.join(systemFonts, "Arial Bold.ttf")) }),
  registerPdfFontFace({ family: "Arial", weight: 400, style: "italic", source: await fs.readFile(path.join(systemFonts, "Arial Italic.ttf")) }),
]);

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

async function saveBlob(targetPath, blob) {
  await fs.writeFile(targetPath, new Uint8Array(await blob.arrayBuffer()));
}

function shape(slide, geometry, position, fill, line = "none", name) {
  return slide.shapes.add({
    geometry,
    name,
    position,
    fill,
    line: { style: "solid", fill: line, width: line === "none" ? 0 : 1 },
    borderRadius: geometry === "roundRect" ? "rounded-xl" : undefined,
  });
}

function text(slide, value, position, options = {}) {
  const box = shape(slide, "textbox", position, "none", "none", options.name);
  box.text = value;
  box.text.style = {
    typeface: "Arial",
    fontSize: options.size ?? 20,
    color: options.color ?? color.ink,
    bold: options.bold ?? false,
    italic: options.italic ?? false,
    align: options.align ?? "left",
    verticalAlignment: options.verticalAlignment ?? "top",
  };
  return box;
}

function chrome(slide, number, label = "SAMURAI") {
  text(slide, "WORKING DRAFT  •  LOCAL EVIDENCE", { left: 70, top: 40, width: 380, height: 20 }, { size: 11, bold: true, color: color.teal });
  text(slide, label, { left: 1040, top: 40, width: 150, height: 20 }, { size: 11, bold: true, color: color.muted, align: "right" });
  shape(slide, "rect", { left: 70, top: 665, width: 1140, height: 1 }, color.line);
  text(slide, String(number).padStart(2, "0"), { left: 1140, top: 676, width: 70, height: 18 }, { size: 10, bold: true, color: color.muted, align: "right" });
}

function title(slide, heading, deckNumber, kicker) {
  chrome(slide, deckNumber);
  text(slide, kicker, { left: 70, top: 92, width: 650, height: 20 }, { size: 12, bold: true, color: color.coral });
  text(slide, heading, { left: 70, top: 126, width: 1120, height: 96 }, { size: 39, bold: true, color: color.ink });
}

function card(slide, position, options = {}) {
  return shape(slide, "roundRect", position, options.fill ?? color.white, options.line ?? color.line, options.name);
}

function divider(slide, left, top, width) {
  shape(slide, "rect", { left, top, width, height: 1 }, color.line);
}

function addNotes(slide, lines) {
  slide.speakerNotes.text = lines.join("\n");
  slide.speakerNotes.setVisible(true);
}

// 1. Cover
{
  const slide = deck.slides.add();
  slide.background.fill = color.navy;
  const logoBytes = await fs.readFile(logoPath);
  slide.images.add({
    blob: logoBytes.buffer.slice(logoBytes.byteOffset, logoBytes.byteOffset + logoBytes.byteLength),
    contentType: "image/png",
    alt: "Samurai logo",
    fit: "contain",
    position: { left: 72, top: 56, width: 84, height: 84 },
  });
  text(slide, "SAMURAI", { left: 172, top: 80, width: 210, height: 28 }, { size: 17, bold: true, color: color.white });
  text(slide, "Future of Work", { left: 75, top: 190, width: 860, height: 68 }, { size: 55, bold: true, color: color.white });
  text(slide, "One founder workspace for company-building work that keeps evidence, decisions, and artifacts connected.", { left: 75, top: 286, width: 710, height: 82 }, { size: 24, color: "#DDE8F3" });
  card(slide, { left: 75, top: 505, width: 400, height: 72 }, { fill: "#1E3656", line: "#365275" });
  text(slide, "WORKING DRAFT  •  LOCAL EVIDENCE", { left: 99, top: 527, width: 350, height: 24 }, { size: 13, bold: true, color: "#A8E5DF" });
  text(slide, "Editable PPTX + rendered PDF\nTemplate matching remains pending", { left: 850, top: 530, width: 350, height: 58 }, { size: 15, color: "#B9C8D8", align: "right" });
  addNotes(slide, [
    "Claim boundary: This is a local draft, not a final submission or template-matched asset.",
    "Evidence: docs/competition/demo-script.md (2026-10-13 public requirements basis and inaccessible template note).",
    "Asset: assets/samurai-logo/samurai-transparent.png, checked as a local brand asset.",
  ]);
}

// 2. Problem and founder journey
{
  const slide = deck.slides.add();
  slide.background.fill = color.paper;
  title(slide, "Founders need one place to turn an idea into accountable work.", 2, "THE PROBLEM");
  text(slide, "Illustrative founder input", { left: 70, top: 255, width: 260, height: 22 }, { size: 13, bold: true, color: color.muted });
  card(slide, { left: 70, top: 292, width: 330, height: 210 }, { fill: color.navy, line: color.navy });
  text(slide, "“Build my business:\nan AI receptionist for Indian dental clinics.”", { left: 98, top: 330, width: 275, height: 110 }, { size: 23, bold: true, color: color.white });
  text(slide, "A founder statement, not market proof.", { left: 98, top: 458, width: 260, height: 30 }, { size: 14, color: "#C6D4E1" });
  const steps = [
    ["1", "Keep the context", "idea, unknowns, next decision"],
    ["2", "Separate evidence", "facts, assumptions, measured outcomes"],
    ["3", "Ask for approval", "before consequential work advances"],
  ];
  steps.forEach(([n, head, body], index) => {
    const left = 455 + index * 245;
    card(slide, { left, top: 292, width: 215, height: 210 }, { fill: color.white });
    text(slide, n, { left: left + 24, top: 318, width: 35, height: 36 }, { size: 28, bold: true, color: color.teal });
    text(slide, head, { left: left + 24, top: 374, width: 165, height: 50 }, { size: 19, bold: true });
    text(slide, body, { left: left + 24, top: 442, width: 165, height: 48 }, { size: 14, color: color.muted });
  });
  text(slide, "The local draft shows a product direction, not a claim of customer validation, demand, pricing, revenue, or traction.", { left: 70, top: 550, width: 1040, height: 36 }, { size: 16, color: color.muted });
  addNotes(slide, [
    "Illustrative founder journey only. No clinic-market, pricing, customer, revenue, or traction claim.",
    "Evidence: docs/competition/demo-script.md, storyboard 0:00–0:35; docs/competition/solution-description.md.",
  ]);
}

// 3. Workflow
{
  const slide = deck.slides.add();
  slide.background.fill = color.paper;
  title(slide, "Samurai organizes one workflow around a founder’s decisions.", 3, "THE PRODUCT");
  const nodes = [
    ["Founder context", "What the founder said\nand what is still unknown", color.navy, color.white],
    ["Evidence gate", "Sources, support status,\nand visible conflicts", color.sky, color.ink],
    ["Founder approval", "A bounded decision\nbefore work moves on", color.sand, color.ink],
    ["Connected work", "Research, strategy, and\nexecution retain lineage", color.teal, color.white],
  ];
  nodes.forEach(([head, body, fill, textColor], index) => {
    const left = 70 + index * 285;
    card(slide, { left, top: 300, width: 230, height: 192 }, { fill, line: fill });
    text(slide, head, { left: left + 24, top: 334, width: 182, height: 52 }, { size: 21, bold: true, color: textColor });
    text(slide, body, { left: left + 24, top: 414, width: 182, height: 52 }, { size: 15, color: textColor });
    if (index < nodes.length - 1) {
      text(slide, "→", { left: left + 238, top: 374, width: 38, height: 38 }, { size: 28, bold: true, color: color.coral, align: "center" });
    }
  });
  text(slide, "The diagram is editable and describes intended workflow behavior. It does not represent a new captured user session.", { left: 70, top: 550, width: 1060, height: 32 }, { size: 16, color: color.muted });
  addNotes(slide, [
    "Editable diagram. It communicates the product contract, not a screenshot or a claim of a live end-to-end run.",
    "Evidence: AGENTS.md, 'Chosen product' and 'Proposed agent responsibilities'; docs/architecture.md sections 'Product boundary' and 'Agent boundaries'.",
  ]);
}

// 4. Gemini / Google distinction
{
  const slide = deck.slides.add();
  slide.background.fill = color.paper;
  title(slide, "Gemini is part of the reasoning design; evidence status depends on the exact environment.", 4, "GENAI IMPLEMENTATION");
  card(slide, { left: 70, top: 272, width: 525, height: 252 }, { fill: color.white });
  text(slide, "Historical deployed evidence", { left: 104, top: 309, width: 320, height: 30 }, { size: 20, bold: true, color: color.navy });
  divider(slide, 104, 356, 420);
  text(slide, "A prior Cloud Run/IAP acceptance recorded a bounded Gemini-backed brief and reload at its recorded revision.", { left: 104, top: 385, width: 400, height: 72 }, { size: 18, color: color.ink });
  text(slide, "Historical evidence only. It does not say this local draft is deployed.", { left: 104, top: 474, width: 400, height: 30 }, { size: 14, bold: true, color: color.coral });
  card(slide, { left: 655, top: 272, width: 555, height: 252 }, { fill: color.navy, line: color.navy });
  text(slide, "Current local evidence", { left: 691, top: 309, width: 320, height: 30 }, { size: 20, bold: true, color: color.white });
  divider(slide, 691, 356, 440);
  text(slide, "Provider-free acceptance covers recovery, UI terminal states, and readiness boundaries without a new provider call.", { left: 691, top: 385, width: 430, height: 72 }, { size: 18, color: color.white });
  text(slide, "Current cloud queue, current Gemini use, and paid upgrade remain deferred.", { left: 691, top: 474, width: 440, height: 30 }, { size: 14, bold: true, color: "#A8E5DF" });
  addNotes(slide, [
    "Historical deployed evidence: docs/gcp-deployment.md lines 261–282 describes a prior IAP sign-in, fictional dental-receptionist brief, reload, and named source revisions.",
    "Current local evidence: task-10 commit 76c9884763198af480c2bd96c959d7d8ff104356 and task-10/DoneClaim.md say provider-free local acceptance only.",
    "Current cloud-resumability and current Gemini/provider acceptance are not claimed. Paid upgrade remains deferred.",
  ]);
}

// 5. Verifier
{
  const slide = deck.slides.add();
  slide.background.fill = color.paper;
  title(slide, "The verifier keeps unsupported claims visible instead of decorating a pitch.", 5, "RELIABILITY OF THE WORKFLOW");
  card(slide, { left: 70, top: 275, width: 385, height: 255 }, { fill: color.white });
  text(slide, "Founder statement", { left: 102, top: 315, width: 240, height: 26 }, { size: 18, bold: true, color: color.navy });
  text(slide, "“Clinics need this service.”", { left: 102, top: 359, width: 270, height: 34 }, { size: 21, italic: true, color: color.ink });
  text(slide, "Recorded as input, not promoted to fact.", { left: 102, top: 420, width: 260, height: 46 }, { size: 16, color: color.muted });
  card(slide, { left: 500, top: 275, width: 325, height: 255 }, { fill: color.sky, line: color.sky });
  text(slide, "Verifier", { left: 532, top: 315, width: 200, height: 26 }, { size: 18, bold: true, color: color.navy });
  text(slide, "Support missing", { left: 532, top: 367, width: 240, height: 42 }, { size: 28, bold: true, color: color.coral });
  text(slide, "The claim stays unresolved until sources actually support it.", { left: 532, top: 432, width: 235, height: 50 }, { size: 16, color: color.ink });
  card(slide, { left: 870, top: 275, width: 340, height: 255 }, { fill: color.navy, line: color.navy });
  text(slide, "Founder decision", { left: 902, top: 315, width: 240, height: 26 }, { size: 18, bold: true, color: color.white });
  text(slide, "Collect source support before strategy.", { left: 902, top: 367, width: 250, height: 66 }, { size: 23, bold: true, color: color.white });
  text(slide, "The next step stays bounded and reviewable.", { left: 902, top: 456, width: 250, height: 28 }, { size: 15, color: "#C6D4E1" });
  addNotes(slide, [
    "This is an illustrative control-flow example, not a live source assessment.",
    "Evidence: docs/competition/demo-script.md, storyboard 0:35–1:35; docs/competition/source-support.md; docs/competition/source-support.json is intentionally empty.",
    "No competitor, demand, price, or market claim appears on this slide.",
  ]);
}

// 6. Local proof
{
  const slide = deck.slides.add();
  slide.background.fill = color.paper;
  title(slide, "Local acceptance gives the draft a reliability baseline, with clear limits.", 6, "WHAT HAS BEEN VERIFIED LOCALLY");
  const proof = [
    ["Durable recovery", "201f0f7\nformatted aa07b46", "Native queue recovery and cancellation passed locally."],
    ["Founder UI", "1a4c6a9", "Terminal cancellation and exhaustion states passed locally."],
    ["Readiness runner", "76c9884", "Provider-free boundary journey passed locally."],
    ["Local onboarding", "1f841e7", "Provider-free setup/CI wiring was locally accepted."],
  ];
  proof.forEach(([head, sha, body], index) => {
    const left = 70 + index * 285;
    card(slide, { left, top: 280, width: 255, height: 225 }, { fill: index % 2 ? color.white : color.faint });
    text(slide, head, { left: left + 22, top: 310, width: 210, height: 48 }, { size: 19, bold: true, color: color.navy });
    text(slide, sha, { left: left + 22, top: 373, width: 210, height: 43 }, { size: 16, bold: true, color: color.teal });
    text(slide, body, { left: left + 22, top: 437, width: 210, height: 52 }, { size: 14, color: color.muted });
  });
  text(slide, "Founder schema c4a6e70 is locally accepted. Shared-workspaces runtime, current cloud recovery, live second-account isolation, and paid upgrade are not complete.", { left: 70, top: 550, width: 1090, height: 42 }, { size: 16, color: color.muted });
  addNotes(slide, [
    "Task 6: .omo/evidence/readiness/task-6/independent-verification.md, implementation 201f0f7... plus format-only aa07b46....",
    "Task 7: local terminal UI acceptance; caller-supplied binding 1a4c6a9. Task 10: .omo/evidence/readiness/task-10/DoneClaim.md, 76c9884.... Task 9: docs/architecture.md, 1f841e7 local acceptance.",
    "Founder schema c4a6e70 and incomplete shared-workspaces runtime are caller-provided acceptance boundary. Live second Google-account isolation was skipped; docs/gcp-deployment.md line 279 records that gap.",
  ]);
}

// 7. Next steps
{
  const slide = deck.slides.add();
  slide.background.fill = color.navy;
  text(slide, "WORKING DRAFT  •  LOCAL EVIDENCE", { left: 70, top: 46, width: 370, height: 20 }, { size: 11, bold: true, color: "#A8E5DF" });
  text(slide, "This draft has a useful role.\nIt is not Task 14 complete.", { left: 70, top: 114, width: 760, height: 112 }, { size: 42, bold: true, color: color.white });
  const next = [
    ["1", "Portal and template", "Confirm the actual template, category choice, team status, and fields through an authorized account."],
    ["2", "Candidate evidence", "Bind current cloud, Gemini, recovery, and source-support evidence to the exact submission revision."],
    ["3", "Public package", "Create and review the video, public links, evaluator access arrangement, and final submission receipt."],
  ];
  next.forEach(([n, head, body], index) => {
    const top = 300 + index * 95;
    text(slide, n, { left: 78, top, width: 32, height: 32 }, { size: 22, bold: true, color: color.coral });
    text(slide, head, { left: 135, top: top + 2, width: 260, height: 28 }, { size: 20, bold: true, color: color.white });
    text(slide, body, { left: 410, top: top + 2, width: 690, height: 48 }, { size: 16, color: "#D5E0EA" });
  });
  text(slide, "Local outputs today: editable PPTX, rendered PDF, slide previews, speaker-note evidence map, and review receipt.", { left: 70, top: 616, width: 1040, height: 30 }, { size: 16, color: "#A8E5DF" });
  addNotes(slide, [
    "Current status: this is a prepared local draft, not final Task 14 completion.",
    "Required future evidence: docs/competition/demo-script.md 'Current acceptance boundary'; .omo/plans/samurai-production-competition-readiness.md Task 14.",
    "Template URL was inaccessible during a bounded read-only check. No portal, cloud, account, publication, or provider mutation occurred for this deck.",
  ]);
}

// Rebuild only task-generated outputs so the documented command can run repeatedly.
await fs.rm(buildDir, { recursive: true, force: true });
await fs.mkdir(buildDir, { recursive: true });
await fs.mkdir(outputDir, { recursive: true });
await fs.rm(finalPptx, { force: true });
await fs.rm(finalPdf, { force: true });
for (const [index, slide] of deck.slides.items.entries()) {
  await saveBlob(path.join(buildDir, `slide-${String(index + 1).padStart(2, "0")}.png`), await deck.export({ slide, format: "png", scale: 2 }));
}
await saveBlob(path.join(buildDir, "deck-montage.webp"), await deck.export({ format: "webp", montage: true }));
await saveBlob(finalPdf, await deck.export({ format: "pdf" }));

const { finalizePresentation } = await import(pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href);
const candidatePath = path.join(buildDir, "candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidatePath);
const result = await finalizePresentation({
  explicitTotalSlideCount: 7,
  requiredNativeTableOwnerSlides: [],
  workspaceDir,
  candidatePath,
  finalPath: finalPptx,
  pythonExecutable: runtimePython,
  integrityValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-bullet-geometry", "--validate-heading-fit"],
  fontPolicy: { basis: "design", families: ["Arial"] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(buildDir, "pptx-validation.json"),
});
await fs.writeFile(path.join(buildDir, "finalizer-result.json"), `${JSON.stringify(result, null, 2)}\n`);
const inspection = await deck.inspect({ kind: "slide,textbox,shape,image,notes", maxChars: 50000 });
await fs.writeFile(path.join(buildDir, "deck-inspection.ndjson"), inspection.ndjson);
