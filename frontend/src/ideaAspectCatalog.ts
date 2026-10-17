import type { Agent, TeamArea, WorkflowArea } from './model';

type Checkpoint = { readonly id: string; readonly title: string; readonly question: string };
type Aspect = { readonly name: string; readonly shortName: string; readonly agent?: Agent; readonly goal: string; readonly prompt: string; readonly scope: TeamArea; readonly checkpoints: readonly Checkpoint[]; readonly related: readonly WorkflowArea[] };

export const aspectCatalog: Readonly<Record<WorkflowArea, Aspect>> = {
  research: {
    name: 'Problem & demand', shortName: 'Problem', agent: 'Researcher', scope: 'research',
    goal: 'Is this a real problem worth solving with software?',
    prompt: 'Help me validate the problem and demand for this software idea. Use existing context; separate evidence from assumptions. Suggest the smallest useful customer test.',
    related: ['market', 'sales'],
    checkpoints: [
      { id: 'customer-problem', title: 'Customer & problem', question: 'Who experiences this problem, how often, and what does it cost them?' },
      { id: 'demand-evidence', title: 'Evidence of demand', question: 'Which interviews, observations or sources support the problem? What remains assumed?' },
      { id: 'riskiest-assumption', title: 'Riskiest assumption', question: 'What must be true for this idea to work, and what is the cheapest way to test it?' },
    ],
  },
  market: {
    name: 'Market & alternatives', shortName: 'Market', agent: 'Researcher', scope: 'research',
    goal: 'What exists already, and where could this idea fit?',
    prompt: 'Help me explore existing software products, manual workarounds, market timing and differentiation for this idea. Use retained sources; label gaps rather than inventing market figures.',
    related: ['research', 'strategy'],
    checkpoints: [
      { id: 'existing-alternatives', title: 'Existing products', question: 'Which competitors, open-source products and manual workarounds already solve this?' },
      { id: 'market-opportunity', title: 'Market & timing', question: 'What is the reachable market and why now? Show the assumptions behind any estimate.' },
      { id: 'differentiation', title: 'A reason to switch', question: 'What gap would make a customer choose this software over their current alternative?' },
    ],
  },
  sales: {
    name: 'Sales & distribution', shortName: 'Sales', agent: 'Sales', scope: 'sales',
    goal: 'How will the right people find it and decide to pay?',
    prompt: 'Help me explore buyers, pricing willingness and distribution for this software idea, even if the technology is unresolved. Treat the offer as a hypothesis; do not send outreach.',
    related: ['research', 'resources'],
    checkpoints: [
      { id: 'first-buyers', title: 'First buyers', question: 'Who uses it, who pays for it, and where can we reach the first five potential buyers?' },
      { id: 'distribution', title: 'Channels & message', question: 'Which channel and short value proposition could reach these buyers? Keep outreach as drafts.' },
      { id: 'willingness-to-pay', title: 'Willingness to pay', question: 'What pricing hypothesis should we test, and what behavior would count as willingness to pay?' },
    ],
  },
  strategy: {
    name: 'Product & technology', shortName: 'Product', agent: 'Strategist', scope: 'strategy',
    goal: 'What is the smallest useful software solution, and can it work?',
    prompt: 'Help me explore the minimum software scope, requirements, technical feasibility and build-versus-buy choices. We can discuss hypotheses before research is complete; identify what needs testing.',
    related: ['market', 'resources', 'verification'],
    checkpoints: [
      { id: 'minimum-product', title: 'Minimum useful product', question: 'What one user journey must work? Which features can wait?' },
      { id: 'technical-feasibility', title: 'Technical requirements', question: 'Which architecture, APIs, integrations and technical skills are required? What needs a feasibility spike?' },
      { id: 'data-and-security', title: 'Data & quality', question: 'What data, privacy, accessibility, security and reliability requirements must the software meet?' },
    ],
  },
  resources: {
    name: 'Budget & resources', shortName: 'Budget', agent: 'Strategist', scope: 'strategy',
    goal: 'What will this take in money, time and people?',
    prompt: 'Help me estimate budget, skills, people, time and running costs for this software idea. Work with explicit ranges and assumptions even if technical choices or research are incomplete.',
    related: ['strategy', 'sales', 'verification'],
    checkpoints: [
      { id: 'build-budget', title: 'Build budget', question: 'What are the low/base/high build estimates, available budget and contingency? State currency and assumptions.' },
      { id: 'skills-and-team', title: 'Skills & capacity', question: 'What can I build myself, what expertise is missing, and how many hours can we commit?' },
      { id: 'running-costs', title: 'Running costs', question: 'What recurring hosting, API, support and acquisition costs affect runway and break-even?' },
    ],
  },
  verification: {
    name: 'Validation & delivery', shortName: 'Delivery', agent: 'Verifier', scope: 'verification',
    goal: 'What should we test or implement next, and how will we know it worked?',
    prompt: 'Help me review the software idea, design a small experiment and plan implementation milestones. Distinguish an experiment, a draft plan, working software and measured outcomes.',
    related: ['research', 'strategy', 'resources'],
    checkpoints: [
      { id: 'validation-experiment', title: 'Experiment & decision', question: 'What is the next experiment, its success threshold, and the criteria to proceed, revise or stop?' },
      { id: 'implementation-roadmap', title: 'Implementation plan', question: 'What are the smallest implementation milestones, owners, acceptance checks and dependencies?' },
      { id: 'release-and-learning', title: 'Test, release & learn', question: 'What must be tested before a pilot, and which real feedback or measurements will guide the next iteration?' },
    ],
  },
};
