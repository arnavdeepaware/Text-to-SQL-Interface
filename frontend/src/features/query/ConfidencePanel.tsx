import type { HallucinationConfidence, SQLDraftMetadata, ValidationSignal } from "../../types/api";

interface ConfidencePanelProps {
  confidence: HallucinationConfidence;
  metadata: SQLDraftMetadata;
}

export function ConfidencePanel({ confidence, metadata }: ConfidencePanelProps) {
  return (
    <section className="confidence-panel" aria-labelledby="confidence-heading">
      <div className="confidence-summary">
        <div>
          <p className="eyebrow">Validated confidence</p>
          <h3 id="confidence-heading">{confidenceLabel(confidence)}</h3>
          <p>{confidence.rationale}</p>
        </div>
        <span className={`confidence-band confidence-band--${confidence.confidence_band}`}>
          {confidence.confidence_band.replace("_", " ")}
        </span>
      </div>

      <p className="model-confidence-note">
        Model-reported confidence: {formatPercent(metadata.model_confidence)}. This is provider
        telemetry, not the validated confidence score above.
      </p>

      {confidence.warnings.length > 0 ? (
        <div className="confidence-warning-list">
          <h4>Validation warnings</h4>
          <ul>
            {confidence.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <details className="signal-details">
        <summary>Validation signal breakdown</summary>
        {confidence.signals.length > 0 ? (
          <ul>
            {confidence.signals.map((signal) => (
              <ValidationSignalItem key={signal.code} signal={signal} />
            ))}
          </ul>
        ) : (
          <p>No validation signals were returned for this result.</p>
        )}
      </details>
    </section>
  );
}

function ValidationSignalItem({ signal }: { signal: ValidationSignal }) {
  return (
    <li>
      <div className="signal-row">
        <strong>{signal.code}</strong>
        <span className={`signal-status signal-status--${signal.status}`}>{signal.status}</span>
        <span>{formatPercent(signal.score)}</span>
      </div>
      <p>{signal.explanation}</p>
      <pre>{formatEvidence(signal.evidence)}</pre>
    </li>
  );
}

function confidenceLabel(confidence: HallucinationConfidence): string {
  if (confidence.score === null) {
    return "Validated score unavailable";
  }

  return `${formatPercent(confidence.score)} validated score`;
}

function formatPercent(value: number): string {
  return `${String(Math.round(value * 100))}%`;
}

function formatEvidence(evidence: Record<string, unknown>): string {
  if (Object.keys(evidence).length === 0) {
    return "No evidence payload.";
  }

  return JSON.stringify(evidence, null, 2);
}
