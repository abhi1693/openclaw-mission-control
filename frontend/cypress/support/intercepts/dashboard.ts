const EMPTY_SERIES = {
  primary: { range: "7d", bucket: "day", points: [] },
  comparison: { range: "7d", bucket: "day", points: [] },
};

export function stubDashboard(apiBase: string): void {
  cy.intercept("GET", `${apiBase}/metrics/dashboard*`, {
    statusCode: 200,
    body: {
      generated_at: "2026-01-01T00:00:00.000Z",
      range: "7d",
      kpis: {
        inbox_tasks: 0,
        in_progress_tasks: 0,
        review_tasks: 0,
        done_tasks: 0,
        tasks_in_progress: 0,
        active_agents: 0,
        error_rate_pct: 0,
        median_cycle_time_hours_7d: null,
      },
      throughput: EMPTY_SERIES,
      cycle_time: EMPTY_SERIES,
      error_rate: EMPTY_SERIES,
      wip: EMPTY_SERIES,
      pending_approvals: { items: [], total: 0 },
    },
  }).as("dashboardMetrics");

  cy.intercept("GET", `${apiBase}/agents*`, {
    statusCode: 200,
    body: { items: [], total: 0 },
  }).as("agentsList");

  cy.intercept("GET", `${apiBase}/activity*`, {
    statusCode: 200,
    body: { items: [], total: 0 },
  }).as("activityList");

  cy.intercept("GET", `${apiBase}/gateways/status*`, {
    statusCode: 200,
    body: { gateways: [] },
  }).as("gatewaysStatus");
}
