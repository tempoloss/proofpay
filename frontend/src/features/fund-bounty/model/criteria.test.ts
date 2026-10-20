import { criteriaSchema, nextCriterionId } from "./criteria";

describe("nextCriterionId", () => {
  it("continues after the highest id even when earlier ones were removed", () => {
    expect(nextCriterionId(["c1", "c3"])).toBe("c4");
  });

  it("starts at c1 for an empty list and ignores foreign ids", () => {
    expect(nextCriterionId([])).toBe("c1");
    expect(nextCriterionId(["x", "c2"])).toBe("c3");
  });
});

describe("criteriaSchema", () => {
  const item = (id: string, text: string) => ({ id, text });

  it("rejects a blank criterion and an empty or oversized list", () => {
    expect(criteriaSchema.safeParse({ criteria: [item("c1", "   ")] }).success).toBe(false);
    expect(criteriaSchema.safeParse({ criteria: [] }).success).toBe(false);
    const seven = Array.from({ length: 7 }, (_, index) => item(`c${index + 1}`, "Adds a test"));
    expect(criteriaSchema.safeParse({ criteria: seven }).success).toBe(false);
  });

  it("trims what it accepts", () => {
    const parsed = criteriaSchema.parse({ criteria: [item("c1", "  Adds a test  ")] });
    expect(parsed.criteria[0]?.text).toBe("Adds a test");
  });
});
