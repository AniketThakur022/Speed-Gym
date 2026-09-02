/** Session prescription — what the client Decision Engine emits and the
 *  Ledger's sessions.prescription JSONB stores. */

export type Bucket = "primary" | "sinking" | "frontier";

export type TechniqueStateName = "fluid" | "fragile" | "fractured";

export interface WrongAnswerGuards {
  max_cycles_per_technique: number;
  max_wrongs_per_session: number;
  max_consecutive_wrongs: number;
  pingpong_max_toggles: number;
  pingpong_window: number;
}

export interface PrescribedProblem {
  techniqueId: string;
  bucket: Bucket;
}

export interface SessionAllocation {
  primary: number;
  sinking: number;
  frontier: number;
}

export interface SessionPrescription {
  allocation: SessionAllocation;
  problems: PrescribedProblem[];
  targetTimeSeconds: number;
  guards: WrongAnswerGuards;
}
