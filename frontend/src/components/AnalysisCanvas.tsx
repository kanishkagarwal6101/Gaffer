import {
  EXAMPLE_PROMPTS,
  MATCH,
  STATS,
  type ShotMarker,
} from "../data";
import Pitch from "./Pitch";

const SCORE = `${MATCH.home.goals}–${MATCH.away.goals}`;
const VS_XG = `${STATS.vsXg >= 0 ? "+" : ""}${STATS.vsXg.toFixed(2)}`;

interface AnalysisCanvasProps {
  isMain: boolean;
  isEmpty: boolean;
  thinking: boolean;
  shots: ShotMarker[];
  annotate: boolean;
  onExample: (text: string) => void;
  /**
   * Placeholder hook for later milestones (M2+): when the backend returns a
   * rendered mplsoccer shot-map PNG, pass its URL here and it renders in the
   * canvas in place of the mock SVG pitch. Null until the backend is wired up.
   */
  imageSrc?: string | null;
}

function ThinkingOverlay() {
  return (
    <div
      className="absolute inset-0 flex flex-col items-center justify-center gap-5"
      style={{ background: "rgba(13,19,17,.74)", backdropFilter: "blur(2px)" }}
    >
      <svg width="220" height="140" viewBox="0 0 220 140" fill="none">
        <path
          d="M20,120 C60,40 90,100 120,60 S180,30 205,70"
          stroke="#34D399"
          strokeWidth="2.2"
          strokeLinecap="round"
          style={{ strokeDasharray: 680, animation: "gdraw 1.8s ease-in-out infinite" }}
        />
        <circle
          cx="205"
          cy="70"
          r="6"
          fill="#34D399"
          style={{ animation: "gdim 1.8s ease-in-out infinite" }}
        />
      </svg>
      <span className="font-mono text-[11.5px] tracking-[.14em] text-accent">
        DRAWING UP THE DATA…
      </span>
    </div>
  );
}

function ShotMapView({
  thinking,
  shots,
  annotate,
  imageSrc,
}: Pick<AnalysisCanvasProps, "thinking" | "shots" | "annotate" | "imageSrc">) {
  return (
    <div
      data-screen-label="Analysis canvas"
      className="flex min-h-0 flex-1 flex-col px-9 pb-[26px] pt-6"
    >
      <div className="flex flex-none items-start justify-between gap-5">
        <div>
          <div className="mb-2 font-mono text-[10.5px] tracking-[.16em] text-muted">
            SHOT MAP · WC FINAL · ATTACKING →
          </div>
          <div className="font-display text-[22px] font-semibold tracking-[-.01em] text-fg">
            {MATCH.home.team}{" "}
            <span className="font-medium text-muted">{SCORE}</span>{" "}
            {MATCH.away.team}
          </div>
        </div>
        <div className="flex flex-none overflow-hidden rounded-[8px] border border-line font-mono text-[11px]">
          <div className="bg-[rgba(52,211,153,.12)] px-[14px] py-[7px] text-accent">
            Shot Map
          </div>
          <div className="cursor-pointer border-l border-line px-[14px] py-[7px] text-muted hover:text-fg">
            Pass Network
          </div>
          <div className="cursor-pointer border-l border-line px-[14px] py-[7px] text-muted hover:text-fg">
            Radar
          </div>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center py-5">
        {imageSrc ? (
          // Backend shot-map PNG renders here once available (see imageSrc above).
          <img
            src={imageSrc}
            alt="Shot map"
            style={{ width: "100%", maxWidth: 800, height: "auto", maxHeight: "100%" }}
          />
        ) : (
          <Pitch shots={shots} annotate={annotate} />
        )}
        {thinking && <ThinkingOverlay />}
      </div>

      <div className="flex flex-none flex-wrap items-center justify-between gap-6 pt-2">
        <div className="flex flex-wrap items-center gap-[18px] font-mono text-[10.5px] tracking-[.04em] text-muted">
          <span className="flex items-center gap-[7px]">
            <svg width="12" height="12">
              <circle cx="6" cy="6" r="5" fill="#34D399" fillOpacity=".85" />
            </svg>
            GOAL
          </span>
          <span className="flex items-center gap-[7px]">
            <svg width="12" height="12">
              <circle cx="6" cy="6" r="4.6" fill="none" stroke="#34D399" strokeWidth="1.6" strokeOpacity=".8" />
            </svg>
            MISS / SAVED
          </span>
          <span className="flex items-center gap-[7px]">
            <svg width="12" height="12">
              <circle cx="6" cy="6" r="5" fill="#E8A13A" fillOpacity=".82" />
            </svg>
            {MATCH.opponent.toUpperCase()}
          </span>
          <span className="text-dim">◦ MARKER SIZE = xG</span>
        </div>
        <div className="flex flex-none items-center whitespace-nowrap rounded-[8px] border border-line bg-panel px-[15px] py-[9px] font-mono text-[13.5px] tracking-[.02em]">
          <span className="text-muted">xG </span>
          <span className="font-semibold text-accent">{STATS.xg.toFixed(2)}</span>
          <span className="text-faint">&nbsp;·&nbsp;</span>
          <span className="text-muted">SHOTS </span>
          <span className="font-semibold text-fg">{STATS.shots}</span>
          <span className="text-faint">&nbsp;·&nbsp;</span>
          <span className="text-muted">GOALS </span>
          <span className="font-semibold text-accent">{STATS.goals}</span>
          <span className="text-faint">&nbsp;·&nbsp;</span>
          <span className="font-semibold text-accent">{VS_XG}</span>
          <span className="text-muted"> vs xG</span>
        </div>
      </div>
    </div>
  );
}

function LandingView({ onExample }: Pick<AnalysisCanvasProps, "onExample">) {
  return (
    <div
      data-screen-label="Landing"
      className="relative flex flex-1 flex-col items-center justify-center overflow-hidden"
    >
      <svg
        viewBox="-30 -30 1110 740"
        preserveAspectRatio="xMidYMid slice"
        className="absolute inset-0 h-full w-full"
      >
        <g stroke="#E8EDEB" strokeOpacity=".05" strokeWidth="2" fill="none" strokeLinecap="round">
          <rect x="0" y="0" width="1050" height="680" />
          <line x1="525" y1="0" x2="525" y2="680" />
          <circle cx="525" cy="340" r="91.5" />
          <rect x="0" y="138.5" width="165" height="403" />
          <rect x="885" y="138.5" width="165" height="403" />
        </g>
      </svg>

      <div className="relative z-[1] flex w-full max-w-[540px] flex-col items-center px-7">
        <div className="font-display text-[62px] font-bold leading-none tracking-[.14em] text-fg">
          GAFFER
        </div>
        <div className="my-[14px] mb-3 h-[3px] w-12 rounded-[2px] bg-accent" />
        <div className="mb-[30px] font-mono text-[11px] tracking-[.28em] text-muted">
          CONVERSATIONAL FOOTBALL ANALYST
        </div>
        <div className="flex w-full flex-col gap-[10px]">
          {EXAMPLE_PROMPTS.map((ex) => (
            <div
              key={ex.text}
              onClick={() => onExample(ex.text)}
              className="flex cursor-pointer items-center gap-[13px] rounded-[10px] border border-line bg-panel px-4 py-[14px] transition-colors hover:border-[rgba(52,211,153,.5)] hover:bg-[#1b2723]"
            >
              <span className="font-mono text-[13px] text-accent">→</span>
              <span className="text-[13.5px] leading-[1.4] text-fg">
                {ex.text}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function AnalysisCanvas({
  isMain,
  isEmpty,
  thinking,
  shots,
  annotate,
  onExample,
  imageSrc = null,
}: AnalysisCanvasProps) {
  return (
    <div className="relative flex min-w-0 flex-1 flex-col bg-ink">
      {isMain && (
        <ShotMapView
          thinking={thinking}
          shots={shots}
          annotate={annotate}
          imageSrc={imageSrc}
        />
      )}
      {isEmpty && <LandingView onExample={onExample} />}
    </div>
  );
}
