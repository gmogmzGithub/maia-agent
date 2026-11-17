"use client";

import {
  Children,
  createContext,
  isValidElement,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { ApiIssue } from "@/shared/lib/api-errors";
import {
  FormFeedback,
  type FeedbackSnapshot,
} from "@/shared/lib/form-feedback";

const Feedback = createContext<FormFeedback | null>(null);
function textOf(node: ReactNode): string {
  return Children.toArray(node)
    .map((child) =>
      isValidElement<{ children?: ReactNode }>(child)
        ? child.type === "button"
          ? ""
          : textOf(child.props.children)
        : String(child),
    )
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

export function ErrorFeedbackProvider({ children }: { children: ReactNode }) {
  const [feedback, setFeedback] = useState<FormFeedback | null>(null);
  const [snapshot, setSnapshot] = useState<FeedbackSnapshot>({ issues: [] });
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  const description = useId();
  useEffect(() => {
    const instance = new FormFeedback(document, setSnapshot);
    setFeedback(instance);
    return () => instance.dispose();
  }, []);
  useEffect(() => {
    if (snapshot.issues.length) {
      if (!dialog.current?.open) dialog.current?.showModal();
    } else dialog.current?.close();
  }, [snapshot]);
  const close = (target?: HTMLElement, retry?: () => void) => {
    dialog.current?.close();
    feedback?.dismiss(target, retry);
  };
  const target = snapshot.issues.find(
    (issue) => issue.target?.isConnected,
  )?.target;
  return (
    <Feedback.Provider value={feedback}>
      {children}
      <dialog
        ref={dialog}
        className="error-dialog"
        aria-labelledby={title}
        aria-describedby={description}
        onCancel={(event) => {
          event.preventDefault();
          close(target);
        }}
      >
        <div className="error-dialog-icon" aria-hidden="true">
          !
        </div>
        <h2 id={title}>No pudimos continuar</h2>
        <div id={description}>
          {snapshot.issues.length === 1 ? (
            <p>{snapshot.issues[0].message}</p>
          ) : (
            <ul>
              {snapshot.issues.map((issue, index) => (
                <li key={index}>
                  {issue.target ? (
                    <button
                      type="button"
                      className="error-field-link"
                      onClick={() => close(issue.target)}
                    >
                      {issue.message}
                    </button>
                  ) : (
                    issue.message
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="error-dialog-actions">
          <button
            type="button"
            className="button primary"
            onClick={() => close(target)}
            autoFocus
          >
            {target ? "Ir al campo" : "Entendido"}
          </button>
          {snapshot.retry && (
            <button
              type="button"
              className="button secondary"
              onClick={() => close(undefined, snapshot.retry)}
            >
              Reintentar
            </button>
          )}
        </div>
      </dialog>
    </Feedback.Provider>
  );
}

export default function ErrorNotice({
  children,
  issues,
  fields = {},
  target,
  retry,
}: {
  children: ReactNode;
  issues?: ApiIssue[];
  fields?: Record<string, string>;
  target?: string;
  retry?: () => void;
}) {
  const feedback = useContext(Feedback);
  const source = useId();
  const root = useRef<HTMLDivElement>(null);
  const retryRef = useRef(retry);
  retryRef.current = retry;
  const message = textOf(children);
  const issueKey = JSON.stringify(
    issues?.length
      ? issues
      : message
        ? [{ message, ...(target ? { field: "__target" } : {}) }]
        : [],
  );
  const fieldKey = JSON.stringify({
    ...fields,
    ...(target ? { __target: target } : {}),
  });
  useEffect(() => {
    if (!feedback) return;
    const failures: ApiIssue[] = JSON.parse(issueKey);
    if (!failures.length) return;
    const scope =
      root.current?.closest("form") ||
      root.current?.closest("main") ||
      document;
    feedback.remote(
      source,
      failures,
      scope,
      JSON.parse(fieldKey),
      retryRef.current ? () => retryRef.current?.() : undefined,
    );
    return () => feedback.clear(source);
  }, [feedback, source, issueKey, fieldKey]);
  return (
    <div ref={root} className="notice error">
      {children}
    </div>
  );
}
