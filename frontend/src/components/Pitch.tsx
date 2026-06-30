import { useState } from "react";
import { TOP_CHANCE, type ShotMarker } from "../data";

interface PitchProps {
  shots: ShotMarker[];
  annotate: boolean;
}

// Tooltip rendered in SVG user space so it scales with the board.
function ShotTooltip({ shot }: { shot: ShotMarker }) {
  const title = shot.player.toUpperCase();
  const sub = `${shot.minute}' · ${shot.xg.toFixed(2)} xG · ${shot.outcome.toUpperCase()}`;

  const padX = 16;
  const padY = 13;
  const titleSize = 21;
  const subSize = 16.5;
  const lineGap = 9;
  const boxW = Math.round(
    padX * 2 + Math.max(title.length * 12.6, sub.length * 9.9),
  );
  const boxH = padY * 2 + titleSize + lineGap + subSize;

  // Prefer above the marker; flip below when it would clip the top edge.
  let x = shot.cx - boxW / 2;
  x = Math.max(6, Math.min(x, 1050 - boxW - 6));
  let y = shot.cy - shot.r - 14 - boxH;
  if (y < 6) y = shot.cy + shot.r + 14;

  const titleBaseline = y + padY + titleSize - 3;
  const subBaseline = titleBaseline + lineGap + subSize;

  return (
    <g style={{ pointerEvents: "none" }}>
      <rect
        x={x}
        y={y}
        width={boxW}
        height={boxH}
        rx={9}
        fill="#18211E"
        stroke={shot.stroke}
        strokeOpacity={0.6}
        strokeWidth={1.5}
      />
      <text
        x={x + padX}
        y={titleBaseline}
        fill={shot.stroke}
        fontFamily="Space Grotesk, sans-serif"
        fontSize={titleSize}
        fontWeight={600}
        letterSpacing="0.5"
      >
        {title}
      </text>
      <text
        x={x + padX}
        y={subBaseline}
        fill="#ECF2EF"
        fontFamily="JetBrains Mono, monospace"
        fontSize={subSize}
        letterSpacing="0.5"
      >
        {sub}
      </text>
    </g>
  );
}

// Chalk-line pitch + shot markers — pitch geometry copied verbatim from the
// design export; markers and the top-chance annotation come from real data.
// Each marker is interactive: hover to preview, click to pin a tooltip.
export default function Pitch({ shots, annotate }: PitchProps) {
  const [hovered, setHovered] = useState<number | null>(null);
  const [pinned, setPinned] = useState<number | null>(null);

  const activeIndex = pinned ?? hovered;
  const active = activeIndex !== null ? shots[activeIndex] : null;

  return (
    <svg
      viewBox="-30 -30 1110 740"
      style={{ width: "100%", maxWidth: 800, height: "auto", maxHeight: "100%" }}
      onClick={() => setPinned(null)}
    >
      <rect x="0" y="0" width="1050" height="680" fill="#0E1512" />
      <g
        stroke="#E8EDEB"
        strokeOpacity=".14"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="0" y="0" width="1050" height="680" />
        <line x1="525" y1="0" x2="525" y2="680" />
        <circle cx="525" cy="340" r="91.5" />
        <rect x="0" y="138.5" width="165" height="403" />
        <rect x="0" y="248" width="55" height="184" />
        <path d="M165,267 A91.5,91.5 0 0 1 165,413" />
        <rect x="885" y="138.5" width="165" height="403" />
        <rect x="995" y="248" width="55" height="184" />
        <path d="M885,267 A91.5,91.5 0 0 0 885,413" />
        <rect x="-12" y="303.5" width="12" height="73" />
        <rect x="1050" y="303.5" width="12" height="73" />
      </g>
      <g fill="#E8EDEB" fillOpacity=".16" stroke="none">
        <circle cx="110" cy="340" r="3" />
        <circle cx="940" cy="340" r="3" />
        <circle cx="525" cy="340" r="3.5" />
      </g>

      {annotate && (
        <>
          <line
            x1={TOP_CHANCE.cx}
            y1={TOP_CHANCE.cy}
            x2="858"
            y2="592"
            stroke="#34D399"
            strokeWidth="1.4"
            strokeOpacity=".45"
          />
          <circle cx="858" cy="592" r="2.5" fill="#34D399" stroke="none" />
          <text
            x="845"
            y="598"
            textAnchor="end"
            fill="#34D399"
            fillOpacity=".95"
            fontFamily="JetBrains Mono, monospace"
            fontSize="16.5"
            letterSpacing="0.5"
          >
            {TOP_CHANCE.label}
          </text>
        </>
      )}

      {shots.map((s, i) => {
        const isActive = i === activeIndex;
        return (
          <g key={i}>
            <circle
              cx={s.cx}
              cy={s.cy}
              r={s.r}
              fill={s.fill}
              stroke={s.stroke}
              strokeWidth={s.strokeWidth}
              fillOpacity={s.fillOpacity}
              strokeOpacity={isActive ? 1 : s.strokeOpacity}
            />
            {/* Transparent hit target so even small/hollow markers are easy to grab. */}
            <circle
              cx={s.cx}
              cy={s.cy}
              r={Math.max(s.r, 18)}
              fill="#000"
              fillOpacity={0}
              style={{ cursor: "pointer" }}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered((h) => (h === i ? null : h))}
              onClick={(e) => {
                e.stopPropagation();
                setPinned((p) => (p === i ? null : i));
              }}
            />
          </g>
        );
      })}

      {active && <ShotTooltip shot={active} />}
    </svg>
  );
}
