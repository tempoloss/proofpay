import { createBountySchema } from "./schema";

const valid = {
  issue_url: "https://github.com/tempoloss/proofpay-demo/issues/1",
  amount_usd: "25",
  done_when: "divide(a, 0) returns None and a test covers it",
};

const errorsOf = (values: Record<string, string>) => {
  const result = createBountySchema.safeParse(values);
  // A value can break several rules of one field; the test asserts which fields fail.
  return result.success ? [] : [...new Set(result.error.issues.map((issue) => issue.path.join(".")))];
};

describe("createBountySchema", () => {
  it("accepts a GitHub issue URL, a whole-dollar amount and a described outcome", () => {
    expect(errorsOf(valid)).toEqual([]);
  });

  it.each([
    "https://github.com/tempoloss/proofpay-demo/pull/1",
    "http://github.com/tempoloss/proofpay-demo/issues/1",
    "https://github.com/tempoloss/proofpay-demo/issues/1/comments",
    "https://gitlab.com/tempoloss/proofpay-demo/issues/1",
  ])("rejects %s as the issue URL", (issue_url) => {
    expect(errorsOf({ ...valid, issue_url })).toEqual(["issue_url"]);
  });

  it.each(["0.99", "500.01", "1.234", "-5", "abc", ""])("rejects %s as the amount", (amount_usd) => {
    expect(errorsOf({ ...valid, amount_usd })).toEqual(["amount_usd"]);
  });

  it.each(["1", "25.5", "500", "499.99"])("accepts %s as the amount", (amount_usd) => {
    expect(errorsOf({ ...valid, amount_usd })).toEqual([]);
  });

  it("rejects an outcome shorter than ten characters after trimming", () => {
    expect(errorsOf({ ...valid, done_when: "   fix it    " })).toEqual(["done_when"]);
  });
});
