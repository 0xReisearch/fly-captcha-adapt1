"""Verify live sensory computation against the original fixed-response contract."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from sensory import LiveEye

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vendor', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    eye = LiveEye(args.vendor)
    tiles = json.loads((ROOT/'data/tiles.json').read_text())['tiles']
    checks = []
    for tile in tiles[::54]:
        with Image.open(ROOT/'data/tiles'/f'{tile["id"]}.jpg') as image:
            eye.reset()
            features, observation, counts = eye.observe(image)
            old = json.loads((ROOT/'data/vision'/f'{tile["id"]}.json').read_text())
            assert observation['spike_sha256'] == old['spike_sha256']
            np.testing.assert_array_equal(features, list(old['features'].values()))
            assert observation['spike_sha256'] == hashlib.sha256(counts.tobytes()).hexdigest()
            # A second glimpse has its own measured response, not a reused tile cache.
            _, glimpse, _ = eye.observe(image, 'center')
            assert glimpse['spike_sha256'] != observation['spike_sha256']
            eye.reset()
            again, repeated, _ = eye.observe(image)
            np.testing.assert_array_equal(again, features)
            assert repeated['spike_sha256'] == observation['spike_sha256']
            checks.append({'tile_id': tile['id'], 'reset_matches_original': True,
                           'glimpse_changes_response': True, 'state_reset_reproducible': True})
    eye.verify_fixed_graph()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'checks': checks, 'calls': eye.calls, 'graph_fixed': True}, indent=2)+'\n')
    print(f'Passed {len(checks)} live/reset/glimpse checks; {eye.calls} actual simulations.')


if __name__ == '__main__':
    main()
