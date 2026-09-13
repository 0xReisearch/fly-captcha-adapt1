# Live neural fly: local results

Measurements from CPU execution with a local Adapt-1 controller.

The fly-side artificial plastic readout chooses tile actions. Adapt-1
controls the optional inspection budget. The reconstructed biological
connection weights remain fixed. This is reward learning in a fly-based
agent, not validated biological learning in the original connectome.

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

## Clear-photo pilot (non-discounted attention)

| Test condition | Seed 17 | Seed 29 | Seed 43 | Mean |
|---|---:|---:|---:|---:|
| Before reward learning | 90/180 (50.00%) | 90/180 (50.00%) | 90/180 (50.00%) | 50.00% |
| Trained fly + Adapt-1 controller | 180/180 (100.00%) | 180/180 (100.00%) | 180/180 (100.00%) | 100.00% |
| Fly readout never trained | 90/180 (50.00%) | 90/180 (50.00%) | 90/180 (50.00%) | 50.00% |
| Neural features removed | 90/180 (50.00%) | 90/180 (50.00%) | 90/180 (50.00%) | 50.00% |
| Trained fly, overview only | 180/180 (100.00%) | 180/180 (100.00%) | 180/180 (100.00%) | 100.00% |
| Trained fly, always permit inspection | 176/180 (97.78%) | 176/180 (97.78%) | 180/180 (100.00%) | 98.52% |

| Run | Training rewards | Attention updates | Core feedbacks | Test extra inspections | Test boards passed |
|---|---:|---:|---:|---:|---:|
| 17 | 360 | 4 | 360 | 0 | 20/20 |
| 29 | 360 | 1 | 360 | 0 | 20/20 |
| 43 | 360 | 252 | 360 | 0 | 20/20 |

Artifacts: `artifacts/live-fly-core/seed-{17,29,43}/`.

Elapsed time per full evaluation: 150-183 seconds. This includes all controls, not just training.
Peak process RSS including local Core: 1882 MB.

## Limited-visibility pilot (non-discounted attention)

| Test condition | Seed 17 | Seed 29 | Seed 43 | Mean |
|---|---:|---:|---:|---:|
| Before reward learning | 90/180 (50.00%) | 90/180 (50.00%) | 90/180 (50.00%) | 50.00% |
| Trained fly + Adapt-1 controller | 160/180 (88.89%) | 174/180 (96.67%) | 180/180 (100.00%) | 95.19% |
| Fly readout never trained | 90/180 (50.00%) | 90/180 (50.00%) | 90/180 (50.00%) | 50.00% |
| Neural features removed | 90/180 (50.00%) | 90/180 (50.00%) | 90/180 (50.00%) | 50.00% |
| Trained fly, overview only | 91/180 (50.56%) | 91/180 (50.56%) | 91/180 (50.56%) | 50.56% |
| Trained fly, always permit inspection | 160/180 (88.89%) | 174/180 (96.67%) | 180/180 (100.00%) | 95.19% |
| Trained decisions, untrained viewing policy | 176/180 (97.78%) | 174/180 (96.67%) | 179/180 (99.44%) | 97.96% |

| Run | Training rewards | Attention updates | Core feedbacks | Test extra inspections | Test boards passed |
|---|---:|---:|---:|---:|---:|
| 17 | 360 | 320 | 360 | 180 | 9/20 |
| 29 | 360 | 358 | 360 | 180 | 14/20 |
| 43 | 360 | 247 | 360 | 180 | 20/20 |

Artifacts: `artifacts/live-fly-attention-audit/seed-{17,29,43}/`.

Elapsed time per full evaluation: 219-247 seconds. This includes all controls, not just training.
Peak process RSS including local Core: 1855 MB.

## Limited visibility with recency-weighted attention

| Test condition | Seed 17 | Seed 29 | Seed 43 | Mean |
|---|---:|---:|---:|---:|
| Before reward learning | 90/180 (50.00%) | 90/180 (50.00%) | 90/180 (50.00%) | 50.00% |
| Trained fly + Adapt-1 controller | 175/180 (97.22%) | 175/180 (97.22%) | 180/180 (100.00%) | 98.15% |
| Fly readout never trained | 90/180 (50.00%) | 90/180 (50.00%) | 90/180 (50.00%) | 50.00% |
| Neural features removed | 90/180 (50.00%) | 90/180 (50.00%) | 90/180 (50.00%) | 50.00% |
| Trained fly, overview only | 91/180 (50.56%) | 91/180 (50.56%) | 91/180 (50.56%) | 50.56% |
| Trained fly, always permit inspection | 175/180 (97.22%) | 175/180 (97.22%) | 180/180 (100.00%) | 98.15% |
| Trained decisions, untrained viewing policy | 175/180 (97.22%) | 175/180 (97.22%) | 180/180 (100.00%) | 98.15% |

| Run | Training rewards | Attention updates | Core feedbacks | Test extra inspections | Test boards passed |
|---|---:|---:|---:|---:|---:|
| 17 | 360 | 320 | 360 | 180 | 16/20 |
| 29 | 360 | 358 | 360 | 180 | 15/20 |
| 43 | 360 | 247 | 360 | 180 | 20/20 |

Artifacts: `artifacts/live-fly-attention-recency/seed-{17,29,43}/`.

Elapsed time per full evaluation: 231-245 seconds. This includes all controls, not just training.
Peak process RSS including local Core: 1863 MB.

## Interpretation

- Every run starts with a new fly readout and a new local Core engine/Domain.
- Each run trains once on 360 photos, then tests on 180 hash-disjoint photos without feedback.
- Three seeds reuse the same image split. They are not 540 unique test images.
- Frozen-state assertions cover fly weights/readout statistics and Core retained learning state.
- Removing neural features destroys the demonstrated classification performance.
- The clear-photo task does not require additional inspections. There is no claimed attention gain on it.
- The two-pixel overview condition is a separate, deliberately limited-visibility experiment. All images undergo the same transform.
- Compare its trained viewing policy with the untrained-viewing control before attributing any gain specifically to learned gaze.
- Allowing inspection and learning which crop to inspect are different interventions; their evidence is reported separately.
- These are small demonstration tasks, not universal CAPTCHA or biological cognition claims.

## Verification

- Eight reward-circuit/controller contract unit tests passed.
- Nine hosted application tests passed.
- Ten live sensory checks matched original wide-view features/hashes and verified reset and changed-glimpse responses.
- Desktop/mobile browser checks passed: nonblank scenes, actual spike activity, moving anatomical fly, no horizontal overflow, and no JavaScript errors.
- Actual local start/stop test verified no new observations or trials after cancellation completed.

See [README.md](README.md) for commands, architecture and hosting requirements.
