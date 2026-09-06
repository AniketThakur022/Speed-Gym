"""Test-wide defaults. The rate limiter is OFF under test: the suite registers
hundreds of users from one client IP within a minute, which is exactly the
traffic shape the limiter exists to stop. test_hardening turns it on for its
own module only."""

import os

os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")
