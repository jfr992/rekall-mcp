import { z } from "zod";

// ----- Health --------------------------------------------------------------

export const HealthSchema = z.object({
  status: z.string(),
  transport: z.string().optional(),
  tools_enabled: z.array(z.string()).optional(),
});

// ----- Projects ------------------------------------------------------------

export const ProjectInfoSchema = z.object({
  name: z.string(),
  count: z.number(),
});

export const ProjectsResponseSchema = z.object({
  total: z.number(),
  projects: z.array(ProjectInfoSchema),
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
}).passthrough();

// ----- Graph ---------------------------------------------------------------

export const GraphNodeSchema = z.object({
  id: z.string(),
  type: z.string().optional(),
  content: z.string().optional(),
  tier: z.string().optional(),
  durability: z.number().optional(),
  degree: z.number().optional(),
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
});

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

export const ResumeResponseSchema = z.object({
  scope: z.record(z.string(), z.any()),
  recent: z.array(z.any()),
  important: z.array(z.any()),
  unresolved: z.array(z.any()),
  next_steps: z.array(z.any()),
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
export type GraphNode = z.infer<typeof GraphNodeSchema>;
export type GraphLink = z.infer<typeof GraphLinkSchema>;
export type GraphResponse = z.infer<typeof GraphResponseSchema>;
export type DetailResponse = z.infer<typeof DetailResponseSchema>;
export type KbEntry = z.infer<typeof KbEntrySchema>;
export type KbResponse = z.infer<typeof KbResponseSchema>;
export type PressureResponse = z.infer<typeof PressureResponseSchema>;
export type PruneCandidate = z.infer<typeof PruneCandidateSchema>;
export type PrunePlan = z.infer<typeof PrunePlanSchema>;
export type PruneApplyResponse = z.infer<typeof PruneApplyResponseSchema>;
export type BackfillReport = z.infer<typeof BackfillReportSchema>;
export type ResumeResponse = z.infer<typeof ResumeResponseSchema>;
