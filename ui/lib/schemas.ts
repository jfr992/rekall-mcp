import { z } from "zod";

// Extended in Task 9
export const HealthSchema = z.object({
  status: z.string(),
  transport: z.string().optional(),
  tools_enabled: z.array(z.string()).optional(),
});

export type Health = z.infer<typeof HealthSchema>;
