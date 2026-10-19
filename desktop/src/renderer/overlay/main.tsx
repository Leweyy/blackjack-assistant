import { StrictMode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Advice } from "../../shared/types";
import { adviceColor } from "../common";
import "../styles.css";

function Overlay() {
  const [advice, setAdvice] = useState<Advice>({ headline: "Starting…", detail: "", action: null, count_line: "", bet_units: null });
  const [status, setStatus] = useState("Watching your screen…");
  const [error, setError] = useState(false);
  const [pulse, setPulse] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => window.api.onEvent((e) => {
    if (e.event === "advice") {
      setAdvice(e.data);
      setError(false);
      if (e.data.action || (e.data.bet_units ?? 0) > 1) setPulse((p) => p + 1);
    } else if (e.event === "status") {
      setStatus(e.data);
      setError(false);
    } else if (e.event === "error") {
      setStatus(e.data);
      setError(true);
    }
  }), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") window.api.closeOverlay();
      if (e.key.toLowerCase() === "r") resetCount();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Size the transparent window to fit the card.
  useLayoutEffect(() => {
    const el = cardRef.current?.parentElement; // #root, which pads the card for its shadow
    if (!el) return;
    const ro = new ResizeObserver(() => window.api.resizeOverlay(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  function resetCount() {
    void window.api.request("reset_count");
    setStatus("Count reset for a new shoe");
    setError(false);
  }

  return (
    <div className="overlay" ref={cardRef}>
      <div key={pulse} className={`headline ${pulse ? "pulse" : ""}`} style={{ background: adviceColor(advice.action, advice.bet_units) }}>
        {advice.headline}
      </div>
      {advice.detail && <div className="detail">{advice.detail}</div>}
      {advice.count_line && <div className="count">{advice.count_line}</div>}
      <div className="footer">
        <div className={`status ${error ? "error" : ""}`} title={status}>{status}</div>
        {advice.count_line && <button className="icon-btn" title="Reset the count for a new shoe (R)" onClick={resetCount}>↺ New shoe</button>}
        <button className="icon-btn" title="Stop (Esc)" onClick={() => window.api.closeOverlay()}>✕</button>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Overlay />
  </StrictMode>,
);
