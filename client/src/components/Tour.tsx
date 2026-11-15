import { useEffect, useRef, useState } from "react";

export interface TourStep {
  title: string;
  text: string;
  /** `data-tour` value of the element to highlight once the step's action has finished. */
  target: string;
  /** What the app does when this step starts (add a region, run a scan, ...). */
  run?: () => void | Promise<void>;
}

interface Props {
  steps: TourStep[];
  /** True while the app is fetching/analyzing; "Next" waits for it. */
  busy: boolean;
  onClose: () => void;
}

const HIGHLIGHT = "tour-target";

/** A guided demo the user watches: each step does something in the app, then points at the
 *  result with a short explanation. */
export default function Tour({ steps, busy, onClose }: Props) {
  const [i, setI] = useState(0);
  const [starting, setStarting] = useState(true);
  const lit = useRef<Element | null>(null);
  // Each step's action must run exactly once, even when React (StrictMode, in development)
  // runs the effect twice: the second run waits on the same promise instead of acting again.
  const ran = useRef<{ i: number; done: Promise<unknown> } | null>(null);
  const step = steps[i];

  // Run the step's action, then highlight its target once it exists (results appear async).
  useEffect(() => {
    let cancelled = false;
    let frame = 0;
    setStarting(true);
    if (ran.current?.i !== i) ran.current = { i, done: Promise.resolve().then(() => step.run?.()) };
    ran.current.done.finally(() => {
      if (cancelled) return;
      setStarting(false);
      const deadline = performance.now() + 30000;
      const find = () => {
        if (cancelled) return;
        const el = document.querySelector(`[data-tour="${step.target}"]`);
        if (el) {
          lit.current?.classList.remove(HIGHLIGHT);
          el.classList.add(HIGHLIGHT);
          lit.current = el;
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        } else if (performance.now() < deadline) {
          frame = requestAnimationFrame(find);
        }
      };
      find();
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
    };
    // Each step runs once, when it starts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i]);

  useEffect(() => () => lit.current?.classList.remove(HIGHLIGHT), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const waiting = busy || starting;
  const last = i === steps.length - 1;
  return (
    <div className="tour-card" role="dialog" aria-live="polite" aria-label="Guided demo">
      <div className="tour-head">
        <span className="small muted">
          Guided demo · step {i + 1} of {steps.length}
        </span>
        <button type="button" className="icon-btn" aria-label="End demo" onClick={onClose}>
          ✕
        </button>
      </div>
      <strong>{step.title}</strong>
      <p className="small">{step.text}</p>
      <div className="tour-actions">
        {waiting && <span className="small muted">Working…</span>}
        <button
          type="button"
          className="primary small"
          disabled={waiting}
          onClick={() => (last ? onClose() : setI(i + 1))}
          autoFocus
        >
          {last ? "Finish" : "Next →"}
        </button>
      </div>
    </div>
  );
}
