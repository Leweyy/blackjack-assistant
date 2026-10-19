import { useEffect, useState } from "react";
import type { WindowSource } from "../../shared/types";
import { errorMessage } from "../common";

/** Dialog listing open windows with live thumbnails. */
export function WindowChooser(props: { selected: number | null; onPick: (w: WindowSource) => void; onClose: () => void }) {
  const [windows, setWindows] = useState<WindowSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  async function load() {
    setError(null);
    try {
      setWindows(await window.api.listWindows());
    } catch (e) {
      setError(errorMessage(e));
      setWindows([]);
    }
  }

  useEffect(() => {
    void load();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && props.onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = (windows ?? []).filter((w) => w.title.toLowerCase().includes(filter.trim().toLowerCase()));

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Choose a window">
        <header>
          <h3>Choose the window showing your table</h3>
          <input className="input" placeholder="Search windows…" value={filter} autoFocus
            onChange={(e) => setFilter(e.target.value)} aria-label="Search windows" />
          <button className="btn" onClick={() => { setWindows(null); void load(); }}>Refresh</button>
          <button className="btn" onClick={props.onClose} aria-label="Close">✕</button>
        </header>
        <div className="window-grid">
          {windows === null && <p className="empty">Looking for windows…</p>}
          {error && <p className="empty error">{error}</p>}
          {windows !== null && !error && shown.length === 0 && (
            <p className="empty">{windows.length ? "No windows match your search." : "No windows found. Open your blackjack game, then press Refresh."}</p>
          )}
          {shown.map((w) => (
            <button key={w.id} className={`window-card ${props.selected === w.handle ? "selected" : ""}`} onClick={() => props.onPick(w)}>
              <div className="thumb">{w.thumbnail ? <img src={w.thumbnail} alt="" /> : <span>No preview</span>}</div>
              <div className="title">
                {w.icon && <img src={w.icon} alt="" />}
                <span title={w.title}>{w.title}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
