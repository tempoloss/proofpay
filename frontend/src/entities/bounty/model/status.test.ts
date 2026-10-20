import { isBountyStatus, STATUS_META, shouldPoll } from "./status";
import type { BountyStatus } from "./types";

describe("shouldPoll", () => {
  it("polls only while the server moves the bounty on its own", () => {
    const polled = (Object.keys(STATUS_META) as BountyStatus[]).filter(shouldPoll);
    expect(polled.sort()).toEqual(["awaiting_payment", "in_review", "released"]);
  });
});

describe("isBountyStatus", () => {
  it("accepts known statuses and rejects anything else", () => {
    expect(isBountyStatus("needs_human")).toBe(true);
    expect(isBountyStatus("toString")).toBe(false);
    expect(isBountyStatus("PAID")).toBe(false);
  });
});
