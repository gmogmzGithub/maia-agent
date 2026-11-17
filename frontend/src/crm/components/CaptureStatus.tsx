import { captureState } from "@/crm/lib/capture-status";

export default function CaptureStatus({ status }: { status: string }) {
  const state = captureState(status);
  return (
    <span className="capture-status" data-tone={state.tone}>
      <span className="capture-status-icon" aria-hidden="true">
        {state.icon}
      </span>
      {state.label}
    </span>
  );
}
