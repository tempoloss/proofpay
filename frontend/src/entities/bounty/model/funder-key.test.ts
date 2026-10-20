import { forgetFunderKey, loadFunderKey, saveFunderKey } from "./funder-key";

describe("funder key storage", () => {
  it("keeps one key per bounty and forgets only the one asked", () => {
    saveFunderKey("bounty-a", "key-a");
    saveFunderKey("bounty-b", "key-b");

    forgetFunderKey("bounty-a");

    expect(loadFunderKey("bounty-a")).toBeNull();
    expect(loadFunderKey("bounty-b")).toBe("key-b");
  });
});
