describe("Organizations (PR #61)", () => {
  const email = Cypress.env("CLERK_TEST_EMAIL") || "jane+clerk_test@example.com";

  it("negative: signed-out user is redirected to sign-in when opening /organization", () => {
    cy.visit("/organization");
    cy.location("pathname", { timeout: 30_000 }).should("match", /\/sign-in/);
  });

  it("positive: org owner can create an org and invite a member (copy invite link)", () => {
    // Story (positive): user signs in, creates a new org, then invites a teammate.
    cy.visit("/sign-in");
    cy.clerkLoaded();
    cy.clerkSignIn({ strategy: "email_code", identifier: email });

    // Go to a page that shows OrgSwitcher.
    cy.visit("/boards");

    // Create a new org via OrgSwitcher.
    cy.contains(/org switcher/i, { timeout: 30_000 }).should("be.visible");

    // Open select and click "Create new org".
    cy.contains("button", /select organization/i)
      .should("be.visible")
      .click();

    cy.contains(/create new org/i).should("be.visible").click();

    const orgName = `Cypress Org ${Date.now()}`;
    cy.get("#org-name").should("be.visible").clear().type(orgName);
    cy.contains("button", /^create org$/i).should("be.visible").click();

    // Creating org triggers a reload; ensure we land back in the app.
    cy.location("pathname", { timeout: 60_000 }).should("match", /\/(boards|organization|activity)/);

    // Now visit organization admin page and create an invite.
    cy.visit("/organization");
    cy.contains(/members\s*&\s*invites/i, { timeout: 30_000 }).should("be.visible");

    cy.contains("button", /invite member/i).should("be.visible").click();

    const invitedEmail = `cypress+invite-${Date.now()}@example.com`;
    cy.get('input[type="email"]').should("be.visible").clear().type(invitedEmail);

    // Invite submit button text varies; match loosely.
    cy.contains("button", /invite/i).should("be.visible").click();

    // Confirm invite shows up in table.
    cy.contains(invitedEmail, { timeout: 30_000 }).should("be.visible");

    // Stub clipboard and verify "Copy link" emits /invite?token=...
    cy.window().then((win) => {
      if (!win.navigator.clipboard) {
        // @ts-expect-error - allow defining clipboard in test runtime
        win.navigator.clipboard = { writeText: () => Promise.resolve() };
      }
      cy.stub(win.navigator.clipboard, "writeText").as("writeText");
    });

    cy.contains("tr", invitedEmail)
      .should("be.visible")
      .within(() => {
        cy.contains("button", /copy link/i).click();
      });

    cy.get("@writeText").should("have.been.calledOnce");
    cy.get("@writeText").should((writeText) => {
      const stub = writeText as unknown as sinon.SinonStub;
      const text = stub.getCall(0).args[0] as string;
      expect(text).to.match(/\/invite\?token=/);
    });
  });
});
