import { claimSchema, loadClaimId, saveClaimId, submitSchema } from "./schema";

describe("claimSchema", () => {
  it("needs a name and an e-mail shaped PayPal address", () => {
    expect(claimSchema.safeParse({ solver_name: "ana", paypal_email: "ana@example.com" }).success).toBe(true);
    expect(claimSchema.safeParse({ solver_name: "  ", paypal_email: "ana@example.com" }).success).toBe(false);
    expect(claimSchema.safeParse({ solver_name: "ana", paypal_email: "ana@example" }).success).toBe(false);
  });
});

describe("submitSchema", () => {
  it.each([
    "https://github.com/tempoloss/proofpay-demo/issues/1",
    "https://github.com/tempoloss/proofpay-demo/pull/7/files",
    "http://github.com/tempoloss/proofpay-demo/pull/7",
  ])("rejects %s", (pr_url) => {
    expect(submitSchema.safeParse({ pr_url }).success).toBe(false);
  });

  it("accepts a pull request URL", () => {
    expect(
      submitSchema.safeParse({ pr_url: "https://github.com/tempoloss/proofpay-demo/pull/7" }).success,
    ).toBe(true);
  });
});

describe("claim storage", () => {
  it("remembers the claim per bounty", () => {
    saveClaimId("bounty-a", "claim-1");
    expect(loadClaimId("bounty-a")).toBe("claim-1");
    expect(loadClaimId("bounty-b")).toBeNull();
  });
});
