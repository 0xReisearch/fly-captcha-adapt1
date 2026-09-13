"""Export CAPTCHA spikes for the original Fruitless renderer, without retraining."""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.feather as feather

from fly_vision import FlyVision, ROOT


def main():
    source = ROOT / 'vendor/fruitless'
    out = ROOT / 'data/anatomy'
    out.mkdir(exist_ok=True)
    ids = np.fromfile(source / 'experiment/neuron-ids.u32', dtype='<u4')
    positions = np.fromfile(source / 'experiment/positions.f32', dtype='<f4').reshape(-1, 3)
    assert len(ids) == len(positions) and len(set(ids)) == len(ids)
    index = {int(body): i for i, body in enumerate(ids)}
    nodes = feather.read_table(ROOT / 'vendor/doomfly/connectome_data/malecns_v1/normalized/neurons.feather').to_pandas()
    mapped = np.full((len(nodes), 3), np.nan, dtype='<f4')
    for i, body in enumerate(nodes.source_id):
        if int(body) in index:
            mapped[i] = positions[index[int(body)]]
    mapped.tofile(out / 'positions.f32')
    vision = FlyVision()
    trials = {}
    checks = []
    for i, tile in enumerate(json.loads((ROOT / 'data/tiles.json').read_text())['tiles']):
        key = tile['id']
        original = json.loads((ROOT / 'data/vision' / f'{key}.json').read_text())
        result = vision.encode(ROOT / 'data/tiles' / f'{key}.jpg')
        assert result['spike_sha256'] == original['spike_sha256'], key
        assert result['features'] == original['features'], key
        counts = vision.brain.counts
        active = np.flatnonzero(counts)
        # One integrated 60 ms observation, NOT fabricated 10 ms spike timing.
        trials[key] = {'events': [[0, int(n), int(counts[n])] for n in active]}
        visible = np.isfinite(mapped[active]).all(axis=1)
        checks.append({'tile_id': key, 'spike_sha256': result['spike_sha256'],
                       'spikes': int(counts.sum()), 'active_neurons': len(active),
                       'visible_active_neurons': int(visible.sum())})
        if i % 60 == 0:
            print(f'{i + 1}/540 verified', flush=True)
    payload = json.dumps({'mAL': [], 'P1': [], 'trials': {'measured': trials}}, separators=(',', ':')).encode()
    (out / 'activity.json.gz').write_bytes(gzip.compress(payload, mtime=0))
    report = {'source': 'https://github.com/nicodunks/fruitless',
              'revision': '0943b2c00b47a97c8e22438b11192b33d6779f56',
              'neurons': len(nodes), 'positioned_neurons': int(np.isfinite(mapped).all(axis=1).sum()),
              'mapping': 'MaleCNS body ID join; no positional/index equivalence assumed',
              'window_ms': 60, 'all_cached_features_and_spike_hashes_match': True,
              'activity_sha256': hashlib.sha256(payload).hexdigest(), 'tiles': checks}
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f"Exported {len(trials)} observations, {report['positioned_neurons']} real soma positions", flush=True)


if __name__ == '__main__':
    main()
