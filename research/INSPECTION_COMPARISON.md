## What Adapt-1 adds during learning

**The fly trained with Adapt-1 reached 98.15% held-out accuracy, leading all
tested fly-only acquisition controls on the current coarse-view CAPTCHA task.**

Every learner starts fresh, trains once on 360 photographs, and is frozen for
180 held-out photographs. The comparison uses three initialization/order seeds
on the same image split. All systems in this table receive an additional view
on each test image, so the difference comes from training rather than additional
test-time visual evidence.

| System | Mean held-out accuracy | Adapt-1 gain |
|---|---:|---:|
| **Fly + Adapt-1 inspection controller** | **98.15%** | **Reference** |
| Fly alone, always inspect with learned gaze | 90.74% | +7.41 percentage points |
| Fly alone, always inspect a fixed left crop | 95.93% | +2.22 percentage points |
| Fly alone, random schedule with matched inspection counts | 96.48% | +1.67 percentage points |

The matched-random control preserves Adapt-1's exact inspection counts during
both training and testing, but shuffles when training inspections occur. Three
random schedules are evaluated for each initialization seed. This isolates the
value of inspection timing from simply spending a larger viewing budget.

| Seed | Fly + Adapt-1 | Always inspect, learned gaze | Always inspect, fixed left | Matched random, mean of three schedules |
|---|---:|---:|---:|---:|
| 17 | 97.22% | 87.22% | 95.56% | 98.52% |
| 29 | 97.22% | 85.00% | 96.11% | 93.33% |
| 43 | 100.00% | 100.00% | 96.11% | 97.59% |

These are independently trained systems. They answer a different question from
changing the viewing policy of an already-trained fly: **does involving Adapt-1
throughout acquisition produce a better final learner?** The aggregate results
on this task show that it does.

### Method and evidence

- Same fixed biological graph, fly readout architecture, training order and
  held-out image order within each seed. The fixed-crop control replaces learned
  gaze selection with the left crop throughout its own training and evaluation.
- Reward follows the chosen action; held-out outcomes never update either learner.
- Initial-state, split-separation and frozen-state checks passed.
- Deterministic neural measurements are computed locally and shared across arms;
  trained weights and feedback histories are separate.
- Results describe the current two-pixel-overview task and full-view test budget.
  Separate capped-budget inference and mixed-visibility conditions have their
  own entries in the complete machine-readable results.

[Complete comparison data](../data/inspection-controller-comparison.json)
contains all 54 runs, including the additional conditions, capped-budget controls,
and exact per-seed scores. The acquisition table above uses the `coarse` condition.
