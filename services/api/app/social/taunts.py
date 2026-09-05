"""Post-match comedy taunts (PHASE_B_DESIGN §7.2). Templates verbatim; the
selection is pure so the frequency/age gates in `policy` stay the only
decision point about WHETHER a taunt is shown."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

TAUNTS: list[dict[str, Any]] = [
    {"id": "close_loss", "tone": "playful",
     "when": lambda c: (not c["won"]) and c["margin"] <= 1,
     "templates": [
         "You were {margin} seconds faster... on the wrong answer. 💀",
         "So close! Just {margin} more correct answers and you would've won. (That's how math works.)",
         "Silver medalist! In a 2-player game. 🥈",
     ]},
    {"id": "speed_accuracy_tradeoff", "tone": "savage",
     "when": lambda c: c["fastest_solver"] and c["lowest_accuracy"],
     "templates": [
         "Fastest solver! Also fastest wrong-answer-submitter. Speed ≠ accuracy, who knew?",
         "You solved {count} problems. {correct} were correct. That's... a ratio.",
         "Your fingers are faster than your brain. Respect. 🫡",
     ]},
    {"id": "trap_victim", "tone": "savage",
     "when": lambda c: c["traps_triggered"] >= 3,
     "templates": [
         "The traps caught you {count} times. They're not even hidden. 📦",
         "You fell for {trap_name}. It's literally named '{trap_name}'. It told you what it was.",
         "Three traps. THREE. At this point they're not traps, they're welcome mats.",
     ]},
    {"id": "blowout_winner", "tone": "playful",
     "when": lambda c: c["won"] and c["margin"] >= 5,
     "templates": [
         "You didn't just win. You made them question their life choices.",
         "That wasn't a match, that was a math lecture. You were the professor.",
         "Dominance. Sheer dominance. {opponent} is rethinking their career path.",
     ]},
    {"id": "self_deprecating_loss", "tone": "self_deprecating",
     "when": lambda c: (not c["won"]) and c["margin"] >= 5,
     "templates": [
         "Well, that happened. Let's never speak of it again.",
         "You lost so badly the scoreboard asked if you were okay.",
         "On the bright side, you're really good at... being consistent?",
     ]},
    {"id": "comeback", "tone": "playful",
     "when": lambda c: c["won"] and c["was_losing"],
     "templates": [
         "FROM THE DEPTHS! They counted you out. You counted yourself back in.",
         "Down {deficit} problems and still won. Main character energy.",
         "The comeback kid strikes again. {opponent} is still processing what happened.",
     ]},
]


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "?"


def build_context(*, won: bool, my_correct: int, opp_correct: int, my_attempted: int,
                  my_time_ms: int, opp_time_ms: int, my_accuracy: float, opp_accuracy: float,
                  traps_triggered: int = 0, was_losing: bool = False,
                  opponent_name: str = "Your opponent", trap_name: str = "the obvious one") -> dict:
    return {
        "won": won,
        "margin": abs(my_correct - opp_correct),
        "fastest_solver": my_time_ms < opp_time_ms,
        "lowest_accuracy": my_accuracy < opp_accuracy,
        "traps_triggered": traps_triggered,
        "was_losing": was_losing,
        "count": my_attempted if traps_triggered < 3 else traps_triggered,
        "correct": my_correct,
        "opponent": opponent_name,
        "trap_name": trap_name,
        "deficit": max(0, opp_correct - my_correct),
    }


def select_taunt(ctx: dict, seed: str) -> Optional[dict]:
    """First matching taunt in catalogue order; template chosen by a stable
    hash of `seed` (e.g. match id) so a re-read shows the same line."""
    for taunt in TAUNTS:
        if taunt["when"](ctx):
            idx = int(hashlib.sha256(f"{seed}:{taunt['id']}".encode()).hexdigest(), 16) % len(taunt["templates"])
            text = taunt["templates"][idx].format_map(_Safe(ctx))
            return {"id": taunt["id"], "tone": taunt["tone"], "text": text}
    return None
