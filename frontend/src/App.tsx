import { useCallback, useRef, useState } from "react";
import Header from "./components/Header";
import ChatRail from "./components/ChatRail";
import AnalysisCanvas from "./components/AnalysisCanvas";
import {
  ChatError,
  deriveCanvasTitle,
  postChat,
  wasCorrected,
  type CitedStat,
} from "./api";
import { buildShots, type Message } from "./data";

type View = "main" | "empty";

const SHOW_OPPONENT = true;
const ANNOTATE = true;

function newSessionId(): string {
  return crypto.randomUUID();
}

export default function App() {
  const [view, setView] = useState<View>("main");
  const [fresh, setFresh] = useState(false);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [citedStats, setCitedStats] = useState<CitedStat[]>([]);
  const [canvasTitle, setCanvasTitle] = useState<string | null>(null);
  const sessionId = useRef(newSessionId());

  const send = useCallback(async (text: string) => {
    const t = text.trim();
    if (!t || thinking) return;

    setView("main");
    setInput("");
    setThinking(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", label: "YOU", showDot: false, text: t },
    ]);

    try {
      const res = await postChat(t, sessionId.current);
      const visual = res.visuals.length ? res.visuals[res.visuals.length - 1] : null;

      setImageSrc(visual);
      setCitedStats(res.cited_stats);
      setCanvasTitle(deriveCanvasTitle(res.cited_stats));

      setMessages((prev) => [
        ...prev,
        {
          role: "gaffer",
          label: "GAFFER",
          showDot: true,
          text: res.answer_text,
          grounded: res.grounded,
          corrected: wasCorrected(res.verification_notes),
          citedStats: res.cited_stats,
        },
      ]);
    } catch (err) {
      const msg =
        err instanceof ChatError
          ? err.message
          : "Could not reach Gaffer. Is the backend running?";
      setMessages((prev) => [
        ...prev,
        {
          role: "gaffer",
          label: "GAFFER",
          showDot: false,
          text: msg,
          error: true,
        },
      ]);
    } finally {
      setThinking(false);
    }
  }, [thinking]);

  const handleExample = useCallback(
    (text: string) => {
      setFresh(true);
      send(text);
    },
    [send],
  );

  const handleNewAnalysis = useCallback(() => {
    sessionId.current = newSessionId();
    setView("empty");
    setFresh(true);
    setThinking(false);
    setMessages([]);
    setImageSrc(null);
    setCitedStats([]);
    setCanvasTitle(null);
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
          messages={messages}
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
          imageSrc={imageSrc}
          citedStats={citedStats}
          canvasTitle={canvasTitle}
        />
      </div>
    </div>
  );
}
