<!-- Skeleton. Fill the placeholders in M9; keep the structure. -->
# flaky-anything

**Your flaky test isn't random. Here's why it fails.**

flaky-anything turns a test that fails "sometimes" into a command that fails **every time**,
tells you the hidden input that causes it, and hands you a fix that's verified not to weaken the test.

<!-- GIF: test fails 1/50 → `flaky-anything diagnose` → "fails 50/50 with this command" → fix → 0/500, rate < 0.6% (95%) -->

```bash
uv add --dev flaky-anything          # or: pip install flaky-anything
flaky-anything hunt                  # find flaky tests
flaky-anything diagnose <test>       # why it fails + deterministic repro
flaky-anything fix <test> --emit-prompt   # hand the solved puzzle to your agent
flaky-anything verify <test>         # prove it: N perturbed runs + confidence bound
```

## What it finds
| Hidden input | Example | v0.1 |
|---|---|---|
| Test order | earlier test leaves a module cache dirty | ✅ |
| Clock | breaks on Jan 31, at midnight, on DST days | ✅ |
| Time zone | assumes the machine is in UTC | ✅ |
| Random / hash seeds | set iteration order, unseeded `random` | ✅ |
| Async scheduling, CPU load, network | races, slow deps | 🔜 |

## How it works
Every hidden input becomes a **knob**. Every run records its full knob configuration. When a run
fails we **replay that exact configuration**; if it fails reliably we've got a deterministic
reproducer, then we switch knobs back one at a time to find the minimal cause (and bisect test
order down to the single polluting test). Fixes run in a git worktree, must pass the reproducer,
must survive a **mutation-testing guard** (the fixed test must still catch the bugs the original
caught), and must pass hundreds of perturbed runs.

## Results
<!-- table from docs/DOGFOOD.md: repo | flaky tests found | root causes | PRs -->

## What it can't do (yet)
- Only pytest. Races and network flakes are reported as `uncontrolled` in v0.1, not fixed.
- "0 failures in 500 runs" means the failure rate is below ~0.6% at 95% confidence, not zero. We say so.

## License
MIT
