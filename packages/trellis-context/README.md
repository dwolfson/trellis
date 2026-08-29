# trellis-context

Turns a **ContextSpec** and some resolved sources into a bounded context, plus a
**manifest** describing exactly what it did and why.

**The packer is ordinary code, not an agent.** Determinism, monotonicity,
symmetric packing and the hard budget ceiling are all unavailable if a model
decides what to include — and those guarantees are the reason this exists rather
than a prompt template.

**It never resolves anything.** Callers hand it results. That keeps it free of
stores, clients and credentials, and makes every test a pure function of its
input.

**The manifest is the point, not a debugging extra.** It is what makes a compile
explainable ("why is this here"), auditable ("re-run it"), and negotiable ("drop
that section and try again"). A packer that returns only text has thrown away
the part a person can act on.

See `docs/context-compilation-design.md` §2 (what a compile adds), §11
(explainability), §14 (the invariants), §16 (why the packer is not an agent).
