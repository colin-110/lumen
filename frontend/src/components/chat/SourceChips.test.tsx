import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SourceChips } from "./SourceChips";
import type { ChatSource } from "@/lib/types";

const source = (doc: string, file: string, snippet = "text"): ChatSource => ({
  filename: file,
  document_id: doc,
  chunk_id: `${doc}-${snippet}`,
  score: 1.23,
  snippet,
});

describe("SourceChips", () => {
  it("renders nothing when there are no sources", () => {
    const { container } = render(<SourceChips sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("labels passages when one document is cited more than once", () => {
    // The reported confusion: three chunks from one PDF rendered three
    // identical chips and read as the same source cited three times.
    render(
      <SourceChips
        sources={[source("d1", "report.pdf", "a"), source("d1", "report.pdf", "b"), source("d1", "report.pdf", "c")]}
      />
    );
    expect(screen.getByText("passage 1")).toBeInTheDocument();
    expect(screen.getByText("passage 2")).toBeInTheDocument();
    expect(screen.getByText("passage 3")).toBeInTheDocument();
  });

  it("omits the label when a document contributes only one passage", () => {
    render(<SourceChips sources={[source("d1", "a.pdf"), source("d2", "b.pdf")]} />);
    expect(screen.queryByText(/passage/)).not.toBeInTheDocument();
  });

  it("numbers passages per document, not globally", () => {
    render(
      <SourceChips
        sources={[
          source("d1", "a.pdf", "1"),
          source("d2", "b.pdf", "2"),
          source("d1", "a.pdf", "3"),
          source("d2", "b.pdf", "4"),
        ]}
      />
    );
    // Each document restarts at 1, so two of each rather than 1..4.
    expect(screen.getAllByText("passage 1")).toHaveLength(2);
    expect(screen.getAllByText("passage 2")).toHaveLength(2);
  });

  it("keeps citation numbers globally sequential so [n] matches the answer", () => {
    render(<SourceChips sources={[source("d1", "a.pdf"), source("d2", "b.pdf"), source("d3", "c.pdf")]} />);
    expect(screen.getByText("[1]")).toBeInTheDocument();
    expect(screen.getByText("[2]")).toBeInTheDocument();
    expect(screen.getByText("[3]")).toBeInTheDocument();
  });

  it("reveals that passage's own snippet when a chip is clicked", async () => {
    const user = userEvent.setup();
    render(<SourceChips sources={[source("d1", "r.pdf", "FIRST"), source("d1", "r.pdf", "SECOND")]} />);
    expect(screen.queryByText("SECOND")).not.toBeInTheDocument();
    await user.click(screen.getAllByRole("button")[1]);
    expect(screen.getByText("SECOND")).toBeInTheDocument();
  });

  it("falls back to filename grouping when document_id is absent", () => {
    const noId = (file: string, snippet: string): ChatSource => ({
      filename: file,
      document_id: null,
      chunk_id: snippet,
      score: 1,
      snippet,
    });
    render(<SourceChips sources={[noId("x.pdf", "a"), noId("x.pdf", "b")]} />);
    expect(screen.getByText("passage 2")).toBeInTheDocument();
  });
});
