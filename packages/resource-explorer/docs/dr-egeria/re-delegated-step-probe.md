## Create Governance Action Type
### Display Name
RE Delegated Step Probe — Write Audit Log

### Qualified Name
GovActionType::REDelegatedStepProbe::WriteAuditLog

### Description
Case-4 live-verification probe for docs/survey-execution.md (§7) — a
harmless, side-effect-limited target (writes one message to the audit
log) to prove Resource Explorer's initiate_action_type_and_wait() /
EgeriaDelegatedStepSurveyor(action_type_qualified_name=...) trigger path
end to end, working around PYEGERIA_ISSUES.md ISSUE-50 (the direct
initiate_engine_action() path 404s). Not part of any real Survey
Definition — delete once case 4 is live-verified and a real delegated
step target is chosen.

### Content Status
ACTIVE

___

## Link Action to Action Executor
### Governance Action Type
GovActionType::REDelegatedStepProbe::WriteAuditLog

### Governance Engine
Stewardship

### Request Type
write-to-audit-log

### Description
Routes the probe through the Stewardship engine's real, standard
WRITE_AUDIT_LOG governance service (request type "write-to-audit-log",
from the core content pack's RequestTypeDefinition.WRITE_AUDIT_LOG) —
already registered on any platform loaded with the standard content pack,
no new registration needed. **Verify "Stewardship" resolves correctly
before running this against a real server** — confirmed from
GovernanceEngineDefinition.java as the engine's plain `name` field
(`GovernanceEngineDefinition.STEWARDSHIP_ENGINE`, display name
"Stewardship Engine", engineUserId "stewardshipengine"), but not
live-checked against this specific deployment's actual registered
qualifiedName — if `Link Action to Action Executor` can't resolve it by
that value, look up the real Stewardship GovernanceEngine element
(`find_metadata_elements` filtered to typeName="GovernanceEngine") and
substitute its actual qualifiedName/displayName here. This link is also
the first live verification of `Link Action to Action Executor` itself —
`egeria-python/CLAUDE.md` flags it as "not yet verified against a live
server" since it was added 2026-07-15.
