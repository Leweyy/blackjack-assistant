import type { ReactNode } from "react";

export function Card({ children }: { children: ReactNode }) {
  return <div className="card">{children}</div>;
}

export function Row({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="row">
      <div className="label">
        <strong>{title}</strong>
        {hint && <span>{hint}</span>}
      </div>
      <div className="control">{children}</div>
    </div>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" aria-label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
    </label>
  );
}

export function ToggleRow(props: { title: string; hint?: ReactNode; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <Row title={props.title} hint={props.hint}>
      <Toggle checked={props.checked} onChange={props.onChange} label={props.title} />
    </Row>
  );
}

/** Integer stepper; `value` is the raw text so the user can type freely. */
export function Stepper(props: {
  value: string;
  onChange: (v: string) => void;
  min: number;
  max: number;
  step?: number;
  label: string;
}) {
  const step = props.step ?? 1;
  const num = Number(props.value);
  const bump = (delta: number) => {
    const base = Number.isFinite(num) ? num : props.min;
    const next = Math.min(props.max, Math.max(props.min, Math.round((base + delta) / step) * step));
    props.onChange(String(Number(next.toFixed(2))));
  };
  return (
    <div className="stepper">
      <button type="button" aria-label={`Decrease ${props.label}`} onClick={() => bump(-step)}>−</button>
      <input aria-label={props.label} inputMode="decimal" value={props.value} onChange={(e) => props.onChange(e.target.value)} />
      <button type="button" aria-label={`Increase ${props.label}`} onClick={() => bump(step)}>+</button>
    </div>
  );
}

export const icons = {
  rules: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="3" width="12" height="17" rx="2" /><path d="M8 3v0M20 7l-4 13" /><path d="M8 9h4M8 13h3" />
    </svg>
  ),
  counting: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19V9M10 19V5M16 19v-7M22 19H2" />
    </svg>
  ),
  screen: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /><path d="M8 8h4v4" />
    </svg>
  ),
  connection: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="15" r="4" /><path d="M11 12l9-9M17 6l3 3M15 8l2 2" />
    </svg>
  ),
};
