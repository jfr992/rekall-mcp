type KnowledgeBaseItem = {
  title: string;
  value: string;
};

type Props = {
  project: string;
  agent: string;
  nodeCount: number;
  linkCount: number;
  hints: string[];
};

export function KbPanel({ project, agent, nodeCount, linkCount, hints }: Props) {
  const items: KnowledgeBaseItem[] = [
    { title: 'Project', value: project },
    { title: 'Agent', value: agent },
    { title: 'Knowledge Nodes', value: String(nodeCount) },
    { title: 'Relationships', value: String(linkCount) },
  ];

  return (
    <article className="card kb-panel">
      <div className="section-title">
        <span className="dot dot-kb" />
        <h2>Knowledge Base</h2>
      </div>
      <div className="kb-grid">
        {items.map((item) => (
          <div key={item.title} className="kb-chip">
            <span>{item.title}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
      <div className="kb-hints">
        {(hints.length ? hints : ['No startup hints loaded yet.']).map((hint) => (
          <div key={hint} className="hint-pill">{hint}</div>
        ))}
      </div>
    </article>
  );
}
