# HTDY X5-05 Rolling OOS Stability

- Mode: `rolling_oos_stability`
- Proposal: `DIAGNOSTIC_CONFIRMS_REJECTION`
- X5-04 Gate: `OOS_HARD_REJECT_TRIGGERED`
- Packet hash: `1d0fe23c2b275ede0d5c96e5ffa477fd1008571cb0087dd7fb845b80b8c8e8c7`

## Folds

- `walk_forward_a_test`: status=completed, audit=passed, trades=84, return=-0.020732620499999962
- `walk_forward_b_test`: status=completed, audit=passed, trades=101, return=-0.023961873000000022
- `walk_forward_c_test`: status=completed, audit=passed, trades=166, return=-0.03930214199999999

X5-05 is diagnostic-only after the X5-04 hard reject and cannot overturn it.
