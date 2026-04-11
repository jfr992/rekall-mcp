type Props = {
  summary: string;
};

export function HandoffPanel({ summary }: Props) {
  return (
    <article className="card">
      <div className="section-title">
        <span className="dot dot-handoff" />
        <h2>Continuity</h2>
      </div>
      <pre>{summary || 'No handoff summary available yet.'}</pre>
    </article>
  );
}
