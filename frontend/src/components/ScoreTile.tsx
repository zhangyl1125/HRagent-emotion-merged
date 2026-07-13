interface ScoreTileProps {
  label: string;
  score: number | string;
}

export function ScoreTile({ label, score }: ScoreTileProps) {
  const numeric = typeof score === 'number' ? Math.max(0, Math.min(100, score)) : null;
  return (
    <div className="score-tile">
      <div className="score-tile-head">
        <span>{label}</span>
        <strong>{score}</strong>
      </div>
      <div className="score-track" aria-hidden="true">
        <span style={{ width: `${numeric ?? 0}%` }} />
      </div>
    </div>
  );
}
