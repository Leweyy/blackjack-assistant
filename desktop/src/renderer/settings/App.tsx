import { useCallback, useEffect, useRef, useState } from "react";
import type { Advice, CaptureMode, ChosenWindow, Region, ScreenshotResult, Settings, SettingsInfo } from "../../shared/types";
import { adviceColor, errorMessage } from "../common";
import { Card, icons, Row, Stepper, ToggleRow } from "./components";
import { SeatMarker } from "./SeatMarker";
import { WindowChooser } from "./WindowChooser";

type Page = "rules" | "counting" | "screen" | "connection";

const PAGES: { id: Page; label: string }[] = [
  { id: "rules", label: "Table rules" },
  { id: "counting", label: "Counting & bets" },
  { id: "screen", label: "Screen" },
  { id: "connection", label: "Connection" },
];

const MODELS = [
  { id: "claude-opus-5-5", name: "Claude Opus 5.5", hint: "Most accurate card reading", tag: "Recommended" },
  { id: "claude-sonnet-5-5", name: "Claude Sonnet 5.5", hint: "Good accuracy, about half the cost", tag: "Balanced" },
  { id: "claude-haiku-5-5", name: "Claude Haiku 5.5", hint: "Far cheaper, may misread cards more often", tag: "Cheapest" },
];

/** Settings as edited in the form: numbers stay as text until saved. */
interface Form {
  api_key: string;
  model: string;
  interval: string;
  monitor: string;
  capture: CaptureMode;
  region: Region | null;
  window: ChosenWindow | null;
  seat: [number, number] | null;
  dealer_hits_soft_17: boolean;
  double_after_split: boolean;
  surrender_allowed: boolean;
  counting: boolean;
  decks: string;
  unit: string;
  max_units: string;
}

function toForm(s: Settings): Form {
  return {
    ...s,
    interval: String(s.interval),
    monitor: String(s.monitor),
    decks: String(s.decks),
    unit: s.unit == null ? "" : String(s.unit),
    max_units: String(s.max_units),
  };
}

type Invalid = Partial<Record<keyof Form, true>>;

function fromForm(f: Form): { settings?: Settings; invalid: Invalid } {
  const invalid: Invalid = {};
  const int = (key: keyof Form, min: number, max: number) => {
    const n = Number(f[key]);
    if (!Number.isInteger(n) || n < min || n > max) invalid[key] = true;
    return n;
  };
  const decks = int("decks", 1, 8);
  const maxUnits = int("max_units", 1, 1000);
  const monitor = int("monitor", 1, 16);
  const interval = Number(f.interval);
  if (!Number.isFinite(interval) || interval < 0.5 || interval > 60) invalid.interval = true;
  const unit = f.unit.trim() === "" ? null : Number(f.unit);
  if (unit !== null && (!Number.isFinite(unit) || unit <= 0)) invalid.unit = true;
  if (Object.keys(invalid).length) return { invalid };
  return {
    invalid,
    settings: {
      api_key: f.api_key.trim(), model: f.model.trim() || MODELS[0].id, interval, monitor,
      capture: f.capture, region: f.region, window: f.window, seat: f.seat,
      dealer_hits_soft_17: f.dealer_hits_soft_17, double_after_split: f.double_after_split,
      surrender_allowed: f.surrender_allowed, counting: f.counting, decks, unit, max_units: maxUnits,
    },
  };
}

type SaveState = { kind: "idle" | "saving" | "saved" } | { kind: "error"; message: string };

export default function App() {
  const [page, setPage] = useState<Page>("rules");
  const [info, setInfo] = useState<SettingsInfo | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [saveState, setSaveState] = useState<SaveState>({ kind: "idle" });
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Loading…");
  const [error, setError] = useState<string | null>(null);
  const [lastAdvice, setLastAdvice] = useState<Advice | null>(null);
  const lastSaved = useRef<string>("");

  // ---- load + live events ----
  useEffect(() => {
    window.api.request<SettingsInfo>("get_settings")
      .then((i) => {
        setInfo(i);
        setForm(toForm(i.settings));
        lastSaved.current = JSON.stringify(i.settings);
        const hasKey = i.settings.api_key || i.env_api_key;
        setStatus(hasKey ? "Ready. Open your blackjack table, then press Start." : "Add your Anthropic API key to get started.");
        if (!hasKey) setPage("connection");
      })
      .catch((e) => setError(errorMessage(e)));
    window.api.isRunning().then(setRunning);
    const offSession = window.api.onSessionChange((r) => {
      setRunning(r);
      if (!r) setStatus("Stopped.");
    });
    const offEvent = window.api.onEvent((e) => {
      if (e.event === "status") setStatus(e.data);
      else if (e.event === "error") setError(e.data);
      else if (e.event === "advice") {
        setLastAdvice(e.data);
        setError(null);
      }
    });
    return () => { offSession(); offEvent(); };
  }, []);

  // ---- auto-save ----
  const parsed = form ? fromForm(form) : null;
  const save = useCallback(async (settings: Settings) => {
    const json = JSON.stringify(settings);
    if (json === lastSaved.current) return true;
    setSaveState({ kind: "saving" });
    try {
      await window.api.request("save_settings", { settings });
      lastSaved.current = json;
      setSaveState({ kind: "saved" });
      return true;
    } catch (e) {
      setSaveState({ kind: "error", message: errorMessage(e) });
      return false;
    }
  }, []);

  useEffect(() => {
    if (!parsed?.settings) return;
    const settings = parsed.settings;
    const t = setTimeout(() => void save(settings), 400);
    return () => clearTimeout(t);
  }, [JSON.stringify(parsed?.settings), save]); // eslint-disable-line react-hooks/exhaustive-deps

  const update = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => {
    if (!f) return f;
    const next = { ...f, [key]: value };
    // A marked seat is a spot in the captured image, so it's stale once the framing changes.
    const reframed = (key === "capture" || key === "region" || key === "window")
      && JSON.stringify(f[key]) !== JSON.stringify(value);
    if (reframed) next.seat = null;
    return next;
  });

  // ---- actions ----
  async function start() {
    if (!parsed?.settings) {
      setError("Fix the highlighted settings first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (!(await save(parsed.settings))) return;
      await window.api.startSession();
      setStatus("Watching your screen…");
    } catch (e) {
      setError(errorMessage(e));
      if (/API key/i.test(errorMessage(e))) setPage("connection");
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      await window.api.stopSession();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (!form || !info) {
    return (
      <div className="app">
        <TitleBar />
        <div className="hero"><div className="state"><h1>Blackjack Assistant</h1><p className={error ? "error" : ""}>{error ?? status}</p></div></div>
      </div>
    );
  }

  const invalid = parsed?.invalid ?? {};
  return (
    <div className="app">
      <TitleBar />

      <section className="hero">
        <div className="state">
          <h1><span className={`dot ${running ? "on" : ""}`} />{running ? "Running" : "Not running"}</h1>
          {error ? <p className="error">{error}</p> : <p>{status}</p>}
          {running && lastAdvice && (
            <p style={{ marginTop: 6 }}>
              Last advice: <b style={{ color: "#fff", background: adviceColor(lastAdvice.action, lastAdvice.bet_units), padding: "1px 8px", borderRadius: 6 }}>{lastAdvice.headline}</b>
              {lastAdvice.count_line && <> · {lastAdvice.count_line}</>}
            </p>
          )}
        </div>
        {running
          ? <button className="btn stop big" disabled={busy} onClick={stop}>■ Stop</button>
          : <button className="btn primary big" disabled={busy} onClick={start}>▶ Start</button>}
      </section>

      <div className="body">
        <nav className="nav">
          {PAGES.map((p) => (
            <button key={p.id} className={page === p.id ? "active" : ""} onClick={() => setPage(p.id)}>
              {icons[p.id]}{p.label}
            </button>
          ))}
          <div className={`save-state ${saveState.kind === "error" ? "error" : ""}`}>
            {saveState.kind === "saving" && "Saving…"}
            {saveState.kind === "saved" && "✓ All changes saved"}
            {saveState.kind === "error" && saveState.message}
          </div>
        </nav>

        <main className="content">
          {running && <div className="banner">Settings are locked while running. Press Stop to change them.</div>}
          {Object.keys(invalid).length > 0 && <div className="banner error">Some values aren’t valid yet. Check the highlighted fields.</div>}
          <fieldset disabled={running}>
            {page === "rules" && <RulesPage form={form} update={update} />}
            {page === "counting" && <CountingPage form={form} update={update} invalid={invalid} />}
            {page === "screen" && <ScreenPage form={form} update={update} invalid={invalid} />}
            {page === "connection" && <ConnectionPage form={form} update={update} info={info} />}
          </fieldset>
        </main>
      </div>
    </div>
  );
}

function TitleBar() {
  return (
    <header className="titlebar">
      <div className="logo">21</div>
      Blackjack Assistant
    </header>
  );
}

type PageProps = { form: Form; update: <K extends keyof Form>(key: K, value: Form[K]) => void };

function RulesPage({ form, update }: PageProps) {
  return (
    <>
      <h2>Table rules</h2>
      <p className="lead">Match these to the table you’re playing. They’re usually printed on the felt or in the game’s help screen.</p>
      <Card>
        <ToggleRow title="Dealer hits soft 17" hint="“Dealer must stand on all 17s” means leave this off."
          checked={form.dealer_hits_soft_17} onChange={(v) => update("dealer_hits_soft_17", v)} />
        <ToggleRow title="Double after split" hint="You can double down on a hand after splitting."
          checked={form.double_after_split} onChange={(v) => update("double_after_split", v)} />
        <ToggleRow title="Surrender offered" hint="Many live-dealer tables don’t offer surrender."
          checked={form.surrender_allowed} onChange={(v) => update("surrender_allowed", v)} />
      </Card>
    </>
  );
}

function CountingPage({ form, update, invalid }: PageProps & { invalid: Invalid }) {
  return (
    <>
      <h2>Counting & bets</h2>
      <p className="lead">Hi-Lo card counting for live-dealer games dealt from a shoe.</p>
      <Card>
        <ToggleRow title="Count cards" hint="Turn off for computer-dealt games that shuffle every hand: counting can’t help there."
          checked={form.counting} onChange={(v) => update("counting", v)} />
        <Row title="Decks in the shoe" hint="Most live tables use 8. Used to turn the running count into the true count.">
          <Stepper label="decks" value={form.decks} min={1} max={8} onChange={(v) => update("decks", v)} />
        </Row>
      </Card>
      <Card>
        <Row title="Betting unit" hint="Optional. Your minimum bet in money, so advice shows amounts like “Bet 4 units (40)”.">
          <input className={`input small ${invalid.unit ? "invalid" : ""}`} placeholder="e.g. 10" inputMode="decimal"
            value={form.unit} onChange={(e) => update("unit", e.target.value)} aria-label="Betting unit" />
        </Row>
        <Row title="Maximum bet" hint="Your bet spread. Minimum bet until the true count reaches +2, then 2 units for each extra +1, up to this.">
          <Stepper label="maximum bet in units" value={form.max_units} min={1} max={100} onChange={(v) => update("max_units", v)} />
          <span className="suffix">units</span>
        </Row>
      </Card>
    </>
  );
}

const CAPTURE_OPTIONS: { id: CaptureMode; label: string; hint: string }[] = [
  { id: "window", label: "A window", hint: "Follows the game window when you move or resize it" },
  { id: "region", label: "Table area", hint: "A fixed rectangle on your screen" },
  { id: "monitor", label: "Whole monitor", hint: "Everything on one monitor" },
];

function ScreenPage({ form, update, invalid }: PageProps & { invalid: Invalid }) {
  const [picking, setPicking] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [markingSeat, setMarkingSeat] = useState(false);
  const windowsSupported = window.api.platform === "win32";

  async function pick() {
    setPicking(true);
    try {
      const region = await window.api.pickRegion();
      if (region) update("region", region);
    } finally {
      setPicking(false);
    }
  }
  const r = form.region;
  const sw = window.screen.width * window.devicePixelRatio;
  const sh = window.screen.height * window.devicePixelRatio;
  const pct = (v: number, total: number) => Math.max(0, Math.min(100, (v / total) * 100));

  return (
    <>
      <h2>Screen</h2>
      <p className="lead">Tell the assistant where your blackjack table is.</p>
      <Card>
        <div className="segmented" role="radiogroup" aria-label="What to watch">
          {CAPTURE_OPTIONS.map((o) => {
            const disabled = o.id === "window" && !windowsSupported;
            return (
              <button key={o.id} type="button" role="radio" aria-checked={form.capture === o.id} disabled={disabled}
                className={form.capture === o.id ? "selected" : ""} onClick={() => update("capture", o.id)}
                title={disabled ? "Window capture is only available on Windows" : o.hint}>
                <strong>{o.label}</strong>
                <span>{disabled ? "Windows only" : o.hint}</span>
              </button>
            );
          })}
        </div>

        {form.capture === "window" && (
          <Row title={form.window ? form.window.title : "No window chosen"}
            hint="Pick the browser or casino app window showing the table. Keep it visible (not minimised); the advice overlay is hidden from captures, so it can sit on top.">
            <button className="btn primary" onClick={() => setChoosing(true)}>{form.window ? "Change window" : "Choose window"}</button>
          </Row>
        )}

        {form.capture === "region" && (
          <>
            <div className="region-preview">
              <div className="screen" aria-hidden>
                {r && <div className="area" style={{
                  left: `${pct(r[0], sw)}%`, top: `${pct(r[1], sh)}%`,
                  width: `${Math.min(100 - pct(r[0], sw), pct(r[2], sw))}%`, height: `${Math.min(100 - pct(r[1], sh), pct(r[3], sh))}%`,
                }} />}
              </div>
              <div className="info">
                <strong>{r ? `Table area: ${r[2]} × ${r[3]} px` : "No area selected yet"}</strong>
                <span>Cover the whole table, including other players’ seats so every card can be counted. A smaller area is also cheaper and more accurate.</span>
              </div>
            </div>
            <Row title="Table area" hint={r ? `Starts at (${r[0]}, ${r[1]}) on your desktop.` : "Drag a box around the table on screen."}>
              <button className="btn primary" disabled={picking} onClick={pick}>{r ? "Select again" : "Select table area"}</button>
            </Row>
          </>
        )}

        {form.capture === "monitor" && (
          <Row title="Monitor" hint="Which monitor to watch. A window or table area is cheaper and more accurate.">
            <Stepper label="monitor" value={form.monitor} min={1} max={6} onChange={(v) => update("monitor", v)} />
          </Row>
        )}
      </Card>
      <Card>
        <Row title="Your seat"
          hint={form.seat
            ? "Marked. A “YOU” ring is drawn at your seat on every screenshot so only your cards are used for advice. Mark it again if the table layout changes."
            : "Detected automatically. If the advice follows another player’s hand, mark your seat so the assistant knows which cards are yours."}>
          {form.seat && <button className="btn" onClick={() => update("seat", null)}>Detect automatically</button>}
          <button className="btn primary" onClick={() => setMarkingSeat(true)}>{form.seat ? "Mark again" : "Mark my seat"}</button>
        </Row>
      </Card>
      <Card>
        <Row title="Check every" hint="Each check of a live video feed is one API call. 3 seconds roughly halves the cost of 1.5; counting still works because rounds are counted when they finish.">
          <span style={{ outline: invalid.interval ? "1px solid var(--danger)" : undefined, borderRadius: 8 }}>
            <Stepper label="seconds between checks" value={form.interval} min={0.5} max={10} step={0.5} onChange={(v) => update("interval", v)} />
          </span>
          <span className="suffix">seconds</span>
        </Row>
      </Card>
      {markingSeat && (
        <SeatMarker
          initial={form.seat}
          onSave={(seat) => { update("seat", seat); setMarkingSeat(false); }}
          onClose={() => setMarkingSeat(false)}
        />
      )}
      {choosing && (
        <WindowChooser
          selected={form.window?.handle ?? null}
          onPick={(w) => { update("window", { handle: w.handle, title: w.title }); setChoosing(false); }}
          onClose={() => setChoosing(false)}
        />
      )}
    </>
  );
}

function ConnectionPage({ form, update, info }: PageProps & { info: SettingsInfo }) {
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ScreenshotResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  async function test() {
    const path = await window.api.openImage();
    if (!path) return;
    setTesting(true);
    setResult(null);
    setTestError(null);
    try {
      await new Promise((r) => setTimeout(r, 450)); // let a just-typed key auto-save first
      setResult(await window.api.request<ScreenshotResult>("test_screenshot", { path }));
    } catch (e) {
      setTestError(errorMessage(e));
    } finally {
      setTesting(false);
    }
  }

  const t = result?.table;
  return (
    <>
      <h2>Connection</h2>
      <p className="lead">The assistant uses Claude to read the cards on your screen.</p>
      <Card>
        <div className="row" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
          <div className="label">
            <strong>Anthropic API key</strong>
            <span>
              Create one in the <a onClick={() => window.api.openExternal("https://console.anthropic.com/settings/keys")}>Anthropic Console</a>.
              {info.env_api_key && !form.api_key && " Currently using the ANTHROPIC_API_KEY environment variable."}
            </span>
          </div>
          <div className="key-row">
            <input className="input" type={showKey ? "text" : "password"} placeholder="sk-ant-…" spellCheck={false}
              value={form.api_key} onChange={(e) => update("api_key", e.target.value)} aria-label="Anthropic API key" />
            <button className="btn" type="button" onClick={() => setShowKey((s) => !s)}>{showKey ? "Hide" : "Show"}</button>
          </div>
          <div className="mono">Saved on this PC in {info.config_path}</div>
        </div>
      </Card>
      <Card>
        <div className="choices" role="radiogroup" aria-label="Model">
          {MODELS.map((m) => (
            <label key={m.id} className={`choice ${form.model === m.id ? "selected" : ""}`}>
              <input type="radio" name="model" checked={form.model === m.id} onChange={() => update("model", m.id)} />
              <div className="label"><strong>{m.name}</strong><span>{m.hint}</span></div>
              <span className="tag">{m.tag}</span>
            </label>
          ))}
        </div>
      </Card>
      <Card>
        <Row title="Test with a screenshot" hint="Pick a saved screenshot of your game to check the key works and the cards are read correctly.">
          <button className="btn" disabled={testing} onClick={test}>{testing ? "Reading…" : "Choose screenshot…"}</button>
        </Row>
        {testError && <div className="result" style={{ color: "#ff8f88" }}>{testError}</div>}
        {result && t && (
          <div className="result">
            {result.image && <img className="sent-image" src={result.image} alt="The screenshot as sent to Claude" />}
            <span className="advice-pill" style={{ background: adviceColor(result.advice.action, result.advice.bet_units) }}>{result.advice.headline}</span>
            {result.advice.detail}
            <dl>
              <dt>Table found</dt><dd>{t.table_visible ? "Yes" : "No"}</dd>
              <dt>Dealer</dt><dd>{t.dealer_cards.join(" ") || "–"}</dd>
              <dt>Your hand(s)</dt><dd>{t.player_hands.map((h) => h.join(" ")).join("  |  ") || "–"}</dd>
              <dt>Other players</dt><dd>{t.other_players_cards.join(" ") || "–"}</dd>
              <dt>Phase</dt><dd>{t.is_betting_phase ? "Betting" : t.round_complete ? "Round over" : t.is_player_turn ? "Your turn" : "Dealing / waiting"}</dd>
              <dt>Confidence</dt><dd>{t.confident ? "High" : "Low: some cards were hard to read"}</dd>
            </dl>
          </div>
        )}
      </Card>
    </>
  );
}
