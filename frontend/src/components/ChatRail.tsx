import type { ReactNode } from "react";
import { STATS, TOP_CHANCE, type Message } from "../data";
import MiniShotMap from "./MiniShotMap";

const XG = STATS.xg.toFixed(2);
const TOP_XG = TOP_CHANCE.xg.toFixed(2);
const VS_XG = `${STATS.vsXg >= 0 ? "+" : ""}${STATS.vsXg.toFixed(2)}`;

interface ChatRailProps {
  isEmpty: boolean;
  showPrebaked: boolean;
  messages: Message[];
  thinking: boolean;
  input: string;
  onInput: (value: string) => void;
  onSend: () => void;
}

function Chip({
  tone,
  children,
}: {
  tone: "green" | "grey";
  children: ReactNode;
}) {
  const cls =
    tone === "green"
      ? "border-[rgba(52,211,153,.25)] bg-[rgba(52,211,153,.1)] text-accent"
      : "border-line-hover bg-[rgba(138,150,144,.12)] text-muted";
  return (
    <span
      className={`mx-px inline-flex items-center rounded-[5px] border px-[6px] font-mono text-[11px] ${cls}`}
    >
      {children}
    </span>
  );
}

function SpeakerLabel({ label, dot }: { label: string; dot: boolean }) {
  return (
    <div className="flex items-center gap-[7px]">
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-accent" />}
      <span className="font-mono text-[10px] tracking-[.16em] text-muted">
        {label}
      </span>
    </div>
  );
}

function GroundingBadge({
  grounded,
  corrected,
}: {
  grounded?: boolean;
  corrected?: boolean;
}) {
  if (grounded === undefined) return null;
  const label = corrected ? "corrected" : grounded ? "grounded" : "unverified";
  const cls = grounded
    ? "border-[rgba(52,211,153,.28)] bg-[rgba(52,211,153,.08)] text-accent"
    : "border-line-hover bg-[rgba(138,150,144,.1)] text-muted";
  return (
    <span
      className={`inline-flex items-center rounded-[4px] border px-[6px] py-[2px] font-mono text-[9px] uppercase tracking-[.14em] ${cls}`}
    >
      {label}
    </span>
  );
}

function statChipLabel(label: string): string {
  const parts = label.split(" ");
  const last = parts[parts.length - 1]?.toLowerCase() ?? label;
  if (["shots", "goals", "xg", "passes", "assists"].includes(last)) {
    return last === "xg" ? "xG" : last;
  }
  return label.length > 22 ? `${label.slice(0, 20)}…` : label;
}

function PrebakedConversation() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-[7px]">
        <div className="font-mono text-[10px] tracking-[.16em] text-muted">
          YOU
        </div>
        <div className="text-[13.5px] leading-[1.55] text-fg">
          How did Argentina create chances against France in the final?
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <SpeakerLabel label="GAFFER" dot />
        <div className="text-[13.5px] leading-[1.62] text-fg">
          Di María tormented Koundé down the left, and they kept attacking that
          channel. {STATS.shots} attempts worth{" "}
          <Chip tone="green">xG {XG}</Chip> across the match — the standout was
          the <Chip tone="green">{TOP_XG} xG</Chip> penalty{" "}
          {TOP_CHANCE.player} buried. I've plotted every shot on the board →
        </div>
        <MiniShotMap />
      </div>

      <div className="flex flex-col gap-[7px]">
        <div className="font-mono text-[10px] tracking-[.16em] text-muted">
          YOU
        </div>
        <div className="text-[13.5px] leading-[1.55] text-fg">
          Which was the best chance?
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <SpeakerLabel label="GAFFER" dot />
        <div className="text-[13.5px] leading-[1.62] text-fg">
          The <Chip tone="green">{TOP_XG} xG</Chip> penalty —{" "}
          {TOP_CHANCE.player} from the spot. Argentina finished {STATS.goals}{" "}
          from <Chip tone="green">xG {XG}</Chip>, a{" "}
          <Chip tone="grey">{VS_XG}</Chip> overperformance.
        </div>
      </div>
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div
      className="flex flex-col gap-[9px]"
      style={{ animation: "gfade .3s ease both" }}
    >
      <div className="flex items-center gap-[7px]">
        <span
          className="h-1.5 w-1.5 rounded-full bg-accent"
          style={{ animation: "gpulse 1.2s ease-in-out infinite" }}
        />
        <span className="font-mono text-[10px] tracking-[.16em] text-muted">
          GAFFER
        </span>
      </div>
      <div className="flex items-center gap-[11px]">
        <svg width="60" height="18" viewBox="0 0 60 18" fill="none">
          <path
            d="M2,13 C11,2 18,17 27,8 S46,2 58,11"
            stroke="#34D399"
            strokeWidth="2"
            strokeLinecap="round"
            style={{
              strokeDasharray: 120,
              animation: "gchalk 1.5s ease-in-out infinite",
            }}
          />
        </svg>
        <span className="font-mono text-[11.5px] text-accent">Analyzing…</span>
      </div>
    </div>
  );
}

export default function ChatRail({
  isEmpty,
  showPrebaked,
  messages,
  thinking,
  input,
  onInput,
  onSend,
}: ChatRailProps) {
  return (
    <div className="flex min-h-0 w-[380px] flex-none flex-col border-r border-line bg-rail">
      <div className="flex flex-1 flex-col gap-6 overflow-y-auto px-5 py-[22px]">
        {isEmpty && (
          <div className="my-auto flex flex-col gap-[9px] text-left opacity-90">
            <div className="font-mono text-[10px] tracking-[.18em] text-dim">
              NO ANALYSIS LOADED
            </div>
            <div className="text-[13px] leading-[1.55] text-muted">
              Ask a tactical or scouting question, or pick one of the prompts on
              the board.
            </div>
          </div>
        )}

        {showPrebaked && <PrebakedConversation />}

        {messages.map((m, i) => (
          <div
            key={i}
            className="flex flex-col gap-[7px]"
            style={{ animation: "gfade .35s ease both" }}
          >
            <div className="flex items-center gap-2">
              <SpeakerLabel label={m.label} dot={m.showDot} />
              {m.role === "gaffer" && (
                <GroundingBadge grounded={m.grounded} corrected={m.corrected} />
              )}
            </div>
            <div
              className={`text-[13.5px] leading-[1.6] ${m.error ? "text-amber" : "text-fg"}`}
            >
              {m.text}
            </div>
            {m.citedStats && m.citedStats.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-0.5">
                {m.citedStats.map((c, j) => (
                  <Chip key={j} tone="green">
                    {statChipLabel(c.label)} {c.value}
                  </Chip>
                ))}
              </div>
            )}
          </div>
        ))}

        {thinking && <ThinkingIndicator />}
      </div>

      <div className="flex-none border-t border-line px-[14px] py-[13px]">
        <div className="flex items-center gap-2 rounded-[11px] border border-line bg-panel py-[7px] pl-[13px] pr-[7px] focus-within:border-edge">
          <input
            type="text"
            value={input}
            onChange={(e) => onInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder="Ask Gaffer a tactical question…"
            className="min-w-0 flex-1 border-none bg-transparent font-body text-[13px] text-fg outline-none"
            disabled={thinking}
          />
          <button
            onClick={onSend}
            disabled={thinking || !input.trim()}
            className="flex h-8 w-8 flex-none items-center justify-center rounded-[8px] border-none bg-accent text-base font-bold text-ink hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}
