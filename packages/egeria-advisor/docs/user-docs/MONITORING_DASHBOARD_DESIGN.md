# Collection Monitoring Dashboard Design

**This was a design proposal and has since been implemented** as the admin dashboard at
`http://localhost:8880/admin` (collection health, query analytics, feedback review, LGCI plan
usage and session transcripts) and the terminal dashboard
(`python -m advisor.dashboard.terminal_dashboard`, 5-second refresh). It also referenced
Milvus, which the project no longer uses (pgvector is the active backend).

The original design proposal is preserved in git history (`git log -- docs/user-docs/MONITORING_DASHBOARD_DESIGN.md`)
for reference on the original design rationale, but should not be used as a guide to current
behavior — check the running `/admin` page and `advisor/dashboard/terminal_dashboard.py`
directly for what's actually implemented.
