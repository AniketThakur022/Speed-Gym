/** Runs the REAL client-side BKT engine (packages/psychometrics) for the
 *  pre-loss parity case: P(L)=0.35 FRACTURED + one correct difficulty-1
 *  answer -> 0.8247 FRAGILE (82%). Emits JSON on stdout. */
import { updateBkt, posterior, bktToMastery, classifyBkt, decayMastery, isFluid } from "../packages/psychometrics/src/bkt";
import { RFP_BKT_PARAMS, LEARN_RATE_BY_DIFFICULTY, FLUID_GATE, PROFICIENT_GATE } from "../packages/psychometrics/src/constants";

// Product mastery bands (the names the pre-loss demo showed the client).
const band = (p: number) => (p >= FLUID_GATE ? "FLUID" : p >= PROFICIENT_GATE ? "FRAGILE" : "FRACTURED");

const before = RFP_BKT_PARAMS.pInit;              // 0.35 prior, BKT-01
const post = posterior(before, true);             // Bayesian posterior on a correct obs
const after = updateBkt(before, true, RFP_BKT_PARAMS, 1);  // + learn step, difficulty 1

console.log(JSON.stringify({
  engine: "packages/psychometrics/src/bkt.ts (real client-side engine, not a reimplementation)",
  params: RFP_BKT_PARAMS,
  learn_rate_by_difficulty: LEARN_RATE_BY_DIFFICULTY,
  gates: { fluid: FLUID_GATE, proficient: PROFICIENT_GATE },
  before: { pL: before, mastery_pct: Math.round(bktToMastery(before)), band: band(before), classify: classifyBkt(before) },
  posterior_after_correct: post,
  after: { pL: after, mastery_pct: Math.round(bktToMastery(after)), band: band(after), classify: classifyBkt(after), is_fluid: isFluid(after) },
  arithmetic: `posterior=${post.toFixed(8)}; learn step P(T)=0.40 -> ${post.toFixed(8)} + (1-${post.toFixed(8)})*0.40 = ${after.toFixed(8)}`,
  counterfactual_wrong_answer: updateBkt(before, false, RFP_BKT_PARAMS, 1),
  decay_30_days_from_after: decayMastery(after, 30),
}, null, 2));
