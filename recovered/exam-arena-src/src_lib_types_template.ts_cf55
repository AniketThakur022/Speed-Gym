import { z } from "zod";

export type ScaffoldType =
  | "arrow_matrix"
  | "place_value_chart"
  | "number_line"
  | "grid_construction"
  | "equation_chain"
  | "shape_canvas"
  | "coordinate_grid"
  | "textual_scaffold"
  | "rotation_diagram"
  | "formula_generalization"
  | "venn_diagram";

export type GenerationMethod = "template" | "llm" | "converted";

export type SolveAlongTemplate = {
  id: string;
  domain: string;
  concept: {
    technique_name: string;
    category: string;
    sub_category?: string;
  };
  difficulty: number;
  expected_time: number;
  visual_scaffold: {
    type: ScaffoldType;
    config?: Record<string, unknown>;
  };
  examples: TemplateExample[];
  key_reminders?: string[];
  common_mistakes?: string[];
  version: number;
  sourceDocumentId?: string;
  generationMethod?: GenerationMethod;
};

export type TemplateExample = {
  problem_statement: string;
  solution: SolutionStep[];
  answer?: string;
};

export type SolutionStep = {
  step_num: number;
  operation: string;
  result?: string;
  description?: string;
};

export type RenderMode = "quick" | "solve_along" | "guided";

export type TemplateSession = {
  id: string;
  templates: SolveAlongTemplate[];
  currentIndex: number;
  stepProgress: Record<string, StepProgress>;
  mode: RenderMode;
};

export type StepProgress = {
  visibleSteps: number;
  completed: boolean;
  correct: boolean | null;
  timeSpent: number;
};

export const SolutionStepSchema = z.object({
  step_num: z.number().int().positive(),
  operation: z.string().min(1),
  result: z.string().optional(),
  description: z.string().optional(),
});

export const TemplateExampleSchema = z.object({
  problem_statement: z.string().min(1),
  solution: z.array(SolutionStepSchema).min(1),
  answer: z.string().optional(),
});

export const SolveAlongTemplateSchema = z.object({
  id: z.string().min(1),
  domain: z.string().min(1),
  concept: z.object({
    technique_name: z.string().min(1),
    category: z.string().min(1),
    sub_category: z.string().optional(),
  }),
  difficulty: z.number().int().min(1).max(5),
  expected_time: z.number().int().positive(),
  visual_scaffold: z.object({
    type: z.string().min(1),
    config: z.record(z.string(), z.unknown()).optional(),
  }),
  examples: z.array(TemplateExampleSchema).min(1),
  key_reminders: z.array(z.string()).optional(),
  common_mistakes: z.array(z.string()).optional(),
  version: z.number().int().positive().default(1),
  sourceDocumentId: z.string().optional(),
  generationMethod: z.enum(["template", "llm", "converted"]).optional(),
});

export const StepProgressSchema = z.object({
  visibleSteps: z.number().int().min(0),
  completed: z.boolean(),
  correct: z.boolean().nullable(),
  timeSpent: z.number().min(0),
});

export const TemplateSessionSchema = z.object({
  id: z.string().min(1),
  templates: z.array(SolveAlongTemplateSchema),
  currentIndex: z.number().int().min(0),
  stepProgress: z.record(z.string(), StepProgressSchema),
  mode: z.enum(["quick", "solve_along", "guided"]),
});

export const DOMAINS = [
  { id: "vedic-math", label: "Vedic Math" },
  { id: "gmat", label: "GMAT" },
  { id: "cat", label: "CAT" },
  { id: "gre", label: "GRE" },
  { id: "banking", label: "Banking" },
] as const;

export const DOMAIN_LABELS: Record<string, string> = {
  "vedic-math": "Vedic Math",
  gmat: "GMAT",
  cat: "CAT",
  gre: "GRE",
  banking: "Banking",
};

export type DomainId = (typeof DOMAINS)[number]["id"];

export type RendererProps = {
  template: SolveAlongTemplate;
  visibleSteps: number;
  mode: RenderMode;
  onStepReveal?: () => void;
  showAnswerInput?: boolean;
  showVisualScaffold?: boolean;
};
