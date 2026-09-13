"""Live fixed-connectome perception. No targets, reward, or task classifier."""
import hashlib
import base64
import io
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image
import pyarrow.feather as feather


class LiveEye:
    def __init__(self, vendor, overview_size=100):
        if not 2 <= overview_size <= 100:
            raise ValueError('Overview size must be between 2 and 100 pixels')
        self.overview_size = overview_size
        vendor = Path(vendor).resolve()
        sys.path.insert(0, str(vendor))
        from doom.native import NativeBrain
        self.brain = NativeBrain(vendor / 'outputs/doom/malecns_v1/graph.npz')
        nodes = feather.read_table(vendor / 'connectome_data/malecns_v1/normalized/neurons.feather').to_pandas()
        ann = feather.read_table(vendor / 'connectome_data/malecns_v1/annotations.feather').to_pandas()
        ann = ann.set_index('bodyId').loc[nodes.source_id]
        x = ann.assignedOlHex1.to_numpy(dtype=float)
        y = ann.assignedOlHex2.to_numpy(dtype=float)
        valid = ann.type.isin(['L1', 'L2', 'L3', 'L5']).to_numpy() & np.isfinite(x)
        self.pools = []
        for side in ('L', 'R'):
            mask = valid & (ann.somaSide.to_numpy() == side)
            xx = np.nan_to_num((x - np.nanmin(x[mask])) / max(np.nanmax(x[mask]) - np.nanmin(x[mask]), 1))
            yy = np.nan_to_num((y - np.nanmin(y[mask])) / max(np.nanmax(y[mask]) - np.nanmin(y[mask]), 1))
            for row in range(4):
                for col in range(8):
                    self.pools.append(np.flatnonzero(mask & (np.clip((xx*8).astype(int), 0, 7) == col)
                                                    & (np.clip((yy*4).astype(int), 0, 3) == row)))
        keys = ('v', 'g', 'drive', 'refractory', 'queue', 'queue_count', 'counts', 'luminance',
                'active', 'active_flag', 'nactive', 'previous_drive', 'last')
        self.initial = {k: getattr(self.brain, k).copy() for k in keys}
        self.calls = 0
        self.seconds = 0.0
        self.graph_sha256 = hashlib.sha256(self.brain.weight.tobytes()).hexdigest()

    def reset(self):
        for key, value in self.initial.items():
            getattr(self.brain, key)[:] = value
        self.brain.cursor = self.brain.total_spikes = 0
        self.brain.sim_ms = 0

    def observe(self, image, view='wide'):
        start = time.perf_counter()
        image = image.convert('RGB')
        # The same image-independent viewing actions exist for every photograph.
        boxes = {'left': (0, .15, .65, .85), 'center': (.175, .175, .825, .825),
                 'right': (.35, .15, 1, .85)}
        if view != 'wide':
            box = boxes[view]
            image = image.crop(tuple(int(v * (image.width if i % 2 == 0 else image.height))
                                    for i, v in enumerate(box))).resize((100, 100))
        elif self.overview_size < 100:
            image = image.resize((self.overview_size, self.overview_size), Image.Resampling.BOX).resize(
                (100, 100), Image.Resampling.NEAREST)
        rgb = np.asarray(image, dtype=np.float32) / 255
        linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055)**2.4)
        contrast = 1 - linear @ np.array([.2126, .7152, .0722])
        preview = io.BytesIO()
        Image.fromarray(np.rint(np.clip(contrast, 0, 1)*255).astype(np.uint8)).save(preview, format='PNG')
        uv = self.brain.uv
        samples = contrast[np.minimum((uv[:, 1]*image.height).astype(int), image.height-1),
                           np.minimum((uv[:, 0]*image.width).astype(int), image.width-1)]
        counts, kernel_seconds = self.brain.step(samples, 60)
        features = np.array([counts[p].mean()/30 if len(p) else 0 for p in self.pools])
        active = np.flatnonzero(counts)
        self.calls += 1
        self.seconds += time.perf_counter() - start
        return features, {'spikes': int(counts.sum()), 'active_neurons': len(active), 'view': view,
                          'retinal_contrast_png': base64.b64encode(preview.getvalue()).decode('ascii'),
                          'simulated_ms': 60, 'kernel_seconds': kernel_seconds,
                          'spike_sha256': hashlib.sha256(counts.tobytes()).hexdigest()}, counts

    def verify_fixed_graph(self):
        assert hashlib.sha256(self.brain.weight.tobytes()).hexdigest() == self.graph_sha256
