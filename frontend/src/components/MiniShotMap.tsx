import {
  ACCENT,
  AMBER,
  MATCH,
  OPPONENT_SHOTS,
  SUBJECT_SHOTS,
  type RawShot,
} from "../data";

// The mini card uses a 260x116 viewBox with the pitch inset at (6,6)–(254,110);
// map the full 1050x680 design-space shot coords into it.
const mx = (cx: number) => 6 + (cx / 1050) * 248;
const my = (cy: number) => 6 + (cy / 680) * 104;

function MiniMarkers({ shots, color }: { shots: RawShot[]; color: string }) {
  return (
    <>
      {shots.map((s, i) => (
        <circle
          key={i}
          cx={mx(s.cx)}
          cy={my(s.cy)}
          r={2 + s.xg * 6}
          fill={s.goal ? color : "none"}
          stroke={color}
          strokeWidth={s.goal ? 0 : 1.6}
          fillOpacity={s.goal ? 0.85 : 0}
          strokeOpacity={0.65}
        />
      ))}
    </>
  );
}

// Compact inline shot-map card shown inside a Gaffer chat bubble.
export default function MiniShotMap() {
  const abbr = (team: string) => team.slice(0, 3).toUpperCase();
  return (
    <div className="mt-[5px] cursor-pointer overflow-hidden rounded-[9px] border border-line bg-panel transition-colors hover:border-[rgba(52,211,153,.45)]">
      <svg
        viewBox="0 0 260 116"
        style={{ display: "block", width: "100%", height: "auto", background: "#0E1512" }}
      >
        <g
          stroke="#E8EDEB"
          strokeOpacity=".14"
          strokeWidth="1.2"
          fill="none"
          strokeLinecap="round"
        >
          <rect x="6" y="6" width="248" height="104" rx="2" />
          <line x1="130" y1="6" x2="130" y2="110" />
          <circle cx="130" cy="58" r="20" />
          <rect x="6" y="32" width="34" height="52" />
          <rect x="220" y="32" width="34" height="52" />
        </g>
        <MiniMarkers shots={SUBJECT_SHOTS} color={ACCENT} />
        <MiniMarkers shots={OPPONENT_SHOTS} color={AMBER} />
      </svg>
      <div className="flex items-center justify-between border-t border-line px-[10px] py-[7px] font-mono text-[9.5px] tracking-[.08em] text-muted">
        <span>
          SHOT MAP · {abbr(MATCH.subject)} vs {abbr(MATCH.opponent)}
        </span>
        <span className="text-accent">EXPAND ↗</span>
      </div>
    </div>
  );
}
