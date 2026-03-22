/// <reference types="cypress" />

import { resetFactoryState } from "./factories";
import { stubAuth } from "./intercepts";

type CommonPageTestHooksOptions = {
  timeoutMs?: number;
  orgMemberRole?: string;
  organizationId?: string;
  organizationName?: string;
  userId?: string;
  userEmail?: string;
  userName?: string;
};

/**
 * Legacy convenience wrapper around stubAuth + factory reset.
 * New tests should use stubAuth() and resetFactoryState() directly.
 */
export function setupCommonPageTestHooks(
  apiBase: string,
  options: CommonPageTestHooksOptions = {},
): void {
  const {
    timeoutMs = 20_000,
    orgMemberRole = "owner",
    organizationId = "org1",
    organizationName = "Testing Org",
    userId = "u1",
    userEmail = "local-auth-user@example.com",
    userName = "Local User",
  } = options;
  const originalDefaultCommandTimeout = Cypress.config("defaultCommandTimeout");

  beforeEach(() => {
    resetFactoryState();
    Cypress.config("defaultCommandTimeout", timeoutMs);

    stubAuth(apiBase, {
      user: { id: userId, email: userEmail, name: userName, preferred_name: userName },
      org: { id: organizationId, name: organizationName },
      member: { role: orgMemberRole, organization_id: organizationId, user_id: userId },
    });
  });

  afterEach(() => {
    Cypress.config("defaultCommandTimeout", originalDefaultCommandTimeout);
  });
}
