import { z } from "zod";

// ----- Health --------------------------------------------------------------

export const HealthSchema = z.object({
  status: z.string(),
  transport: z.string().optional(),
  tools_enabled: z.array(z.string()).optional(),
  vectors: z
    .object({ sampled: z.number(), zero_vectors: z.number() })
    .optional(),
  // "ok" or { error } — see /health embedder probe (#57).
  embedder: z
    .union([z.literal("ok"), z.object({ error: z.string() })])
    .optional(),
});

// ----- Projects ------------------------------------------------------------

export const ProjectInfoSchema = z.object({
  name: z.string(),
  count: z.number(),
});

export const ProjectsResponseSchema = z.object({
  total: z.number(),
  projects: z.array(ProjectInfoSchema),
  truncated: z.boolean().optional(),
});

// ----- Memory core ---------------------------------------------------------

export const MemorySchema = z.object({
  memory_id: z.string(),
  content: z.string().optional(),
  type: z.string().optional(),
  tier: z.enum(["working", "episodic", "semantic", "identity"]).optional(),
  durability: z.number().optional(),
  reinforcement_count: z.number().optional(),
  lifecycle_reason: z.string().optional(),
  date: z.string().optional(),
  project: z.string().optional(),
  salience: z.number().optional(),
  entities: z.array(z.string()).optional(),
}).passthrough();

// ----- Recall (global search) ----------------------------------------------

export const RecallMemorySchema = MemorySchema.extend({
  score: z.number().optional(),
});

export const RecallResponseSchema = z.object({
  query: z.string(),
  count: z.number(),
  memories: z.array(RecallMemorySchema),
});

// ----- Delete ---------------------------------------------------------------

export const DeleteResponseSchema = z.object({
  deleted: z.boolean(),
  memory_id: z.string(),
});

// ----- Entity backlinks ----------------------------------------------------

export const ByEntityResponseSchema = z.object({
  entity: z.string(),
  project: z.string(),
  count: z.number(),
  memories: z.array(MemorySchema),
});

// ----- Graph ---------------------------------------------------------------

export const GraphNodeSchema = z.object({
  id: z.string(),
  type: z.string().optional(),
  content: z.string().optional(),
  tier: z.string().nullable().optional(),
  durability: z.number().nullable().optional(),
  degree: z.number().optional(),
  salience: z.number().nullable().optional(),
  trust_boundary: z.string().nullable().optional(),
  timestamp: z.string().nullable().optional(),
}).passthrough();

export const GraphLinkSchema = z.object({
  source: z.union([z.string(), z.any()]),
  target: z.union([z.string(), z.any()]),
  weight: z.number().optional(),
  relation: z.string().optional(),
}).passthrough();

export const GraphResponseSchema = z.object({
  graph: z
    .object({
      nodes: z.array(GraphNodeSchema),
      links: z.array(GraphLinkSchema),
    })
    .optional(),
}).passthrough();

// ----- Detail --------------------------------------------------------------

export const MemoryNeighborSchema = z.object({
  relation: z.string(),
  memory: MemorySchema,
});

export const DetailResponseSchema = z.object({
  memory: MemorySchema.nullable(),
  neighbors: z.array(MemoryNeighborSchema),
  scope: z
    .object({
      project: z.string().nullable().optional(),
      agent: z.string().nullable().optional(),
      repo_name: z.string().nullable().optional(),
    })
    .nullable(),
});

// ----- Detail V2 -----------------------------------------------------------

export const RelationshipSchema = z.object({
  source_id: z.string(),
  target_id: z.string(),
  neighbor_id: z.string(),
  direction: z.enum(["in", "out"]),
  relation: z.string(),
  weight: z.number().optional(),
  auto: z.boolean().optional(),
  created: z.string().optional(),
  memory: MemorySchema.nullable(),
});

export const ProvenanceSchema = z
  .object({
    agent: z.string().nullable(),
    source_tool: z.string().nullable(),
    source_event: z.string().nullable(),
    timestamp: z.string().nullable(),
    session_id: z.string().nullable(),
    repo_name: z.string().nullable(),
    repo_remote: z.string().nullable(),
    branch: z.string().nullable(),
    trust_boundary: z.string().nullable(),
  })
  .passthrough();

export const LifecycleSchema = z
  .object({
    tier: z.string().nullable(),
    durability: z.number().nullable(),
    retention_days: z.number().nullable(),
    lifecycle_reason: z.string().nullable(),
  })
  .passthrough();

export const StorageSchema = z.object({
  qdrant: z.boolean(),
  yaml: z.boolean(),
});

export const DetailResponseV2Schema = z.object({
  memory: MemorySchema.nullable(),
  neighbors: z.array(MemoryNeighborSchema),
  scope: z
    .object({
      project: z.string().nullable().optional(),
      agent: z.string().nullable().optional(),
      repo_name: z.string().nullable().optional(),
    })
    .nullable(),
  relationships: z.array(RelationshipSchema).optional(),
  provenance: ProvenanceSchema.nullable().optional(),
  lifecycle: LifecycleSchema.nullable().optional(),
  storage: StorageSchema.optional(),
  warnings: z.array(z.string()).optional(),
  missing_neighbor_ids: z.array(z.string()).optional(),
});

// ----- KB ------------------------------------------------------------------

export const KbEntrySchema = z.object({
  memory_id: z.string().nullable(),
  type: z.string().nullable(),
  tier: z.string().nullable(),
  date: z.string().nullable(),
  summary: z.string(),
  content: z.string().optional(),
});

export const KbResponseSchema = z.object({
  project: z.string(),
  decisions: z.array(KbEntrySchema),
  requirements: z.array(KbEntrySchema),
  preferences: z.array(KbEntrySchema),
  learnings: z.array(KbEntrySchema),
  facts: z.array(KbEntrySchema).optional(),
  truncated: z.boolean().optional(),
});

// ----- Sessions ------------------------------------------------------------

export const SessionTotalsSchema = z.object({
  recalls: z.number(),
  injected: z.number(),
  tokens: z.number(),
});

export const SessionRowSchema = z.object({
  session_id: z.string(),
  project: z.string(),
  started_at: z.string().nullable(),
  last_at: z.string().nullable(),
  totals: SessionTotalsSchema,
});

export const SessionsResponseSchema = z.object({
  sessions: z.array(SessionRowSchema),
  window: z.number(),
});

export const SessionInjectedSchema = z.object({
  memory_id: z.string(),
  token_estimate: z.number().nullable(),
});

export const SessionRecallMemorySchema = z.object({
  memory_id: z.string(),
  score: z.number(),
});

export const SessionRecallSchema = z.object({
  query: z.string().nullable(),
  memories: z.array(SessionRecallMemorySchema),
  token_estimate: z.number().nullable(),
  observed_at: z.string(),
});

export const SessionDetailSchema = SessionRowSchema.extend({
  injected: z.array(SessionInjectedSchema),
  recalls: z.array(SessionRecallSchema),
  window: z.number().optional(),
});

export const FeedbackVerdictSchema = z.enum(["useful", "wrong", "stale"]);

export const FeedbackResponseSchema = z.object({ recorded: z.boolean() });

// ----- Pressure ------------------------------------------------------------

export const PressureResponseSchema = z.object({
  project: z.string(),
  load_score: z.number(),
  capacity: z.number(),
  flagged: z.object({
    stale_working_count: z.number(),
    low_value_count: z.number(),
    contradiction_count: z.number(),
  }),
  candidates: z.array(z.record(z.string(), z.any())),
  truncated: z.boolean().optional(),
});

// ----- Prune ---------------------------------------------------------------

export const PruneCandidateSchema = z.object({
  memory_id: z.string(),
  tier: z.string(),
  reason: z.string(),
  age_days: z.number(),
  salience: z.number(),
});

export const PrunePlanSchema = z.object({
  plan_id: z.string(),
  project: z.string(),
  generated_at: z.string(),
  expires_at: z.string(),
  summary: z.string(),
  candidates: z.array(PruneCandidateSchema),
});

export const PruneApplyResponseSchema = z.object({
  plan_id: z.string(),
  deleted: z.array(z.string()),
  skipped: z.array(z.string()),
});

// ----- Backfill ------------------------------------------------------------

export const BackfillReportSchema = z.object({
  dry_run: z.boolean(),
  project: z.string().nullable(),
  updated_by_tier: z.record(z.string(), z.number()),
  skipped: z.array(z.string()),
  errors: z.array(z.object({ memory_id: z.string(), error: z.string() })),
  total: z.number(),
});

// ----- Resume --------------------------------------------------------------

export const ResumeMemorySchema = z.object({
  memory_id: z.string(),
  content: z.string(),
  date: z.string().optional(),
  type: z.string().optional(),
  tier: z.string().optional(),
  importance: z.number().optional(),
});

export const ResumeConflictSchema = z.object({
  memory_id: z.string(),
  conflicts_with: z.string(),
  content: z.string().optional(),
}).passthrough();

export const ResumeScopeSchema = z.object({
  project: z.string().optional(),
  agent: z.string().optional(),
}).passthrough();

export const ResumeResponseSchema = z.object({
  scope: ResumeScopeSchema,
  recent: z.array(ResumeMemorySchema),
  important: z.array(ResumeMemorySchema),
  unresolved: z.array(ResumeConflictSchema),
  next_steps: z.array(z.string()),
  handoff: z.string().nullable(),
  pressure: z.any(),
  pressure_report: z.string().optional(),
  truncated: z.boolean(),
  summary: z.string().optional(),
}).passthrough();

// Types
export type Health = z.infer<typeof HealthSchema>;
export type ProjectInfo = z.infer<typeof ProjectInfoSchema>;
export type ProjectsResponse = z.infer<typeof ProjectsResponseSchema>;
export type Memory = z.infer<typeof MemorySchema>;
export type RecallMemory = z.infer<typeof RecallMemorySchema>;
export type RecallResponse = z.infer<typeof RecallResponseSchema>;
export type ByEntityResponse = z.infer<typeof ByEntityResponseSchema>;
export type DeleteResponse = z.infer<typeof DeleteResponseSchema>;
export type GraphNode = z.infer<typeof GraphNodeSchema>;
export type GraphLink = z.infer<typeof GraphLinkSchema>;
export type GraphResponse = z.infer<typeof GraphResponseSchema>;
export type DetailResponse = z.infer<typeof DetailResponseSchema>;
export type Relationship = z.infer<typeof RelationshipSchema>;
export type Provenance = z.infer<typeof ProvenanceSchema>;
export type Lifecycle = z.infer<typeof LifecycleSchema>;
export type Storage = z.infer<typeof StorageSchema>;
export type DetailResponseV2 = z.infer<typeof DetailResponseV2Schema>;
export type KbEntry = z.infer<typeof KbEntrySchema>;
export type KbResponse = z.infer<typeof KbResponseSchema>;
export type SessionTotals = z.infer<typeof SessionTotalsSchema>;
export type SessionRow = z.infer<typeof SessionRowSchema>;
export type SessionsResponse = z.infer<typeof SessionsResponseSchema>;
export type SessionInjected = z.infer<typeof SessionInjectedSchema>;
export type SessionRecallMemory = z.infer<typeof SessionRecallMemorySchema>;
export type SessionRecall = z.infer<typeof SessionRecallSchema>;
export type SessionDetail = z.infer<typeof SessionDetailSchema>;
export type FeedbackVerdict = z.infer<typeof FeedbackVerdictSchema>;
export type FeedbackResponse = z.infer<typeof FeedbackResponseSchema>;
export type PressureResponse = z.infer<typeof PressureResponseSchema>;
export type PruneCandidate = z.infer<typeof PruneCandidateSchema>;
export type PrunePlan = z.infer<typeof PrunePlanSchema>;
export type PruneApplyResponse = z.infer<typeof PruneApplyResponseSchema>;
export type BackfillReport = z.infer<typeof BackfillReportSchema>;
export type ResumeResponse = z.infer<typeof ResumeResponseSchema>;

export const PublishResponseSchema = z
  .object({
    tree: z.array(z.string()),
    files: z.record(z.string(), z.string()),
    stats: z
      .object({
        concepts: z.number(),
        clusters: z.number().optional(),
        titled_by: z.string().optional(),
      })
      .passthrough(),
  });
export type PublishResponse = z.infer<typeof PublishResponseSchema>;
