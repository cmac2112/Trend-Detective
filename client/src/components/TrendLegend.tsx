import { legendGradient, niceLimit } from "../trendColor";

interface Props {
  units: string;
  limit: number;
  coarsened: boolean;
  visible: boolean;
  onToggle: (visible: boolean) => void;
}

/** Overlay on the map: what the cell colours mean, and a show/hide switch. */
export default function TrendLegend({ units, limit, coarsened, visible, onToggle }: Props) {
  const lim = niceLimit(limit);
  return (
    <div className="trend-legend" role="group" aria-label="Trend map legend">
      <label className="trend-legend-head">
        <input type="checkbox" checked={visible} onChange={(e) => onToggle(e.target.checked)} />
        <strong>Trend map</strong>
        <span className="muted">change per decade ({units})</span>
      </label>
      {visible && (
        <>
          <div className="trend-ramp" style={{ background: legendGradient() }} aria-hidden />
          <div className="trend-ramp-labels">
            <span>−{lim}</span>
            <span>0</span>
            <span>+{lim}</span>
          </div>
          <div className="trend-ramp-labels muted">
            <span>decreasing</span>
            <span>increasing</span>
          </div>
          <div className="trend-key">
            <span className="trend-key-swatch solid" aria-hidden /> significant
            <span className="trend-key-swatch faded" aria-hidden /> not significant
          </div>
          {coarsened && <div className="muted">Large region: neighbouring cells averaged together.</div>}
        </>
      )}
    </div>
  );
}
