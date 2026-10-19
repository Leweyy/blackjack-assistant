import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";

interface Point { x: number; y: number }

const seatMode = new URLSearchParams(window.location.search).get("mode") === "seat";

function Picker() {
  const [start, setStart] = useState<Point | null>(null);
  const [end, setEnd] = useState<Point | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && window.api.pickerDone(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const rect = start && end ? {
    x: Math.min(start.x, end.x), y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x), height: Math.abs(end.y - start.y),
  } : null;

  return (
    <div
      className={`picker ${rect ? "selecting" : ""} ${seatMode ? "seat" : ""}`}
      onContextMenu={(e) => { e.preventDefault(); window.api.pickerDone(null); }}
      onMouseDown={(e) => { if (e.button === 0) { setStart({ x: e.clientX, y: e.clientY }); setEnd({ x: e.clientX, y: e.clientY }); } }}
      onMouseMove={(e) => start && setEnd({ x: e.clientX, y: e.clientY })}
      onMouseUp={() => {
        if (!rect) return;
        if (rect.width < 20 || rect.height < 20) { setStart(null); setEnd(null); return; }
        window.api.pickerDone(rect);
      }}
    >
      {rect && (
        <>
          <div className="selection" style={{ left: rect.x, top: rect.y, width: rect.width, height: rect.height }} />
          <div className="size" style={{ left: rect.x, top: rect.y }}>
            {Math.round(rect.width * window.devicePixelRatio)} × {Math.round(rect.height * window.devicePixelRatio)}
          </div>
        </>
      )}
      <div className="hint">
        {seatMode
          ? <>Drag a box around <b>your</b> cards only, leaving room for extra cards · Esc to cancel</>
          : <>Drag a box around the blackjack table · Esc to cancel</>}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Picker />
  </StrictMode>,
);
