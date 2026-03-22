import { buildUser, buildOrg, buildOrgMember } from "../factories";
import type { UserEntity, OrgEntity, OrgMemberEntity } from "../factories";

interface StubAuthOptions {
  user?: Partial<UserEntity>;
  org?: Partial<OrgEntity>;
  member?: Partial<OrgMemberEntity>;
}

export function stubAuth(apiBase: string, options: StubAuthOptions = {}): void {
  const user = buildUser(options.user);
  const org = buildOrg({ id: "org-1", name: "Testing Org", ...options.org });
  const member = buildOrgMember({
    organization_id: org.id,
    user_id: user.id,
    ...options.member,
  });

  cy.intercept("GET", "**/healthz", {
    statusCode: 200,
    body: { ok: true },
  }).as("healthz");

  cy.intercept("GET", `${apiBase}/users/me*`, {
    statusCode: 200,
    body: user,
  }).as("usersMe");

  cy.intercept("GET", `${apiBase}/organizations/me/list*`, {
    statusCode: 200,
    body: [org],
  }).as("organizationsList");

  cy.intercept("GET", `${apiBase}/organizations/me/member*`, {
    statusCode: 200,
    body: member,
  }).as("orgMeMember");
}
