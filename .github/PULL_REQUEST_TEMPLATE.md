<!--
Delivery evidence lives here, in the PR description (AGENTS.md, "Delivery evidence discipline").
Keep the three evidence headings. A docs-only / copy-only / dependency-bump PR may keep only
"What changed and why" and must say so under it.
-->

## Summary

<!-- What problem this solves and what the user sees change. -->

## What changed and why

<!-- 修改文件说明. Per file: what changed and why. Name the function and the branch; "fixed a bug" is not a description.
     List added and deleted files. Mention files that look related and were deliberately left alone. -->

## Performance

<!-- 性能分析. Measured numbers with the command, environment and sample size. Answer each:
     steady-state cost; cost and frequency of any new path; new syscalls / network / disk / threads; memory growth.
     Adjectives ("negligible", "faster") are not analysis. -->

## Real-machine run

<!-- 实机运行记录. What ran on the real machine (not CI, not mocks): commands, real output, and the user-visible
     behaviour that was confirmed. For anything that cannot be verified automatically, show the probe evidence for why. -->

## Tests

<!-- Which tests ran, and why that scope is enough (AGENTS.md risk gate). Say so if the full suite was skipped. -->

## Docs

<!-- Tick what applies; see docs/adr/README.md for when an ADR is required.
- [ ] CHANGELOG.md: one line (user-visible change)
- [ ] Topic doc under docs/ updated (a mechanism, invariant or troubleshooting conclusion changed)
- [ ] ADR added under docs/adr/ (new feature area, architecture boundary, a trade-off someone will want to undo, or a removal)
-->
