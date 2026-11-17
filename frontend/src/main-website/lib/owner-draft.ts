import type { Capture, CaptureData, Owner } from "@/shared/lib/capture";

type Draft = {
  id: string;
  data: CaptureData;
  capture: Capture | null;
  ownerEmail?: string | null;
};

export async function restoreOwnerDraft(
  saved: string | null,
  owner: Owner | null,
  authorize: (id: string) => Promise<Capture>,
): Promise<Draft | null> {
  if (!saved) return null;
  try {
    const draft: Draft = JSON.parse(saved);
    if (
      !draft ||
      typeof draft.id !== "string" ||
      !draft.data ||
      typeof draft.data !== "object" ||
      Array.isArray(draft.data)
    )
      return null;
    if (draft.ownerEmail && draft.ownerEmail !== owner?.email) return null;
    if (draft.capture) {
      if (!owner?.verified || draft.capture.id !== draft.id) return null;
      // Local email metadata never substitutes for backend authorization.
      const authorized = await authorize(draft.id);
      if (authorized.id !== draft.id) return null;
      draft.capture = {
        ...draft.capture,
        // A confirmed upload can outlive a lost response or a closed browser tab.
        assets: authorized.assets ?? draft.capture.assets,
        location: undefined,
      };
    }
    return draft;
  } catch {
    return null;
  }
}
