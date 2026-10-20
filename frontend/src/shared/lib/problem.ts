/** RFC 9457 problem details as the API returns them, plus its own `code`. */
interface Problem {
  title?: unknown;
  code?: unknown;
}

const MESSAGE_BY_CODE: Record<string, string> = {
  ISSUE_URL_INVALID: "That is not a GitHub issue URL.",
  AMOUNT_OUT_OF_RANGE: "The amount must be between $1 and $500.",
  GITHUB_NOT_FOUND: "GitHub cannot find that issue. Is the repository public?",
  GITHUB_ERROR: "GitHub did not answer. Try again in a minute.",
  LLM_UNAVAILABLE: "The AI could not draft criteria right now. Try again in a minute.",
  PAYPAL_ERROR: "PayPal rejected the request.",
  PAYPAL_UNAVAILABLE: "PayPal is not reachable right now.",
  FUNDER_KEY_INVALID: "The funder key saved in this browser does not match this bounty.",
  CRITERIA_INVALID: "Every criterion needs text, and there can be at most six.",
  INVALID_TRANSITION: "The bounty changed in the meantime. Refresh and try again.",
  ALREADY_CAPTURED: "The money is already captured, so it can only be paid out.",
  NOT_AWAITING_DECISION: "The bounty is not waiting for a decision any more.",
  BOUNTY_NOT_FOUND: "This bounty does not exist.",
};

/** A sentence for the user from whatever a failed request threw. */
export function problemMessage(error: unknown): string {
  if (typeof error === "object" && error !== null) {
    const problem = error as Problem;
    if (typeof problem.code === "string" && problem.code in MESSAGE_BY_CODE) {
      return MESSAGE_BY_CODE[problem.code] ?? problem.code;
    }
    if (typeof problem.title === "string" && problem.title.length > 0) return problem.title;
  }
  return "Something went wrong. Try again.";
}

/** The machine code of a problem response, if there is one. */
export const problemCode = (error: unknown): string | null =>
  typeof error === "object" && error !== null && typeof (error as Problem).code === "string"
    ? ((error as Problem).code as string)
    : null;
