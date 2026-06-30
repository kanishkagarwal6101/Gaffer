import { useCallback, useRef, useState } from "react";
import Header from "./components/Header";
import ChatRail from "./components/ChatRail";
import AnalysisCanvas from "./components/AnalysisCanvas";
import { buildShots, GAFFER_REPLY, type Message } from "./data";

type View = "main" | "empty";

// Opponent shots + the goal annotation are always on in v1 (editor props in the
// original export). Backend wiring will make these dynamic later.
const SHOW_OPPONENT = true;
const ANNOTATE = true;

export default function App() {
  const [view, setView] = useState<View>("main");
  const [fresh, setFresh] = useState(false);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [extra, setExtra] = useState<Message[]>([]);
  const replyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const send = useCallback((text: string) => {
    const t = text.trim();
    if (!t) return;

    setView("main");
    setInput("");
    setThinking(true);
    setExtra((prev) => [
      ...prev,
      { role: "user", label: "YOU", showDot: false, text: t },
    ]);

    if (replyTimer.current) clearTimeout(replyTimer.current);
    replyTimer.current = setTimeout(() => {
      setThinking(false);
      setExtra((prev) => [
        ...prev,
        { role: "gaffer", label: "GAFFER", showDot: true, text: GAFFER_REPLY },
      ]);
    }, 2000);
  }, []);

  const handleExample = useCallback(
    (text: string) => {
      setFresh(true);
      send(text);
    },
    [send],
  );

  const handleNewAnalysis = useCallback(() => {
    if (replyTimer.current) clearTimeout(replyTimer.current);
    setView("empty");
    setFresh(true);
    setThinking(false);
    setExtra([]);
  }, []);

  const isMain = view === "main";
  const isEmpty = view === "empty";
  const showPrebaked = view === "main" && !fresh;
  const shots = buildShots(SHOW_OPPONENT);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-ink font-body text-fg">
      <Header onNewAnalysis={handleNewAnalysis} />

      <div className="flex min-h-0 flex-1">
        <ChatRail
          isEmpty={isEmpty}
          showPrebaked={showPrebaked}
          messages={extra}
          thinking={thinking}
          input={input}
          onInput={setInput}
          onSend={() => send(input)}
        />
        <AnalysisCanvas
          isMain={isMain}
          isEmpty={isEmpty}
          thinking={thinking}
          shots={shots}
          annotate={ANNOTATE}
          onExample={handleExample}
        />
      </div>
    </div>
  );
}
