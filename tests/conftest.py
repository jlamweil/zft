"""Shared pytest config: Hypothesis profiles for Phase-B CPU batches.

Profiles are registered here only; the default profile is left untouched so
interactive runs keep hypothesis defaults. Batch runners select a profile
explicitly via ``--hypothesis-profile <name>``.
"""
from hypothesis import HealthCheck, settings

# Overnight batch: 10x examples, no wall-clock deadline (host shares CPU with
# other batch jobs; deadline flakes under contention, not under bugs).
settings.register_profile(
    "nightly",
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Soak tier for the property-dense modules only: 30x examples.
settings.register_profile(
    "soak",
    max_examples=3000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
