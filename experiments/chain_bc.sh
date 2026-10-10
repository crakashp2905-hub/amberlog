#!/usr/bin/env bash
# Run Phase C after Phase B, with two things resolved from Phase B's result
# rather than chosen by hand:
#
#   best_fixed   whichever sharing policy actually won Phase B, because PC is
#                registered to beat the best *fixed* policy and picking a weak
#                one would be the H3 mistake inverted.
#   --registered only when PB1 was supported. The Phase C registration gates it:
#                a threshold applied to a surface already measured to be flat is
#                not a test, so without the gate the run is exploratory and PC is
#                reported as neither supported nor killed.
set -u

SCRATCH="$1"
B_OUT="$SCRATCH/phase_b.txt"
C_OUT="$SCRATCH/phase_c.txt"

until grep -qE "PB1:|Traceback" "$B_OUT" 2>/dev/null; do sleep 20; done

if grep -q "Traceback" "$B_OUT"; then
  echo "PHASE B FAILED; not starting Phase C"
  tail -20 "$B_OUT"
  exit 1
fi

# The winning selective policy, read off Phase B's own summary line.
BEST=$(grep -oE "PB1 best selective policy: [a-z_]+" "$B_OUT" | awk '{print $5}' | tail -1)
BEST=${BEST:-share_overlap}

if grep -q "PB1: SUPPORTED" "$B_OUT"; then
  FLAG="--registered"
  echo "PB1 SUPPORTED -> Phase C runs as a registered test, best_fixed=$BEST"
else
  FLAG=""
  echo "PB1 not supported -> Phase C runs as EXPLORATORY, best_fixed=$BEST"
fi

python -u -m experiments.phase_c --seeds 3 --rounds 16 --quiet \
  --best-fixed "$BEST" $FLAG \
  --out research/results/phase-c-decisions.json > "$C_OUT" 2>&1

echo "PHASE C DONE"
tail -4 "$C_OUT"
