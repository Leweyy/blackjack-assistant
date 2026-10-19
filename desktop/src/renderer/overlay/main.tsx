import { StrictMode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Advice } from "../../shared/types";
import { adviceColor, errorMessage } from "../common";
import "../styles.css";

const STARTING: Advice = {
  headline: "Starting…", detail: "", action: null, count_line: "", bet_units: null, reason: "",
  player_cards: [], dealer_cards: [], player_total: "", dealer_total: "", hand_label: "",
};

const SUITS = "♠♥♦♣";

/** "9♥" -> a small card showing ♥9; cards read without a suit show the rank alone. */
function CardChip({ card }: { card: string }) {
  const text = card.trim();
  const suit = SUITS.includes(text.slice(-1)) ? text.slice(-1) : "";
  const rank = suit ? text.slice(0, -1).trim() : text;
  const red = suit === "♥" || suit === "♦";
  return (
    <span className={`card-chip ${red ? "red" : ""}`} aria-label={card}>
      {suit && <span className="suit">{suit}</span>}
      <span className="rank">{rank}</span>
    </span>
  );
}

function HandRow({ label, note, cards, total }: { label: string; note?: string; cards: string[]; total: string }) {
  return (
    <div className="hand-row">
      <div className="hand-label">{label}{note && <small>{note}</small>}</div>
      <div className="hand-cards">{cards.map((c, i) => <CardChip key={`${c}-${i}`} card={c} />)}</div>
      {total && <div className="hand-total">{total}</div>}
    </div>
  );
}

function Overlay() {
  const [advice, setAdvice] = useState<Advice>(STARTING);
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

  async function markSeat() {
    try {
      const seat = await window.api.markSeat();
      if (seat) {
        setStatus("Seat marked ✓");
        setError(false);
      }
    } catch (e) {
      setStatus(errorMessage(e));
      setError(true);
    }
  }

  const showHands = advice.player_cards.length > 0 || advice.dealer_cards.length > 0;
  return (
    <div className="overlay" ref={cardRef}>
      <div key={pulse} className={`headline ${pulse ? "pulse" : ""}`} style={{ background: adviceColor(advice.action, advice.bet_units) }}>
        {advice.headline}
      </div>
      {advice.reason && <div className="reason">{advice.reason}</div>}
      {showHands && (
        <div className="hands">
          {advice.player_cards.length > 0 && (
            <HandRow label="You" note={advice.hand_label} cards={advice.player_cards} total={advice.player_total} />
          )}
          {advice.dealer_cards.length > 0 && (
            <HandRow label="Dealer" cards={advice.dealer_cards} total={advice.dealer_total} />
          )}
        </div>
      )}
      {advice.count_line && <div className="count">{advice.count_line}</div>}
      <footer className="footer">
        <div className={`status ${error ? "error" : ""}`} title={status}>{status}</div>
        <button className="icon-btn" title="Drag a box around your cards so only they are used for advice" onClick={markSeat}>📍 Seat</button>
        {advice.count_line && <button className="icon-btn" title="Reset the count for a new shoe (R)" onClick={resetCount}>↺ Shoe</button>}
        <button className="icon-btn" title="Stop (Esc)" onClick={() => window.api.closeOverlay()}>✕</button>
      </footer>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Overlay />
  </StrictMode>,
);
