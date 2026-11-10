# Run stitch

Goal: Smoke test: each worker edits one file, stitcher confirms both markers exist.

## Workers
- t1: ok Mark alpha → smoke/alpha.txt
- t2: ok Mark beta → smoke/beta.txt

## Stitcher
APPROVE

Changed files:
- `smoke/alpha.txt` — contains `SMOKE_ALPHA=ok` (original `alpha start` preserved)
- `smoke/beta.txt` — contains `SMOKE_BETA=ok` (original `beta start` preserved)

Both markers verified; no cross-file fixes needed.

## Files touched by stitcher
(none)
