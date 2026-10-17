import type { Panel, Transport, Workspace } from './model';
import { chooseWorkflow, companyBriefSchema, type CompanyBrief, type WorkEvent } from './model';

export const offer: Panel = {
  id: 'offer-v1', kind: 'offer', title: 'Your first offer', note: 'Draft hypothesis · needs customer validation',
  customer: 'Independent dental clinics in Bengaluru',
  promise: 'Turn missed calls into booked appointments, even after the clinic closes.',
  price: '₹4,999 / month',
  includes: ['Appointment booking and rescheduling', 'English + Hindi call handling', 'A daily summary for the clinic owner'],
};
export const prospects: Panel = {
  id: 'prospects-v1', kind: 'prospects', title: 'Find your first customers',
  note: 'Fictional demo clinics · no contact details researched',
  rows: [
    { id: 'p1', name: 'Maple Dental', area: 'Indiranagar', reason: 'Small team, evening appointment demand', fit: 'High' },
    { id: 'p2', name: 'Brightside Smiles', area: 'Koramangala', reason: 'Owner-managed clinic, limited front-desk cover', fit: 'High' },
    { id: 'p3', name: 'Parkside Dental', area: 'HSR Layout', reason: 'Growing practice with a shared receptionist', fit: 'Medium' },
    { id: 'p4', name: 'Little Oak Dentistry', area: 'Whitefield', reason: 'Family appointments outside working hours', fit: 'Medium' },
  ],
};
export const pricing: Panel = {
  id: 'pricing-v1', kind: 'pricing', title: 'A price worth testing', note: 'Illustrative options · not competitor research',
  options: [
    { name: 'Pilot', price: '₹2,499', description: 'A two-week trial to learn whether clinics value the service.' },
    { name: 'Essential', price: '₹4,999 / mo', description: 'Booking, rescheduling, and daily summaries for one clinic.' },
    { name: 'Growth', price: '₹7,999 / mo', description: 'Test demand for follow-ups and a second clinic location.' },
  ],
};
export const evidence: Panel = {
  id: 'evidence-v1', kind: 'evidence', title: 'What needs proving', note: 'Illustrative hypotheses · no live research or verified sources',
  claims: [
    { id: 'demand', claim: 'Missed calls are a costly problem', status: 'hypothesis', detail: 'Ask five clinic owners how many calls they miss and whether those callers book elsewhere.', sources: [] },
    { id: 'alternatives', claim: 'Existing tools may already solve this', status: 'needs-check', detail: 'Compare the clinic’s current receptionist, WhatsApp workflow, and booking software before shaping the offer.', sources: [] },
    { id: 'price', claim: 'The monthly price is still an assumption', status: 'hypothesis', detail: 'Test the sample ₹4,999 offer with owners; interest alone does not establish willingness to pay.', sources: [] },
  ],
};
export const launchPlan: Panel = {
  id: 'launch-v1', kind: 'launch-plan', title: 'Your first launch', note: 'Sample action plan · checkmarks track your local progress only',
  tasks: [
    { id: 'interviews', title: 'Speak to five clinic owners', owner: 'Founder', timing: 'Days 1–3', detail: 'Learn how missed calls are handled today. Record objections and existing alternatives.' },
    { id: 'offer-test', title: 'Test one clear offer', owner: 'Founder', timing: 'Days 4–7', detail: 'Show the promise and price. Look for a concrete pilot commitment.' },
    { id: 'pilot', title: 'Run a small pilot', owner: 'Founder', timing: 'Week 2', detail: 'Agree on success measures and delivery responsibilities before starting.' },
    { id: 'review', title: 'Review what changed', owner: 'Founder', timing: 'Week 3', detail: 'Use actual bookings and customer feedback to revise the offer.' },
  ],
};
export const initialWorkspace: Workspace = { actions: [], nextAction: null, selectedArea: 'overview', drafts: {},
  executionMode: 'preview', activityLog: [],
  version: 1, theme: 'sky', pinned: [offer], completedTasks: [], panelOrder: [], shortlist: [], approvedOffers: [],
  messages: [
    { id: 'intro-user', role: 'user', text: 'I want to build an AI receptionist for Indian dental clinics.' },
    { id: 'intro-assistant', role: 'assistant', text: 'Let’s start with the business. Who needs this most, what would they pay for, and how do we reach our first customer?' },
    { id: 'intro-offer', role: 'assistant', text: 'Here’s a first offer to explore. The next step is to test it with clinic owners.', panel: offer },
  ],
};

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException('Stopped', 'AbortError')); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, ms);
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, { once: true });
  });
}

// shortcut: deterministic fixtures exercise the UI; replace this transport with Kalyan's backend event stream.
export const demoTransport: Transport = async function* (input, signal, area = 'overview') {
  if (area !== 'overview') {
    const target = /pricing|price|offer|strategy|position|delivery|roadmap|launch plan/i.test(input) ? 'strategy' : /prospect|outreach|sales|sell to/i.test(input) ? 'sales' : /verification|verify|conflict/i.test(input) ? 'verification' : /research|competitor|market/i.test(input) ? 'research' : area;
    if (target !== area) {
      const names = { overview: 'Company', research: 'Researcher', strategy: 'Strategist', verification: 'Verifier', sales: 'Sales' };
      yield { type: 'message', text: 'This belongs with ' + names[target] + '. Switch there to continue.', handoff: target };
      return;
    }
  }
  let workflow = /^research our market/i.test(input) ? 'evidence' : chooseWorkflow(input);
  if (area === 'research' || area === 'verification') workflow = 'evidence';
  else if (area === 'sales') workflow = 'prospects';
  if (workflow === 'help' && area !== 'overview') {
    yield { type: 'message', text: 'Let’s stay with the goal for this team area. What would you like to investigate next?' };
    return;
  }
  if (workflow === 'help') {
    yield { type: 'message', text: 'This preview uses a dental receptionist business. Try “Find our first customers”, “Review our offer”, “Explore pricing”, “Validate assumptions”, or “Create a launch plan” to see its interactive views.' };
    return;
  }
  const agent = area === 'sales' ? 'Sales' : area === 'verification' ? 'Verifier' : workflow === 'prospects' || workflow === 'evidence' ? 'Researcher' : 'Strategist';
  yield { type: 'activity', agent, state: 'working', detail: workflow === 'prospects' ? 'Preparing the sample customer shortlist' : 'Preparing a sample business hypothesis' };
  await pause(1100, signal);
  yield { type: 'activity', agent, state: 'done', detail: 'Sample prepared' };
  yield { type: 'activity', agent: 'Verifier', state: 'working', detail: 'Checking the preview data structure' };
  await pause(900, signal);
  yield { type: 'activity', agent: 'Verifier', state: 'done', detail: 'Structure checked · market claims remain unverified' };
  if (workflow === 'evidence') {
    yield { type: 'message', text: 'These are the questions to test before committing to the business. This preview has not researched them.', panel: area === 'verification' ? verificationPreview : evidence };
  } else if (workflow === 'launch-plan') {
    yield { type: 'message', text: 'Work towards one paying pilot. Track the steps here as you complete them.', panel: launchPlan };
  } else if (workflow === 'prospects') {
    yield { type: 'message', text: 'Start with owner-managed clinics where missed calls could mean missed appointments. These fictional examples show how we’ll compare real prospects.', panel: prospects };
  } else if (workflow === 'offer') {
    yield { type: 'message', text: 'Lead with the outcome: fewer missed appointments. Review this draft, then test the promise with actual clinic owners.', panel: offer };
  } else {
    yield { type: 'message', text: 'Treat pricing as a hypothesis. Compare these sample options before asking clinic owners what they would pay.', panel: pricing };
  }
};

export function previewBrief(input: CompanyBrief): Extract<Panel, { kind: 'evidence' }> {
  const brief = companyBriefSchema.parse(input);
  const fields = [['Idea', brief.idea], ['First customers', brief.customer], ['Market', brief.location], ['Budget', brief.budget], ['Founder skills', brief.founderSkills], ['First milestone', brief.goal]];
  return { id: 'preview-company-brief', kind: 'evidence', title: 'Company brief', note: '', claims: fields.flatMap(([label, value], index) => value ? [{ id: `brief-${index}`, claim: `${label}: ${value}`, status: 'hypothesis', detail: 'Founder supplied context, not market evidence', sources: [] }] : []) };
}

// Preview follows the same brief-first boundary without making a provider call.
export async function* onboardingPreview(input: CompanyBrief, signal: AbortSignal): AsyncIterable<WorkEvent> {
  if (signal.aborted) return;
  yield { type: 'message', text: 'Your starting point is ready. Choose when to begin research.', panel: previewBrief(input) };
}


export const verificationPreview: Panel = {
  id: 'preview-verification', kind: 'evidence', title: 'Verification review',
  note: 'Illustrative checks only. No real market evidence has been verified.',
  claims: [
    { id: 'check-sources', claim: 'Source support is still needed', status: 'needs-check', detail: 'The sample research has no verified source support.', sources: [] },
    { id: 'check-price', claim: 'Pricing remains a hypothesis', status: 'hypothesis', detail: 'Willingness to pay needs customer evidence.', sources: [] },
    { id: 'check-demand', claim: 'Demand has not been measured', status: 'needs-check', detail: 'A clinic interview or pilot is the next real check.', sources: [] },
  ],
};
