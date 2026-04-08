const EMPTY_SSE = {
  statusCode: 200,
  headers: { "content-type": "text/event-stream" },
  body: "",
};

export function stubEmptySSEStreams(apiBase: string): void {
  cy.intercept("GET", `${apiBase}/boards/*/tasks/stream*`, EMPTY_SSE).as("tasksStream");
  cy.intercept("GET", `${apiBase}/boards/*/approvals/stream*`, EMPTY_SSE).as("approvalsStream");
  cy.intercept("GET", `${apiBase}/boards/*/memory/stream*`, EMPTY_SSE).as("memoryStream");
  cy.intercept("GET", `${apiBase}/agents/stream*`, EMPTY_SSE).as("agentsStream");
}
