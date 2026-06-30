import { COMPETITION } from "../data";

interface HeaderProps {
  onNewAnalysis: () => void;
}

export default function Header({ onNewAnalysis }: HeaderProps) {
  return (
    <div className="flex h-[54px] flex-none items-center gap-4 border-b border-line pl-5 pr-[18px]">
      <div className="flex items-center gap-[9px]">
        <div className="h-[9px] w-[9px] rounded-[2px] bg-accent" />
        <div className="font-display text-[17px] font-bold tracking-[.2em] text-fg">
          GAFFER
        </div>
      </div>

      <div className="h-[18px] w-px bg-line" />

      <div className="font-mono text-[11px] tracking-[.07em] text-muted">
        {COMPETITION}
      </div>

      <div className="flex-1" />

      <div className="flex items-center gap-2 font-mono text-[10.5px] tracking-[.08em] text-muted">
        <span
          className="h-1.5 w-1.5 rounded-full bg-accent"
          style={{ animation: "gpulse 2.4s ease-in-out infinite" }}
        />
        GAFFER-TACTICAL v3 · READY
      </div>

      <button
        onClick={onNewAnalysis}
        className="ml-[6px] flex items-center gap-[6px] rounded-[7px] border border-line bg-transparent px-[11px] py-[6px] font-body text-xs text-fg transition-colors hover:border-edge hover:bg-panel"
      >
        <span className="text-[13px] leading-none text-accent">+</span> New
        analysis
      </button>
    </div>
  );
}
