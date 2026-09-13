"""Regenerate measurements with the fixed full graph; never update the cache."""
import json
from fly_vision import FlyVision, ROOT

vision = FlyVision()
for i, tile in enumerate(json.loads((ROOT / 'data/tiles.json').read_text())['tiles']):
    saved = json.loads((ROOT / 'data/vision' / (tile['id'] + '.json')).read_text())
    actual = vision.encode(ROOT / 'data/tiles' / (tile['id'] + '.jpg'))
    if actual['features'] != saved['features'] or actual['spike_sha256'] != saved['spike_sha256']:
        raise RuntimeError('Sensory response differs for ' + tile['id'])
    if (i+1) % 60 == 0:
        print(f'{i+1}/540 exact feature and spike-hash matches', flush=True)
