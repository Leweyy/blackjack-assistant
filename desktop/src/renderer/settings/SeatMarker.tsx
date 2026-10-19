import { useEffect, useState } from "react";
import type { CapturePreview } from "../../shared/types";
import { errorMessage } from "../common";

/** Dialog showing a snapshot of the watched area; the user clicks on their own cards. */
export function SeatMarker(props: {
  initial: [number, number] | null;
  onSave: (seat: [number, number]) => void;
  onClose: () => void;
}) {
  const [preview, setPreview] = useState<CapturePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seat, setSeat] = useState<[number, number] | null>(props.initial);

  async function load() {
    setError(null);
    setPreview(null);
    try {
      setPreview(await window.api.capturePreview());
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  useEffect(() => {
    void load();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && props.onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function onClick(e: React.MouseEvent<HTMLImageElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    setSeat([Number(x.toFixed(4)), Number(y.toFixed(4))]);
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Mark your seat">
        <header>
          <h3>Click on your cards</h3>
          <button className="btn" onClick={() => void load()}>Retake snapshot</button>
          <button className="btn primary" disabled={!seat || !preview} onClick={() => seat && props.onSave(seat)}>Save</button>
          <button className="btn" onClick={props.onClose} aria-label="Close">✕</button>
        </header>
        <div className="seat-body">
          <p className="lead">
            Open the table with cards dealt (or your seat taken), then click where <b>your</b> cards appear.
            Only the cards at this spot will be used for advice; everyone else’s still count towards the card count.
          </p>
          {!preview && !error && <p className="empty">Taking a snapshot of what’s being watched…</p>}
          {error && <p className="empty error">{error}</p>}
          {preview && (
            <div className="seat-canvas">
              <img src={preview.image} alt="Snapshot of the watched area" onClick={onClick} draggable={false} />
              {seat && (
                <div className="seat-ring" style={{
                  left: `${seat[0] * 100}%`, top: `${seat[1] * 100}%`,
                  // Same size as the ring the backend draws: radius = 12% of the shorter side.
                  width: `${(24 * Math.min(preview.width, preview.height)) / preview.width}%`,
                }}>
                  <span>YOU</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
