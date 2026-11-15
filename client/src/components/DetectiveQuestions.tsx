import type { VariableInfo } from "../api";
import { INTERESTS, PLACES, suggest, type Choice } from "../detective";

interface Props {
  place: string | null;
  interest: string | null;
  onPlace: (key: string | null) => void;
  onInterest: (key: string | null) => void;
  variables: VariableInfo[];
  selected: string;
  onPick: (key: string) => void;
}

function Chips({ items, value, onChange, label }: { items: Choice[]; value: string | null; onChange: (k: string | null) => void; label: string }) {
  return (
    <div className="chips" role="radiogroup" aria-label={label}>
      {items.map((c) => (
        <button
          key={c.key}
          type="button"
          role="radio"
          aria-checked={value === c.key}
          className={`chip ${value === c.key ? "chip-on" : ""}`}
          onClick={() => onChange(value === c.key ? null : c.key)}
        >
          <span aria-hidden>{c.icon}</span> {c.label}
        </button>
      ))}
    </div>
  );
}

/** Two quick questions that point a student at the variables most worth investigating. */
export default function DetectiveQuestions({ place, interest, onPlace, onInterest, variables, selected, onPick }: Props) {
  const ideas = suggest(place, interest);
  const name = (key: string) => variables.find((v) => v.key === key)?.name ?? key;
  return (
    <details className="detective" open={!!(place || interest)} data-tour="detective">
      <summary>🕵️ Not sure what to investigate? Answer two questions</summary>
      <p className="small q">What kind of place did you pick?</p>
      <Chips items={PLACES} value={place} onChange={onPlace} label="Kind of place" />
      <p className="small q">What are you curious about?</p>
      <Chips items={INTERESTS} value={interest} onChange={onInterest} label="Curious about" />
      {ideas.length > 0 && (
        <>
          <p className="small q">Good leads to investigate:</p>
          <ul className="ideas">
            {ideas.map((s) => (
              <li key={s.key}>
                <button
                  type="button"
                  className={`idea ${selected === s.key ? "idea-on" : ""}`}
                  onClick={() => onPick(s.key)}
                  aria-pressed={selected === s.key}
                >
                  <strong>{name(s.key)}</strong>
                  <span className="small muted">{s.why}</span>
                </button>
              </li>
            ))}
          </ul>
          {place === "ocean" && (
            <p className="small muted">Soil, snow, runoff and greenness are land-only, so they have no data over the sea.</p>
          )}
        </>
      )}
    </details>
  );
}
