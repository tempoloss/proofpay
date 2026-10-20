import { render, screen } from "@testing-library/react";
import { VerdictRow } from "./verdict";

const criterion = { id: "c1", text: "divide(a, 0) returns None" };

describe("VerdictRow", () => {
  it("credits a met criterion to the file whose added lines hold the quote", () => {
    render(
      <VerdictRow
        criterion={criterion}
        item={{
          criterion_id: "c1",
          state: "met",
          quote: "if b == 0:\n    return None",
          file: "src/tinycalc/__init__.py",
          reason: "Guard added",
        }}
      />,
    );
    expect(screen.getByText(/Quote found in the added lines of/)).toHaveTextContent(
      "src/tinycalc/__init__.py",
    );
    expect(screen.getByText("return None", { exact: false })).toBeInTheDocument();
  });

  it("hands an unverifiable quote to a human instead of showing the judge's claim as proof", () => {
    render(
      <VerdictRow
        criterion={criterion}
        item={{
          criterion_id: "c1",
          state: "unverified",
          quote: "return None  # handled",
          file: "src/tinycalc/__init__.py",
          reason: "quote not found in added lines",
        }}
      />,
    );
    expect(screen.getByText(/not in the pull request's added lines/)).toBeInTheDocument();
    expect(screen.queryByText(/Quote found/)).not.toBeInTheDocument();
  });

  it("explains a criterion the judge skipped", () => {
    render(
      <VerdictRow
        criterion={criterion}
        item={{
          criterion_id: "c1",
          state: "unverified",
          quote: "",
          file: "",
          reason: "criterion missing from judge answer",
        }}
      />,
    );
    expect(screen.getByText(/did not answer this criterion/)).toBeInTheDocument();
  });
});
