"""Social / gamification / COPPA kids mode (block 5).

Pure rules live in `policy`, `achievements`, `taunts`, `daily`; the DB-touching
helpers in `xp` and `guard`. Every social surface is flag-gated
(`social_*`, `daily_challenge`); kids mode is NOT a flag — compliance is not
optional.
"""
