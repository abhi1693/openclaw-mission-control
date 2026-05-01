export type AgentStatus = "active" | "idle" | "review" | "blocked" | "offline";

export type SimpleProAgent = {
  id: string;
  name: string;
  role: string;
  initials: string;
  accent: string;
  platform: string;
  model: string;
  currentTask: string;
  status: AgentStatus;
  progress: number;
  lastActivity: string;
};

export const SIMPLE_PRO_AGENTS: SimpleProAgent[] = [
  {
    id: "openclaw-coordinator",
    name: "OpenClaw Coordinator",
    role: "Orchestrator",
    initials: "OC",
    accent: "from-indigo-500 to-violet-500",
    platform: "OpenClaw",
    model: "claude-opus-4-7",
    currentTask: "Routing Belle voice intents to scheduler",
    status: "active",
    progress: 72,
    lastActivity: "2m ago",
  },
  {
    id: "claude-code-cto",
    name: "Claude Code CTO",
    role: "Architect / CTO",
    initials: "CC",
    accent: "from-amber-500 to-orange-500",
    platform: "Claude Code",
    model: "claude-opus-4-7",
    currentTask: "Reviewing payments retry policy for late invoices",
    status: "review",
    progress: 58,
    lastActivity: "6m ago",
  },
  {
    id: "codex-builder",
    name: "Codex Builder",
    role: "Senior Engineer",
    initials: "CB",
    accent: "from-emerald-500 to-teal-500",
    platform: "OpenAI Codex",
    model: "gpt-5.1-codex",
    currentTask: "Implementing technician photo diagnosis upload flow",
    status: "active",
    progress: 84,
    lastActivity: "just now",
  },
  {
    id: "hermes-qa",
    name: "Hermes QA",
    role: "QA / Test Pilot",
    initials: "HQ",
    accent: "from-sky-500 to-blue-500",
    platform: "Hermes",
    model: "claude-sonnet-4-6",
    currentTask: "End-to-end test: estimate → invoice → Stripe collect",
    status: "active",
    progress: 41,
    lastActivity: "1m ago",
  },
  {
    id: "devops-agent",
    name: "DevOps Agent",
    role: "Platform / Infra",
    initials: "DO",
    accent: "from-slate-500 to-slate-700",
    platform: "Internal",
    model: "claude-sonnet-4-6",
    currentTask: "Promoting Belle voice gateway to canary",
    status: "idle",
    progress: 100,
    lastActivity: "14m ago",
  },
  {
    id: "product-design-agent",
    name: "Product / Design Agent",
    role: "Product & UX",
    initials: "PD",
    accent: "from-pink-500 to-rose-500",
    platform: "Figma + Claude",
    model: "claude-opus-4-7",
    currentTask: "Refining technician daily-route mobile screens",
    status: "active",
    progress: 63,
    lastActivity: "9m ago",
  },
  {
    id: "belle-product-assistant",
    name: "Belle Product Assistant",
    role: "Product Companion",
    initials: "BL",
    accent: "from-fuchsia-500 to-purple-500",
    platform: "Belle",
    model: "claude-opus-4-7",
    currentTask: "Drafting follow-up scripts for late-payment customers",
    status: "active",
    progress: 49,
    lastActivity: "30s ago",
  },
];

export type PipelineColumn = {
  id: "backlog" | "in-progress" | "review" | "done";
  title: string;
  accent: string;
  cards: PipelineCard[];
};

export type PipelineCard = {
  id: string;
  title: string;
  owner: string;
  ownerAccent: string;
  tag: string;
  tagTone: "blue" | "violet" | "emerald" | "amber" | "rose" | "slate";
  meta: string;
};

export const TASK_PIPELINE: PipelineColumn[] = [
  {
    id: "backlog",
    title: "Backlog",
    accent: "bg-slate-400",
    cards: [
      {
        id: "bk-1",
        title: "Receipt OCR — multi-page PDF support",
        owner: "Codex Builder",
        ownerAccent: "from-emerald-500 to-teal-500",
        tag: "Belle",
        tagTone: "violet",
        meta: "Receipts · 3 pts",
      },
      {
        id: "bk-2",
        title: "Tech app — offline job notes sync",
        owner: "Product / Design",
        ownerAccent: "from-pink-500 to-rose-500",
        tag: "Mobile",
        tagTone: "blue",
        meta: "Field Ops · 5 pts",
      },
      {
        id: "bk-3",
        title: "QuickBooks payout reconciliation v2",
        owner: "Claude Code CTO",
        ownerAccent: "from-amber-500 to-orange-500",
        tag: "Payments",
        tagTone: "amber",
        meta: "Billing · 8 pts",
      },
    ],
  },
  {
    id: "in-progress",
    title: "In Progress",
    accent: "bg-blue-500",
    cards: [
      {
        id: "ip-1",
        title: "Belle voice → schedule appointment intent",
        owner: "OpenClaw Coordinator",
        ownerAccent: "from-indigo-500 to-violet-500",
        tag: "Voice",
        tagTone: "violet",
        meta: "Belle · 5 pts",
      },
      {
        id: "ip-2",
        title: "Photo diagnosis: HVAC compressor classifier",
        owner: "Codex Builder",
        ownerAccent: "from-emerald-500 to-teal-500",
        tag: "AI",
        tagTone: "emerald",
        meta: "Diagnostics · 8 pts",
      },
      {
        id: "ip-3",
        title: "Late-payment follow-up cadence v3",
        owner: "Belle Assistant",
        ownerAccent: "from-fuchsia-500 to-purple-500",
        tag: "Payments",
        tagTone: "amber",
        meta: "Collections · 3 pts",
      },
    ],
  },
  {
    id: "review",
    title: "Review",
    accent: "bg-violet-500",
    cards: [
      {
        id: "rv-1",
        title: "Estimate PDF template — branded edition",
        owner: "Hermes QA",
        ownerAccent: "from-sky-500 to-blue-500",
        tag: "Estimates",
        tagTone: "blue",
        meta: "Awaiting CTO · 2 pts",
      },
      {
        id: "rv-2",
        title: "Stripe webhook idempotency hardening",
        owner: "Claude Code CTO",
        ownerAccent: "from-amber-500 to-orange-500",
        tag: "Payments",
        tagTone: "amber",
        meta: "Awaiting QA · 5 pts",
      },
    ],
  },
  {
    id: "done",
    title: "Done",
    accent: "bg-emerald-500",
    cards: [
      {
        id: "dn-1",
        title: "Inbound call routing for after-hours",
        owner: "OpenClaw Coordinator",
        ownerAccent: "from-indigo-500 to-violet-500",
        tag: "Voice",
        tagTone: "violet",
        meta: "Shipped · 3 pts",
      },
      {
        id: "dn-2",
        title: "Job task → invoice line items mapper",
        owner: "Codex Builder",
        ownerAccent: "from-emerald-500 to-teal-500",
        tag: "Billing",
        tagTone: "amber",
        meta: "Shipped · 5 pts",
      },
    ],
  },
];

export type BelleInsight = {
  id: string;
  title: string;
  detail: string;
  tone: "info" | "warning" | "success";
};

export const BELLE_INSIGHTS: BelleInsight[] = [
  {
    id: "insight-1",
    title: "Calls peaking 8–10 AM",
    detail:
      "Belle is handling 3.4× more inbound calls weekday mornings. Recommend pre-warming voice gateway capacity before 7:45 AM local.",
    tone: "info",
  },
  {
    id: "insight-2",
    title: "Late-invoice follow-ups recovering 38%",
    detail:
      "New cadence (day 3 / day 7 / day 14) recovered $12,480 across 27 customers this week. Suggest rolling out to plumbing accounts next.",
    tone: "success",
  },
  {
    id: "insight-3",
    title: "Photo diagnosis confidence dipped",
    detail:
      "HVAC compressor classifier confidence fell to 71% on rooftop units. Hermes QA is queuing labeled examples for retraining.",
    tone: "warning",
  },
  {
    id: "insight-4",
    title: "Receipts uploaded by techs +22%",
    detail:
      "Field techs uploaded 412 receipts this week — Codex Builder is shipping multi-page PDF support to keep latency under 2s.",
    tone: "info",
  },
];

export type RepoDeployment = {
  id: string;
  repo: string;
  branch: string;
  status: "deployed" | "deploying" | "failed" | "queued";
  env: string;
  lastDeploy: string;
  by: string;
};

export const REPOS_DEPLOYMENTS: RepoDeployment[] = [
  {
    id: "repo-1",
    repo: "simplepro/web-app",
    branch: "main",
    status: "deployed",
    env: "production",
    lastDeploy: "12m ago",
    by: "DevOps Agent",
  },
  {
    id: "repo-2",
    repo: "simplepro/belle-voice",
    branch: "feat/canary",
    status: "deploying",
    env: "canary",
    lastDeploy: "just now",
    by: "DevOps Agent",
  },
  {
    id: "repo-3",
    repo: "simplepro/tech-mobile",
    branch: "release/2026.05",
    status: "deployed",
    env: "staging",
    lastDeploy: "1h ago",
    by: "Codex Builder",
  },
  {
    id: "repo-4",
    repo: "simplepro/billing",
    branch: "fix/stripe-idempotency",
    status: "queued",
    env: "preview",
    lastDeploy: "—",
    by: "Claude Code CTO",
  },
];

export type ActivityItem = {
  id: string;
  agent: string;
  agentAccent: string;
  message: string;
  time: string;
  kind: "deploy" | "approval" | "code" | "voice" | "alert";
};

export const RECENT_ACTIVITY: ActivityItem[] = [
  {
    id: "act-1",
    agent: "DevOps Agent",
    agentAccent: "from-slate-500 to-slate-700",
    message: "Promoted belle-voice to canary (build #4821).",
    time: "30s ago",
    kind: "deploy",
  },
  {
    id: "act-2",
    agent: "Hermes QA",
    agentAccent: "from-sky-500 to-blue-500",
    message: "All 184 e2e checks passing on payments suite.",
    time: "3m ago",
    kind: "code",
  },
  {
    id: "act-3",
    agent: "Belle",
    agentAccent: "from-fuchsia-500 to-purple-500",
    message: "Booked appointment for Acme Plumbing — Tue 9:30 AM.",
    time: "6m ago",
    kind: "voice",
  },
  {
    id: "act-4",
    agent: "Claude Code CTO",
    agentAccent: "from-amber-500 to-orange-500",
    message: "Approved PR #312 — Stripe webhook idempotency.",
    time: "11m ago",
    kind: "approval",
  },
  {
    id: "act-5",
    agent: "Codex Builder",
    agentAccent: "from-emerald-500 to-teal-500",
    message: "Pushed compressor-classifier v0.4 (+1.2% accuracy).",
    time: "18m ago",
    kind: "code",
  },
  {
    id: "act-6",
    agent: "OpenClaw Coordinator",
    agentAccent: "from-indigo-500 to-violet-500",
    message: "Reassigned 2 tasks from idle DevOps queue.",
    time: "26m ago",
    kind: "alert",
  },
];

export type ApprovalItem = {
  id: string;
  title: string;
  agent: string;
  scope: string;
  risk: "low" | "medium" | "high";
  raised: string;
};

export const APPROVAL_QUEUE: ApprovalItem[] = [
  {
    id: "apv-1",
    title: "Promote belle-voice canary to 100% production",
    agent: "DevOps Agent",
    scope: "Production deploy",
    risk: "high",
    raised: "2m ago",
  },
  {
    id: "apv-2",
    title: "Auto-charge invoices > 30 days late (HVAC pilot)",
    agent: "Belle Assistant",
    scope: "Billing policy",
    risk: "medium",
    raised: "12m ago",
  },
  {
    id: "apv-3",
    title: "Enable photo-diagnosis recommendations in tech app",
    agent: "Product / Design",
    scope: "Feature flag",
    risk: "low",
    raised: "34m ago",
  },
  {
    id: "apv-4",
    title: "Update QuickBooks token rotation cadence to 30d",
    agent: "Claude Code CTO",
    scope: "Integration",
    risk: "low",
    raised: "1h ago",
  },
];
