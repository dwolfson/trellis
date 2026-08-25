<!-- Resource Explorer's own governance metrics

Design §5's rule: **RE may emit a number only if a declared `GovernanceMetric`
exists for it, with `measurement` and `target` filled in. No metric, no number.**

Every metric below was already being computed and published; none was declared.
Writing them down is the point — the `measurement` text is the formula the code
actually uses, and the `target` is the threshold the code already applies. Where
a target looks arbitrary that is a true statement about the metric, now visible
instead of buried in a comparison.

These are **RE's own opinions**, not a relayed external standard. §5's rule set
is explicit that an external standard is `CertificationType` + `QualityAnnotation`
instead, with no metric, because there the standard is the authority.

Heading levels are load-bearing: Dr.Egeria reads `##` as the command and `###`
as its fields. An earlier version used `#`/`##` and every command was silently
skipped — the run reported success and created nothing.
-->

___

## Create Governance Metric

### Display Name
Repository Activity

### Summary
How much recent development a repository is receiving.

### Domain Identifier
DATA

### Measurement
Commits in the last 30 days weighted 3, the last 90 days weighted 0.5, and the
last 365 days weighted 0.1, summed and capped at 100. Computed by
`resource_explorer/surveyors/sub_surveyors/health.py` from `project_commits`.

### Target
40 or above. Below that a repository is receiving occasional rather than
regular maintenance. The weighting deliberately favours recent work: a burst of
commits last year should not read as activity today.

### Importance
Medium

### Content Status
ACTIVE

### Qualified Name
GovernanceMetric::ResourceExplorer::RepositoryActivity::1.0

___

## Create Governance Metric

### Display Name
Repository Community

### Summary
Whether a repository has a community around it beyond its maintainers.

### Domain Identifier
DATA

### Measurement
Stars divided by 100 weighted 20, forks divided by 20 weighted 20, and
contributors capped at 50 weighted 1.2, summed and capped at 100. Computed by
`health.py` from `project_stats`.

### Target
30 or above. Below that a project is effectively single-maintainer, which is a
sustainability risk rather than a quality judgement. The contributor cap exists
because the difference between 50 and 500 contributors does not change the
answer to that question.

### Importance
Medium

### Content Status
ACTIVE

### Qualified Name
GovernanceMetric::ResourceExplorer::RepositoryCommunity::1.0

___

## Create Governance Metric

### Display Name
Repository Release Cadence

### Summary
How regularly a repository publishes releases.

### Domain Identifier
DATA

### Measurement
100 minus the mean number of days between releases, floored at 0, and 0 when a
repository has published no releases at all. Computed by `health.py`.

### Target
50 or above, meaning releases roughly every 50 days or better. A score of 0 is
ambiguous by construction — it means either no releases or a very long gap —
and a consumer needing to tell those apart must read `releases_count` rather
than this metric.

### Importance
Low

### Content Status
ACTIVE

### Qualified Name
GovernanceMetric::ResourceExplorer::RepositoryReleaseCadence::1.0

___

## Create Governance Metric

### Display Name
Repository Freshness

### Summary
How recently a repository was last touched.

### Domain Identifier
DATA

### Measurement
100 minus twice the number of days since the last push, floored at 0. Where the
last push date is unknown the value is 50, which is a declared placeholder and
not a measurement.

### Target
60 or above, meaning pushed within roughly the last 20 days. The 50-for-unknown
case sits below target on purpose: an unknown push date should not read as
healthy.

### Importance
Medium

### Content Status
ACTIVE

### Qualified Name
GovernanceMetric::ResourceExplorer::RepositoryFreshness::1.0

___

## Create Governance Metric

### Display Name
Overall Repository Health

### Summary
A single headline score combining activity, community, release cadence and
freshness.

### Domain Identifier
DATA

### Measurement
The unweighted mean of Repository Activity, Repository Community, Repository
Release Cadence and Repository Freshness. Unweighted is a deliberate choice, not
an absence of one: no evidence supports weighting these against each other, so
asserting weights would claim knowledge RE does not have.

### Target
70 or above, which is the band the UI already renders as healthy. Between 40 and
70 renders as a warning and below 40 as a gap. A repository can miss this target
for entirely legitimate reasons — a finished library needs no recent commits —
so this is a prompt to look, never a verdict.

### Importance
High

### Content Status
ACTIVE

### Qualified Name
GovernanceMetric::ResourceExplorer::OverallRepositoryHealth::1.0

___

## Create Governance Metric

### Display Name
Documentation Signal Count

### Summary
How many distinct kinds of documentation a repository provides.

### Domain Identifier
DATA

### Measurement
The count of distinct documentation collection types present, plus the count of
documentation hygiene files found (README, CONTRIBUTING, CODE_OF_CONDUCT and
similar). Computed by
`resource_explorer/surveyors/sub_surveyors/documentation.py` from the file
inventory.

### Target
5 or above, which the UI labels Comprehensive; 2 to 4 is Partial and below 2 is
Minimal. This counts KINDS of documentation, not quality or quantity of it — a
repository with one excellent guide scores lower than one with five stubs, and
that is a real limitation of the metric rather than a judgement about either
repository.

### Importance
Medium

### Content Status
ACTIVE

### Qualified Name
GovernanceMetric::ResourceExplorer::DocumentationSignalCount::1.0
