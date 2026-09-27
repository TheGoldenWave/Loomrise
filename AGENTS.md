# Loomrise Agent Guide

## Mission

Loomrise is an open Agent delivery workbench for AI product managers, solution engineers, and small development teams. It turns authorized business materials and processes into runnable, testable, deployable, and continuously improvable Agent applications.

The repository contains product research and planning **plus the S1 vertical-slice implementation** under `loomrise/` (contracts, execution service, adapters, scenario pack, curated cases). S1 covers one inbound request replayed end to end; the B-end workbench, multi-tenant, real external writes, release gates, and self-evolution are still **planned, not implemented**. Do not describe planned behavior as implemented.

## Required Reading

Before substantial work, read:

1. `README.md`
2. `docs/PRODUCT.md`
3. `docs/ARCHITECTURE.md`
4. `docs/ROADMAP.md`
5. `docs/OPEN-SOURCE-BOUNDARY.md`
6. `docs/S1-BUILD-REPORT.md` and `VERSION-PINS.md` before changing S1 code or dependency versions

Read `docs/REFERENCE-PROJECTS.md` before changing technology choices or adapter boundaries.

## Public / Private Boundary

- `private/` is local-only and gitignored. Never stage it, force-add it, quote it into a public file, or make public documentation depend on it.
- `docs/OPEN-SOURCE-BOUNDARY.md` is the canonical policy for deciding what may become public.
- Keep unresolved personal judgment, commercialization, budget, career strategy, employer context, private research, and unconfirmed discussions in `private/`.
- Promote material to public only after classifying, removing sensitive context, making it independently understandable, and adding an evidence status.
- Never place secrets in `private/`. Gitignored storage is not a secret manager.

## Product Truth

- Core users are AI product managers, solution engineers, and small development teams. Business PM and operations users are co-builders and acceptance users.
- The product owns `ScenarioPack`, `AgentSpec`, `AgentVersion`, `ExecutionService`, `ServiceRequest`, `RunEvent`, `DecisionPolicy`, `Case`, `ChangeProposal`, and `Release`.
- AgentScope, Pipecat, AG-UI, OpenTelemetry, Langfuse, and other frameworks stay behind adapters. Loomrise is not a wholesale fork of Dify, Octop, or an upstream runtime.
- Text and voice entries must share business state, permissions, tools, cancellation semantics, and result persistence.
- A model saying an action is complete is not evidence. Completion requires a persisted business result and an external result identifier where applicable.
- Use fictional or explicitly authorized materials in public examples. Never use employer, customer, or third-party private assets.

## Documentation Rules

- Write project documentation in Chinese unless an English identifier or public API name is clearer.
- Give evolving documents a version and date. State whether content is confirmed, pending validation, pending decision, planned, implemented, or verified.
- Do not include private rationale merely to make a public decision look more complete.
- When positioning changes, update every affected public document in the same task: `README.md`, `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and relevant references.
- Do not publish budget estimates, time quotes, personal branding plans, or marketing schedules unless explicitly approved for public release.
- Do not claim production readiness, enterprise readiness, statistical significance, first-of-kind status, or measured performance without reproducible evidence.

## Change Workflow

1. Inspect Git status and preserve unrelated user changes.
2. Classify new information as public or private before writing it.
3. Make the smallest coherent documentation or code change.
4. Update cross-references and status labels.
5. Verify links, terminology, privacy boundaries, and Git ignore behavior.
6. Report what was verified and what remains unverified.

Use `rtk` as the shell-command prefix in this environment.

## Required Verification

Before considering documentation work complete, run:

```text
rtk git status --short
rtk git diff --check
rtk git check-ignore -v private/
```

Also inspect staged paths when anything is staged. If `private/` or a sensitive file appears, stop and remove it from staging before continuing. Never rewrite Git history or force-add files unless the user explicitly requests it.

## Architecture Guardrails

- Keep framework-private state behind adapters and out of public domain contracts.
- Version every executable business configuration and evaluation suite.
- Preserve idempotency, cancellation confirmation, permission re-checks, budget limits, and audit evidence in designs.
- Treat voice playback state, generation state, and task completion as separate facts.
- Keep hard rules and approval authority outside model scores. Optimization may propose changes but must not silently edit permissions, prices, commitments, or safety rules.
