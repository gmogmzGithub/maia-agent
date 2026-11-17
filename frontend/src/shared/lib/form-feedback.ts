import type { ApiIssue } from "./api-errors";

export type FeedbackIssue = { message: string; target?: HTMLElement };
export type FeedbackSnapshot = { issues: FeedbackIssue[]; retry?: () => void };
type Field = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
type Mark = {
  note: HTMLElement;
  invalid: string | null;
  described: string | null;
  source: string;
};
type Report = { issues: FeedbackIssue[]; retry?: () => void };

/** One lifetime for remote failures, native validation, annotations and focus. */
export class FormFeedback {
  private sources = new Map<string, Report>();
  private marks = new Map<HTMLElement, Mark>();
  private pending: FeedbackIssue[] = [];
  private timer?: ReturnType<typeof setTimeout>;
  private returnFocus: HTMLElement | null = null;
  private disposed = false;
  private sequence = 0;
  constructor(
    private document: Document,
    private changed: (snapshot: FeedbackSnapshot) => void,
  ) {
    document.addEventListener("invalid", this.invalid, true);
    document.addEventListener("input", this.input, true);
    document.addEventListener("change", this.input, true);
  }
  private field(target: EventTarget | null): target is Field {
    return (
      !!target &&
      ["INPUT", "SELECT", "TEXTAREA"].includes((target as Element).tagName)
    );
  }
  private sweep() {
    for (const field of this.marks.keys())
      if (!field.isConnected) this.unmark(field);
  }
  private unmark(field: HTMLElement) {
    const mark = this.marks.get(field);
    if (!mark) return;
    mark.note.remove();
    if (mark.invalid === null) field.removeAttribute("aria-invalid");
    else field.setAttribute("aria-invalid", mark.invalid);
    if (mark.described === null) field.removeAttribute("aria-describedby");
    else field.setAttribute("aria-describedby", mark.described);
    this.marks.delete(field);
  }
  private mark(field: HTMLElement, message: string, source: string) {
    this.unmark(field);
    const note = this.document.createElement("span");
    note.id = `maia-field-error-${++this.sequence}`;
    note.className = "field-error";
    note.textContent = message;
    this.marks.set(field, {
      note,
      source,
      invalid: field.getAttribute("aria-invalid"),
      described: field.getAttribute("aria-describedby"),
    });
    field.setAttribute("aria-invalid", "true");
    field.setAttribute(
      "aria-describedby",
      [field.getAttribute("aria-describedby"), note.id]
        .filter(Boolean)
        .join(" "),
    );
    field.insertAdjacentElement("afterend", note);
  }
  private publish() {
    if (this.disposed) return;
    this.sweep();
    const reports = [...this.sources.values()];
    const issues: FeedbackIssue[] = [];
    for (const report of reports)
      for (const issue of report.issues) {
        if (
          !issues.some(
            (item) =>
              item.message === issue.message && item.target === issue.target,
          )
        )
          issues.push(issue);
      }
    this.changed({
      issues,
      ...(reports.length === 1 && reports[0].retry
        ? { retry: reports[0].retry }
        : {}),
    });
  }
  private show(source: string, report: Report) {
    if (this.disposed) return;
    if (!this.sources.size)
      this.returnFocus = this.document.activeElement as HTMLElement | null;
    this.sources.set(source, report);
    this.publish();
  }
  private invalid = (event: Event) => {
    if (!this.field(event.target)) return;
    event.preventDefault();
    const field = event.target;
    this.unmark(field);
    const label =
      field.getAttribute("aria-label") ||
      field.labels?.[0]?.textContent?.replace(/\s+/g, " ").trim() ||
      field.name ||
      "Campo";
    const message = `${label}: ${field.validity.valueMissing ? "Completa este campo para continuar." : field.validationMessage}`;
    this.mark(field, message, "native");
    this.pending.push({ message, target: field });
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      const issues = this.pending;
      this.pending = [];
      this.show("native", { issues });
    }, 0);
  };
  private input = (event: Event) => {
    const field = event.target;
    if (!this.field(field)) return;
    // React's controlled monetary input updates customValidity during commit.
    queueMicrotask(() => {
      if (this.disposed) return;
      const mark = this.marks.get(field);
      if (mark && (mark.source !== "native" || field.validity.valid))
        this.unmark(field);
      this.sweep();
    });
  };
  remote(
    source: string,
    issues: ApiIssue[],
    scope: ParentNode,
    fields: Record<string, string> = {},
    retry?: () => void,
  ) {
    if (this.disposed) return;
    for (const [field, mark] of this.marks)
      if (mark.source === source) this.unmark(field);
    const resolved = issues.map((issue) => {
      let target: HTMLElement | undefined;
      if (issue.field) {
        target = fields[issue.field]
          ? (scope.querySelector<HTMLElement>(fields[issue.field]) ?? undefined)
          : ([
              ...scope.querySelectorAll<HTMLElement>("[data-feedback-field]"),
            ].find((field) => field.dataset.feedbackField === issue.field) ??
            [
              ...scope.querySelectorAll<HTMLElement>(
                'input:not([type="hidden"]), select, textarea',
              ),
            ].find((field) => field.getAttribute("name") === issue.field));
      }
      if (target) this.mark(target, issue.message, source);
      return { message: issue.message, target };
    });
    this.show(source, { issues: resolved, retry });
  }
  clear(source: string) {
    const removed = this.sources.delete(source);
    for (const [field, mark] of this.marks)
      if (mark.source === source) this.unmark(field);
    if (removed) this.publish();
  }
  dismiss(target?: HTMLElement, retry?: () => void) {
    this.sources.clear();
    this.publish();
    const focus = target?.isConnected ? target : this.returnFocus;
    if (focus?.isConnected) {
      focus.scrollIntoView?.({ block: "center", behavior: "smooth" });
      focus.focus({ preventScroll: true });
    }
    // Replays only the explicit, caller-supplied safe operation.
    retry?.();
  }
  dispose() {
    this.disposed = true;
    clearTimeout(this.timer);
    this.sources.clear();
    this.pending = [];
    this.document.removeEventListener("invalid", this.invalid, true);
    this.document.removeEventListener("input", this.input, true);
    this.document.removeEventListener("change", this.input, true);
    for (const field of this.marks.keys()) this.unmark(field);
  }
}
