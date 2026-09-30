"""Dataset registry support for geoimport (admin dashboard, plan: .claude/plans/admin-dashboard.plan.md).

redact     scrub secrets from any text that is stored or printed
runs       record every CLI (later: worker) execution in app.jobs / app.runs, with a redacted log tail
registry   sync data/recipes/*.yaml into app.recipes (YAML stays the source of truth), key status
outputs    discover each dataset's outputs (src table -> pub views -> tiPG collections -> projects),
           footprints and coverage
health     live checks per output
freshness  compare what we loaded with what upstream offers now
"""
