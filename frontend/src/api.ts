/** Backend /chat client (plan section 7). */

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface CitedStat {
  label: string;
  value: string;
  source: string;
}

export interface ChatResponse {
  answer_text: string;
  visuals: string[];
  cited_stats: CitedStat[];
  grounded: boolean;
  verification_notes: string[];
}

export class ChatError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ChatError";
    this.status = status;
  }
}

export async function postChat(
  message: string,
  sessionId: string,
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ChatError(
      detail || `Request failed (${res.status})`,
      res.status,
    );
  }

  return res.json() as Promise<ChatResponse>;
}

/** True when the grounding pass rewrote the draft to fix unsupported claims. */
export function wasCorrected(notes: string[]): boolean {
  return notes.some(
    (n) =>
      n.toLowerCase().includes("rewriting draft") ||
      n.toLowerCase().includes("rewrite budget"),
  );
}

/** Derive a canvas headline from shot_map cited stats, if present. */
export function deriveCanvasTitle(cited: CitedStat[]): string | null {
  const shot = cited.find(
    (c) =>
      c.source === "shot_map" && c.label.toLowerCase().includes("shots"),
  );
  if (!shot) return null;
  const player = shot.label.replace(/\s+shots$/i, "").trim();
  return player ? `${player} — shot map` : null;
}

export interface CanvasStats {
  xg: string | null;
  shots: string | null;
  goals: string | null;
  vsXg: string | null;
}

/** Pull xG / shots / goals / vs-xG from cited_stats for the canvas stat pill. */
export function extractCanvasStats(cited: CitedStat[]): CanvasStats {
  let xg: string | null = null;
  let shots: string | null = null;
  let goals: string | null = null;
  let vsXg: string | null = null;

  for (const c of cited) {
    const label = c.label.toLowerCase();
    if (label.includes("xg diff")) {
      const n = parseFloat(c.value);
      if (!Number.isNaN(n)) {
        vsXg = `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;
      }
    } else if (label.includes("xg") && !label.includes("diff")) {
      if (!xg) xg = c.value;
    } else if (label.includes("shots")) {
      shots = c.value;
    } else if (label.includes("goals")) {
      goals = c.value;
    }
  }

  if (!vsXg && xg && goals) {
    const diff = parseFloat(goals) - parseFloat(xg);
    if (!Number.isNaN(diff)) {
      vsXg = `${diff >= 0 ? "+" : ""}${diff.toFixed(2)}`;
    }
  }

  return { xg, shots, goals, vsXg };
}
