"""Task-blind visual features from the unchanged full-connectome LIF kernel."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.deps'))
sys.path.insert(0, str(ROOT / 'vendor/doomfly'))
from doom.native import NativeBrain
import pyarrow.feather as feather


class FlyVision:
    def __init__(self):
        base = ROOT / 'vendor/doomfly'
        self.brain = NativeBrain(base / 'outputs/doom/malecns_v1/graph.npz')
        self.manifest = json.loads((base / 'outputs/doom/malecns_v1/manifest.json').read_text())
        nodes = feather.read_table(base / 'connectome_data/malecns_v1/normalized/neurons.feather').to_pandas()
        annotation = feather.read_table(base / 'connectome_data/malecns_v1/annotations.feather').to_pandas()
        annotation = annotation.set_index('bodyId').loc[nodes.source_id]
        # Label-independent electrode bins in the annotated optic-lobe grid.
        # These pool postsynaptic visual cells, not the externally driven retina.
        valid = annotation.type.isin(['L1', 'L2', 'L3', 'L5']) & annotation.assignedOlHex1.notna()
        x = annotation.assignedOlHex1.to_numpy(dtype=float)
        y = annotation.assignedOlHex2.to_numpy(dtype=float)
        self.pools = []
        for side in ('L', 'R'):
            mask = valid.to_numpy() & (annotation.somaSide.to_numpy() == side)
            xx = np.nan_to_num((x - np.nanmin(x[mask])) / max(np.nanmax(x[mask]) - np.nanmin(x[mask]), 1))
            yy = np.nan_to_num((y - np.nanmin(y[mask])) / max(np.nanmax(y[mask]) - np.nanmin(y[mask]), 1))
            for row in range(4):
                for col in range(8):
                    self.pools.append(np.flatnonzero(mask & (np.clip((xx * 8).astype(int), 0, 7) == col)
                                                     & (np.clip((yy * 4).astype(int), 0, 3) == row)))
        self.names = [f'neural_{i:02d}' for i in range(len(self.pools))]
        self.snapshot = {key: value.copy() for key, value in vars(self.brain).items()
                         if isinstance(value, np.ndarray) and key in (
                             'v', 'g', 'drive', 'refractory', 'queue', 'queue_count', 'counts',
                             'luminance', 'active', 'active_flag', 'nactive', 'previous_drive', 'last')}

    def encode(self, path):
        brain = self.brain
        for key, value in self.snapshot.items():
            getattr(brain, key)[:] = value
        brain.cursor = 0
        brain.total_spikes = 0
        brain.sim_ms = 0
        rgb = np.asarray(Image.open(path).convert('RGB'), dtype=np.float32) / 255
        linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
        luminance = linear @ np.array([.2126, .7152, .0722])
        # Contrast on the white photo background; same fixed transform for every image.
        contrast = 1 - luminance
        uv = brain.uv
        samples = contrast[np.minimum((uv[:, 1] * contrast.shape[0]).astype(int), contrast.shape[0] - 1),
                           np.minimum((uv[:, 0] * contrast.shape[1]).astype(int), contrast.shape[1] - 1)]
        counts, wall = brain.step(samples, 60)
        features = {name: float(counts[pool].mean() / 30) if len(pool) else 0.0
                    for name, pool in zip(self.names, self.pools)}
        return {'features': features, 'spikes': int(counts.sum()),
                'active_neurons': int(np.count_nonzero(counts)), 'simulated_ms': 60,
                'wall_seconds': wall, 'spike_sha256': hashlib.sha256(counts.tobytes()).hexdigest()}


def main():
    vision = FlyVision()
    data = json.loads((ROOT / 'data/tiles.json').read_text())
    directory = ROOT / 'data/vision'
    directory.mkdir(exist_ok=True)
    for i, tile in enumerate(data['tiles']):
        out = directory / f"{tile['id']}.json"
        if out.exists():
            continue
        response = vision.encode(ROOT / 'data/tiles' / f"{tile['id']}.jpg")
        response['image_sha256'] = tile['sha256']
        out.write_text(json.dumps(response) + '\n')
        if i % 20 == 0:
            print(f"{i+1}/{len(data['tiles'])}: {response['spikes']:,} spikes, {response['wall_seconds']:.3f}s", flush=True)
    (directory / 'manifest.json').write_text(json.dumps({'connectome': vision.manifest,
        'feature_names': vision.names, 'simulated_ms_per_image': 60,
        'protocol': 'Reset neural voltage state for each flashed tile; no image labels in encoder; graph weights fixed.'}, indent=2) + '\n')


if __name__ == '__main__':
    main()
