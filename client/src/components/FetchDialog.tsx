import type { Coverage, Job, VariableInfo } from "../api";

interface Props {
  variable: VariableInfo;
  coverage: Coverage;
  job: Job | null;
  error: string | null;
  onDownload: () => void;
  onAnalyzeAvailable: () => void;
  onCancel: () => void;
}

const MIN_MONTHS = 24; // the API needs at least two years for a trend

/** Asks before downloading missing data; shows progress while it downloads. */
export default function FetchDialog({ variable, coverage: c, job, error, onDownload, onAnalyzeAvailable, onCancel }: Props) {
  const busy = job && (job.status === "queued" || job.status === "downloading" || job.status === "building");
  const canUseAvailable = c.available_months >= MIN_MONTHS;
  const missingRange = c.missing_first === c.missing_last ? c.missing_first : `${c.missing_first} to ${c.missing_last}`;

  return (
    <div className="backdrop" role="presentation">
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="fetch-title">
        <h2 id="fetch-title">{busy ? `Downloading ${variable.name}` : "Some data isn't downloaded yet"}</h2>

        {!busy && (
          <>
            <p>
              <strong>{c.missing_months}</strong> of the {c.requested_months} months you asked for ({missingRange}) aren't on
              the server yet.
              {c.available_months > 0 && <> {c.available_months} months are already available.</>}
            </p>
            {c.download_months > 0 ? (
              <p>
                Downloading them from NASA is about <strong>{formatMb(c.estimated_mb)}</strong>{" "}
                <span className="muted">(server limit: {formatMb(c.limit_mb)} per request)</span>.
              </p>
            ) : (
              <p>The files are already on the server; they just need to be prepared. This is quick.</p>
            )}
            {c.start < c.data_starts && (
              <p className="muted">Note: this dataset starts in {c.data_starts}, so earlier months don't exist.</p>
            )}
            {!c.within_limit && (
              <p className="callout warn" role="alert">
                <span aria-hidden>⚠</span> That's over the server's {formatMb(c.limit_mb)} limit. Choose a shorter date range
                (roughly {Math.floor(c.limit_mb / variable.mb_per_month)} months or fewer of new data
                {canUseAvailable ? ") or analyze the data that's already available." : ")."}
              </p>
            )}
          </>
        )}

        {job && (
          <div className="job" aria-live="polite">
            <div className="job-msg">{job.message}</div>
            <progress max={1} value={job.progress ?? undefined} />
          </div>
        )}
        {error && (
          <p className="callout error" role="alert">
            <span aria-hidden>✕</span> {error}
          </p>
        )}

        <div className="dialog-actions">
          <button type="button" className="ghost" onClick={onCancel}>
            {busy ? "Hide" : "Cancel"}
          </button>
          {!busy && canUseAvailable && c.available_months < c.requested_months && (
            <button type="button" className="secondary" onClick={onAnalyzeAvailable}>
              Use the {c.available_months} available months
            </button>
          )}
          {!busy && c.within_limit && (
            <button type="button" className="primary" onClick={onDownload}>
              {c.download_months > 0 ? `Download ${formatMb(c.estimated_mb)} and analyze` : "Prepare and analyze"}
            </button>
          )}
        </div>
        {busy && <p className="muted small">The download continues on the server even if you hide this window.</p>}
      </div>
    </div>
  );
}

function formatMb(mb: number) {
  return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${Math.max(1, Math.round(mb))} MB`;
}
