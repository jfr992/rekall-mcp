type Props = {
  summary: string;
};

export function PressurePanel({ summary }: Props) {
  const lines = summary.split('\n').filter(Boolean).slice(0, 8);

  return (
    <article className="card">
      <div className="section-title">
        <span className="dot dot-pressure" />
        <h2>Memory Pressure</h2>
      </div>
      {lines.length ? (
        <ul>
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <p>No pressure report loaded yet.</p>
      )}
    </article>
  );
}
