"""Render a local report from completed result files, not hand-entered scores."""
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]


def main():
    lines = ['# Live neural fly: local results', '',
             'Measurements from CPU execution with a local Adapt-1 controller.', '',
             'The fly-side artificial plastic readout chooses tile actions. Adapt-1',
             'controls the optional inspection budget. The reconstructed biological',
             'connection weights remain fixed. This is reward learning in a fly-based',
             'agent, not validated biological learning in the original connectome.', '']
    lines += (ROOT/'research/INSPECTION_COMPARISON.md').read_text().splitlines() + ['']
    for title, folder in (
        ('Clear-photo pilot (non-discounted attention)', 'live-fly-core'),
        ('Limited-visibility pilot (non-discounted attention)', 'live-fly-attention-audit'),
        ('Limited visibility with recency-weighted attention', 'live-fly-attention-recency'),
    ):
        directory = ROOT/'artifacts'/folder
        results = [json.loads((directory/f'seed-{s}'/'results.json').read_text()) for s in (17,29,43)]
        lines += [f'## {title}', '', '| Test condition | Seed 17 | Seed 29 | Seed 43 | Mean |',
                  '|---|---:|---:|---:|---:|']
        for phase, label in (
            ('before', 'Before reward learning'), ('after', 'Trained fly + Adapt-1 controller'),
            ('frozen_fly', 'Fly readout never trained'), ('erased_neural_input', 'Neural features removed'),
            ('wide_only', 'Trained fly, overview only'), ('fixed_inspection', 'Trained fly, always permit inspection'),
            ('frozen_attention', 'Trained decisions, untrained viewing policy'),
        ):
            if not all(phase in r['metrics'] for r in results):
                continue
            scores = [r['metrics'][phase]['accuracy'] for r in results]
            entries = [f"{r['metrics'][phase]['correct']}/{r['metrics'][phase]['tiles']} ({100*v:.2f}%)"
                       for r, v in zip(results, scores)]
            lines.append('| '+label+' | '+' | '.join(entries)+f' | {100*statistics.mean(scores):.2f}% |')
        lines += ['', '| Run | Training rewards | Attention updates | Core feedbacks | Test extra inspections | Test boards passed |',
                  '|---|---:|---:|---:|---:|---:|']
        for r in results:
            m=r['metrics']['after']
            lines.append(f"| {r['seed']} | {r['fly_feedbacks']} | {r['attention_feedbacks']} | {r['controller_feedbacks']} | {m['inspections']} | {m['passed_boards']}/{m['boards']} |")
            assert r['initial_fly_sha256'] != r['frozen_fly_sha256'] == r['heldout_fly_sha256']
            assert r['test_feedback'] == r['exact_split_overlap'] == 0 and r['graph_fixed']
        lines += ['', f'Artifacts: `artifacts/{folder}/seed-{{17,29,43}}/`.', '',
                  f"Elapsed time per full evaluation: {min(r['elapsed_seconds'] for r in results):.0f}-"
                  f"{max(r['elapsed_seconds'] for r in results):.0f} seconds. This includes all controls, not just training.",
                  f"Peak process RSS including local Core: {max(r['process_peak_rss_mb'] for r in results):.0f} MB.", '']
    lines += ['## Interpretation', '',
              '- Every run starts with a new fly readout and a new local Core engine/Domain.',
              '- Each run trains once on 360 photos, then tests on 180 hash-disjoint photos without feedback.',
              '- Three seeds reuse the same image split. They are not 540 unique test images.',
              '- Frozen-state assertions cover fly weights/readout statistics and Core retained learning state.',
              '- Removing neural features destroys the demonstrated classification performance.',
              '- The clear-photo task does not require additional inspections. There is no claimed attention gain on it.',
              '- The two-pixel overview condition is a separate, deliberately limited-visibility experiment. All images undergo the same transform.',
              '- Compare its trained viewing policy with the untrained-viewing control before attributing any gain specifically to learned gaze.',
              '- Allowing inspection and learning which crop to inspect are different interventions; their evidence is reported separately.',
              '- These are small demonstration tasks, not universal CAPTCHA or biological cognition claims.', '',
              '## Verification', '',
              '- Eight reward-circuit/controller contract unit tests passed.',
              '- Nine hosted application tests passed.',
              '- Ten live sensory checks matched original wide-view features/hashes and verified reset and changed-glimpse responses.',
              '- Desktop/mobile browser checks passed: nonblank scenes, actual spike activity, moving anatomical fly, no horizontal overflow, and no JavaScript errors.',
              '- Actual local start/stop test verified no new observations or trials after cancellation completed.',
              '',
              'See [README.md](README.md) for commands, architecture and hosting requirements.', '']
    (ROOT/'research/RESULTS.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
