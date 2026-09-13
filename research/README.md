# Live fly neural learner

Local-Core research runner. The live website shares its simulator, readouts
and UI but uses the visitor-owned production adapter described in the root
[README](../README.md). Commands here specifically use local Core.

## Roles

**Fly simulation:** every presented view drives the actual native CPU simulator
over the fixed MaleCNS graph (166,700 neurons). No cached visual responses are
used by the experiment. Neural voltage and other fast state persist between the
overview and the next glimpse of an image, and reset before the next image.

**Fly-side learner:** an artificial, reward-plastic readout receives 64 pooled
lamina spike measurements. It chooses `select` or `leave`. A second plastic
readout chooses a left, center, or right visual inspection when permitted. The
chosen crop is actually presented to the simulator; it changes the retinal
input and subsequent activity. It is not a camera-only animation.

**Adapt-1:** a fresh local Domain chooses `answer_now` or `inspect_again` using
the fly's current decision margin, sensory variation and experience count. It
learns from the final outcome with an extra-inspection cost. It has no tile
selection action, fruit label, image identifier, pixel input, or neural feature
vector. The fly readout still chooses the tile action if Core abstains; that
abstention means no additional inspection and is recorded explicitly.

**Environment:** returns binary correctness only after the fly's action has
been selected. The training task asks for banana photos. Reward is informative
per tile, not a single sparse reward for an entire nine-tile board. Target labels
stay in the scoring harness; they are not passed into either policy beforehand.

**Display:** uses the original Fruitless fly assets and soma coordinates. The
activity overlay shows the current simulation's measured 60 ms spike counts,
for each view. Body movement illustrates inspections rather than biological
locomotion.

## What the plasticity implementation is

The learning circuit is an experimental attachment, not a reconstruction of
biological mushroom-body plasticity. It has a fixed random nonlinear expansion
and trainable action readouts. Recursive least squares updates only the selected
action's predicted reward. Positive outcomes reinforce that activity/action
association; negative outcomes suppress it. The earlier inspection choice keeps
an eligibility vector until the final outcome arrives, so the reward also
updates its attention readout. The outcome of the unchosen action is not fitted.
Attention discounts older outcomes as its downstream answer circuit changes, and
explores alternative views during training. Decision inference is frozen in the
test. These are ordinary numerical learning controls, not simulated dopamine.

No original biological connection weight changes. No dopamine dynamics or
reward-induced biological spike patterns are claimed. This distinction is
important: the fly-based agent learns, but this does not demonstrate that the
unmodified connectome itself learns the task. The readout method is established
numerical learning, not a proposed new neuroscience discovery.

Background for the separation between fixed connectivity, dynamics and learning:
[upstream simulator](https://github.com/nftechie/doomfly),
[mushroom-body reward-prediction model](https://pmc.ncbi.nlm.nih.gov/articles/PMC8105414/),
[experimental fly reversal learning](https://www.nature.com/articles/s41467-021-21388-w).
These sources motivate a future biologically constrained model; they do not
validate the artificial circuit used here.

## Run locally

Use the project's existing sensory dependencies and a Python environment that
can also run local Adapt-1. `requirements-sensory.txt` supplies NumPy, Pillow,
PyArrow and the simulator prerequisites. Prepare the pinned graph/kernel using
`setup_fly.py` if it is not already available. No GPU is needed. These experiments
explicitly disable visible GPU devices and use a single numerical compute thread.

From this repository, in a Python environment with local Core installed:

```bash
env CUDA_VISIBLE_DEVICES='' HIP_VISIBLE_DEVICES='' HF_HUB_OFFLINE=1 \
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python research/server.py \
  --vendor vendor/doomfly \
  --core /path/to/neuroadapt --port 8794
```

Open http://127.0.0.1:8794. The lab defaults to a two-pixel overview followed by
optional detailed inspections, making attention consequential. Pass
`--overview-size 100` for the clear-photo task. Start fresh creates a new local engine, Domain and fly
learner. Stop learning cancels before the next observation/controller call or
feedback; an operation already in progress may finish. The listener is loopback
only and rejects cross-origin starts. It never asks for a production API key.
After the held-out test, the browser retains the trained fly and its local
Adapt-1 inspection controller. **Another CAPTCHA** opens a practice board. Click
the photos on the 3D floor to make your own selections, then **Lock my picks** to
compare answers. **Fly goes solo** runs a board without human participation.
Repeat boards without restarting training. Stop also works during practice and
preserves the trained learner; Start fresh explicitly replaces it.

Practice reshuffles nine photos from the existing held-out set. Both learners
remain frozen, receive no practice feedback, and are fingerprint-checked after
each completed board. Human picks reach only the comparison scorer, not the fly
or Core. These rounds are entertainment, not additional independent evaluation;
the original results and learning curve stay unchanged. Separate records go to
`practice.jsonl`. The illustrated banana salary counts perfect nine-tile boards
in training, frozen evaluation and completed practice; it is a display counter,
not a change to the per-tile learning reward. Reactions and identity verdicts
are scripted presentation, not language generated by the fly.

The trained session lives in server memory. Restarting the server requires a new
training run; refreshing the browser does not. This remains a single-user local
lab, not a multi-tenant deployment. The command-line evaluator also runs the
disabled-readout, input-erasure, and viewing-policy controls separately.

For a full three-seed command-line evaluation:

```bash
env CUDA_VISIBLE_DEVICES='' HIP_VISIBLE_DEVICES='' HF_HUB_OFFLINE=1 \
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python research/run.py \
  --vendor vendor/doomfly \
  --core /path/to/neuroadapt \
  --seeds 17,29,43 --output artifacts/my-live-fly-run
```

Use a new output directory. No prior task checkpoint is loaded. Remove `--core`
to test the same neural learner with a fixed inspection allowance. The optional
`--overview-size` changes the resolution of the first view, identically for all
images; extra inspection crops retain their detail. Default 100 preserves the
original photo resolution. Lower-resolution results are separate protocols.

The limited-visibility evaluation uses `--overview-size 2`. Current defaults are
`--attention-forgetting .98 --attention-epsilon .3`. The non-discounted pilots retain
all attention history and use less exploration; reproduce their configuration
with `--attention-forgetting 1 --attention-epsilon .15`. No test outcome changes
either learner in any of these runs. These are exploratory comparisons on one
image split, not a preregistered attention-method superiority study.

## Evaluation contract

Each run uses 360 training photos once, and 180 different test photos. Exact
hash overlap is checked. These are held-out images from the same four categories,
not evidence of unseen object instances or arbitrary CAPTCHA understanding.
Three seeds vary order and random circuit initialization on the same image split;
they are not 540 distinct test images or independent dataset replications.

The full run records baseline, training, frozen held-out test, a never-trained
fly control, a neural-input-erasure control, wide-only inference, and fixed-extra-
inspection inference. Controls do not update the learner. Both the fly learner
and Core's retained samples/model/calibration are fingerprinted across testing.
Hashes of biological graph weights must remain unchanged across the entire run.

Artifacts under each output's `seed-N/`:

- `results.json`: phase scores, resource use, update counts and freeze checks.
- `configuration.json`: explicit protocol and learner parameters for new runs.
- `trace.jsonl`: every action, reward, view, neural digest and controller decision.
- `domain.json`: complete experiment-controller declaration.
- `core-api-trace.jsonl`: actual local API requests and responses, no auth headers.

The live browser streams full sparse activity for the current neural window.
It does not retain full per-neuron recordings for all windows on disk; action
traces retain the computed spike digest and aggregate counts. It does not invent
spike timing inside a 60 ms window.
The small retinal preview is the actual contrast image used to sample receptors,
including any overview downsampling or chosen crop. The signed decision readout
values are predicted rewards, not calibrated probabilities. The displayed reward
prediction error comes from the actual chosen-action update.

## Runtime requirements

The standalone simulator/readout pilot peaked around 0.8 GB process RSS, and full
local runs including Core stayed below 1.9 GB. The neural simulator and fly
readouts run on CPU; no GPU is required. These are local measurements, not a
concurrency test.

To use the Neuroadapt API with your own key instead of local Core, follow the
[production reproduction instructions](../README.md#reproduce-through-production).

## Checks

```bash
env OPENBLAS_NUM_THREADS=1 .venv/bin/python \
  -m unittest discover -s research -p 'test_*.py' -v
env OPENBLAS_NUM_THREADS=1 .venv/bin/python research/verify_live.py \
  --vendor vendor/doomfly --output artifacts/live-sensory-checks.json
```

The public browser checks and their prerequisites are described in the root
[README](../README.md#tests-and-attribution).
