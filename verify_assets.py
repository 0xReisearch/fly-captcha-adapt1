"""Verify the distributed static/sensory assets against the release manifest."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'ASSETS.json').read_text())
for name, expected in manifest['sha256'].items():
    path = (root / name).resolve()
    if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Asset check failed: ' + name)
print(f"Verified {len(manifest['sha256'])} files.")
