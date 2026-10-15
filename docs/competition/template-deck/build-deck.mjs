import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [source, screenshot, output] = process.argv.slice(2);
const modules = process.env.RUNTIME_NODE_MODULES;
if (!source || !screenshot || !output || !modules) throw new Error('Usage: RUNTIME_NODE_MODULES=... node build-deck.mjs source.pptx screenshot.png output-directory');
const {PresentationFile, FileBlob, registerPdfFontFace} = await import(pathToFileURL(path.join(modules,'@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const deck = await PresentationFile.importPptx(await FileBlob.load(source));
if (deck.slides.items.length !== 16) throw new Error('Expected the inspected 16-slide template.');
const inspected = await deck.inspect({kind:'textbox',maxChars:120000});
const bodyFont = 'Google Sans Flex Medium';
const fontRoot = process.env.PRESENTATION_FONT_DIR ?? '/System/Library/Fonts/Supplemental';
await registerPdfFontFace({family:'Arial',weight:400,style:'normal',source:await fs.readFile(path.join(fontRoot,'Arial.ttf'))});
await fs.mkdir(output,{recursive:true});
function text(index, value, y=150, height=300, size=23) {
 const shape=deck.slides.items[index].shapes.add({geometry:'textbox',position:{left:40,top:y,width:880,height},fill:'none',line:{fill:'none',width:0}});
 shape.text=value;shape.text.style={typeface:bodyFont,fontSize:size,color:'#000000',verticalAlignment:'top'};
}
function replace(index,value) {
 const item=inspected.records.find(x=>x.kind==='textbox' && x.slideIndex===index);
 if (!item) throw new Error(`Missing template textbox on slide ${index+1}`);
 deck.resolve(item.id).text=value;
}
replace(0,'Team Details\n\nTeam name: Samurai\nTeam leader: pending portal confirmation\nProblem: founder work loses context and evidence');
text(0,'DRAFT • Future of Work & Enterprise Productivity • Local evidence',480,35,18);
text(2,'One founder workspace for turning an idea into research, a reviewable offer, and a delivery plan.\n\nSamurai retains company context, sources, decisions, and artifacts across stages.\n\nThe founder reviews the next decision. Missing or conflicting evidence remains visible.',150,320,25);
replace(3,'Opportunities');
text(3,'A connected workflow: specialists share revisioned company context instead of producing isolated answers.\n\nEvidence before confidence: source adjudication checks cited content; unsupported claims stay unverified.\n\nFounder control: accepted stages persist, and consequential external actions require approval.',150,330,24);
text(4,'Locally accepted\nWorkspace membership • company revision fencing • quotas and files\nFounder context • offer diagnostics • scoped knowledge\nExplicit learning • bounded schedules • synthetic scenarios\n\nReliability\nOne automatic retry • duplicate-write protection • cancellation\n\nThese local results do not establish current cloud deployment.',140,340,23);
text(5,'Founder brief  →  Research  →  Source adjudication\n                                      ↓\n                     Verifier and founder decision\n                         ↓                    ↓\n               Evidence sufficient     Missing / conflicting\n                         ↓                    ↓\n                Strategy and plan       Rework / clarify',145,300,25);
text(5,'Accepted stages and their provenance persist; interrupted work resumes under revision and attempt fences.',455,55,20);
text(6,'The implemented founder workspace is shown on slide 11.\n\nIt combines conversation, company context, and typed business panels. Views distinguish assumptions, supported claims, and synthetic calculations.\n\nThis draft uses an accepted local fixture capture, not a live customer or cloud demonstration.',160,290,25);
text(7,'Founder UI (React/Vite)\n                  ↓\nServer proxy: identity and allowlisted routes\n                  ↓\nAgno AgentOS: parent + explicit workflows + verifier\n          ↓                         ↓\nPostgreSQL                 Gemini reasoning\ncompany state, jobs         Researcher-only Search\n\nAgno ↔ Redis: events and cancellation',135,325,23);
text(7,'Local files today. Shared cloud coordination rollout is deferred; Cloud Storage is a future adapter.',470,45,19);
text(8,'Python + Agno AgentOS: explicit staged workflows and persistence\nGemini: bounded reasoning; native Search for Researcher only\nPostgreSQL: canonical company state, artifacts, and durable jobs\nRedis: local coordination for recovery and cancellation\nReact/Vite + TypeScript: typed founder views and server proxy\n\nHistorical Google deployment: Cloud Run, Cloud SQL, and IAP.\nThe current local candidate has not been deployed.',145,340,23);
text(9,'Cost controls\nBounded attempts, company admission, quotas, and test fixtures\nProvider-free local acceptance; no new Gemini spend in these checks\n\nPaid cloud recovery upgrade: deferred by the founder\nCurrent spend and an approved recurring budget: not established\n\nHosting estimates require a refreshed inventory and authorization.\nNo claim of zero-cost hosting or a guaranteed spending cap.',150,330,23);
const bytes=await fs.readFile(screenshot);
deck.slides.items[10].images.add({blob:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),contentType:'image/png',alt:'Local synthetic scenario form from accepted Task 20 browser QA',fit:'contain',position:{left:170,top:130,width:620,height:365}});
text(10,'Accepted Task 20 local fixture capture; visible “Live” is the UI mode, not cloud deployment or real business data.',500,26,15);
text(11,'Correctness checks at the accepted local production tree\n554 backend tests • 150 frontend tests\n60 server tests • 4 Sites tests • 40 provider-free evaluations\n\nObserved recovery\nOne scheduled result; no duplicate receipt on replay\nStable company and result hashes after backend restart and reload\n\nLatency, throughput, cost per task, and business impact: unmeasured.',145,350,24);
text(12,'Before a production-readiness claim\nComplete final integrated manual QA and local integration\nAuthorize and verify cloud queue rollout and isolated restore drill\nRun bounded live source-supported business acceptance\n\nFuture work\nCloud Storage adapter and connected business measurements\n\nNo outreach, publishing, spending, or demand validation is implied.',150,340,23);
replace(13,'Prototype and submission links');
text(13,'Repository: OveRide-Phoenix/team-samurai\nPublic visibility and final all-ref review: pending authorization\n\nDemo video: not yet recorded or published\n\nProduct: restricted Google sign-in; evaluator access pending\nCurrent deployment revision and public links require verification\n\nDRAFT — not ready to submit',145,340,24);
for (const [index,slide] of deck.slides.items.entries()) {
 slide.speakerNotes.text=`Draft for Future of Work & Enterprise Productivity. Source template: https://docs.google.com/presentation/d/13rg7vW43mEH6DkpuusAE6fdoEylSFz8waNpE4RLzoUg/edit (download 2026-10-16, SHA256 fac56448966ecac0bea3975b7c9c61bf578679ccf4bd252a5f281ed4db90ce77). Local implementation evidence: docs/local-acceptance.md; production/test commit 7b731d6942e113e671d5ce0110d694deea19193e; acceptance docs da69bbfa6fef32abb01d789efde21eed4f550782. See docs/architecture.md, docs/readiness-costs.md, docs/gcp-deployment.md, docs/competition/template-checklist.md. Slide ${index+1}. No cloud/provider/publication/submission acceptance implied. Slide 11 image: accepted Task20 browser-fix.png, synthetic local data; source tree continuity documented in Task20 acceptance receipt.`;
 const blob=await deck.export({slide,format:'png',scale:1});
 await fs.writeFile(path.join(output,`slide-${String(index+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
}
await (await PresentationFile.exportPptx(deck)).save(path.join(output,'samurai-template-draft.pptx'));
const pdf=await deck.export({format:'pdf'});
await fs.writeFile(path.join(output,'samurai-template-draft.pdf'),new Uint8Array(await pdf.arrayBuffer()));
await fs.writeFile(path.join(output,'inspection.json'),JSON.stringify(await deck.inspect({kind:'slide,textbox,image',maxChars:150000}),null,2));
console.log(JSON.stringify({slides:deck.slides.items.length,output,status:'draft_requires_visual_review'}));
