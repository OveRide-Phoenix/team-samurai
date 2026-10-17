import type { Panel, Workspace } from './model';
import { companyBriefSchema, type CompanyBrief } from './model';

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
export const initialWorkspace: Workspace = { actions: [], nextAction: null, selectedArea: 'overview', aspectChecks: {}, drafts: {},
  executionMode: 'live', activityLog: [],
  version: 1, theme: 'sky', pinned: [offer], completedTasks: [], panelOrder: [], shortlist: [], approvedOffers: [],
  messages: [
    { id: 'intro-user', role: 'user', text: 'I want to build an AI receptionist for Indian dental clinics.' },
    { id: 'intro-assistant', role: 'assistant', text: 'Let’s start with the business. Who needs this most, what would they pay for, and how do we reach our first customer?' },
    { id: 'intro-offer', role: 'assistant', text: 'Here’s a first offer to explore. The next step is to test it with clinic owners.', panel: offer },
  ],
};

export function briefFixture(input: CompanyBrief): Extract<Panel, { kind: 'evidence' }> {
  const brief = companyBriefSchema.parse(input);
  const fields = [['Idea', brief.idea], ['First customers', brief.customer], ['Market', brief.location], ['Budget', brief.budget], ['Founder skills', brief.founderSkills], ['First milestone', brief.goal]];
  return { id: 'test-company-brief', kind: 'evidence', title: 'Company brief', note: '', claims: fields.flatMap(([label, value], index) => value ? [{ id: `brief-${index}`, claim: `${label}: ${value}`, status: 'hypothesis', detail: 'Founder supplied context, not market evidence', sources: [] }] : []) };
}
