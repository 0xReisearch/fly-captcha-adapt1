"""CPU deployment smoke test; no API key or Core calls."""
import argparse
import json
from pathlib import Path

from PIL import Image
import numpy as np

from sensory import LiveEye

parser = argparse.ArgumentParser()
parser.add_argument('--vendor', default='vendor/doomfly')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
tile = json.loads((root/'data/tiles.json').read_text())['tiles'][0]['id']
eye = LiveEye(args.vendor, 2)
with Image.open(root/'data/tiles'/(tile+'.jpg')) as image:
    first, overview, _ = eye.observe(image)
    close, detail, _ = eye.observe(image, 'left')
    eye.reset()
    repeat, reset, _ = eye.observe(image)
assert np.array_equal(first, repeat) and overview['spike_sha256'] == reset['spike_sha256']
assert not np.array_equal(first, close)
eye.verify_fixed_graph()
print(json.dumps({'cpu_simulation': True, 'reset_reproducible': True,
                  'different_views': True, 'graph_fixed': True,
                  'overview_spikes': overview['spikes'], 'detail_spikes': detail['spikes'],
                  'graph_weight_sha256': eye.graph_sha256}))
