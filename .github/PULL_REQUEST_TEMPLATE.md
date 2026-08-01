## What changed

<!-- One or two sentences. What does this PR do? -->

## Why

<!-- The problem this solves. Link an issue if there is one. -->

## Security impact

<!-- Required. Write "none" if nothing changes about containment. -->

- [ ] Does not weaken any risk classification (SAFE / RISKY / CRITICAL)
- [ ] Does not introduce a new execution path outside the hologram
- [ ] Invisible mode, autopilot, and shell integration remain opt-in
- [ ] Any new residual risk is documented in the README

## Testing

```bash
python -m unittest discover -s tests -v
```

<!-- Paste the result, plus anything you verified manually. -->
