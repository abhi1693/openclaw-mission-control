describe("Organizations (PR #61)", () => {
  const email = Cypress.env("CLERK_TEST_EMAIL") || "jane+clerk_test@example.com";

  beforeEach(() => {
    // Story: user signs in via official Clerk Cypress commands.
    cy.visit("/sign-in");
    cy.clerkLoaded();
    cy.clerkSignIn({ strategy: "email_code", identifier: email });
  });

  it("signed-in user can open /organization and create an invite link", () => {
    // Story (positive): org admin invites a teammate.
    cy.visit("/organization");

    cy.contains(/members\s*&\s*invites/i, { timeout: 30_000 }).should("be.visible");

    // Open invite dialog.
    cy.contains("button", /invite member/i).should("be.visible").click();

    const invitedEmail = `cypress+invite-${Date.now()}@example.com`;

    // Fill invite form.
    cy.get('input[type="email"]').should("be.visible").clear().type(invitedEmail);

    cy.contains("button", /send invite|invite|create/i).click();

    // Confirm invite shows up in table.
    cy.contains(invitedEmail, { timeout: 30_000 }).should("be.visible");

    // Stub clipboard and verify "Copy link" emits /invite?token=...
    cy.window().then((win) => {
      // Some browsers/environments may not expose clipboard; guard accordingly.
      if (!win.navigator.clipboard) {
        // @ts-expect-error - allow defining clipboard in test runtime
        win.navigator.clipboard = { writeText: () => Promise.resolve() };
      }
      cy.stub(win.navigator.clipboard, "writeText").as("writeText");
    });

    // Click copy link for this invite row.
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
