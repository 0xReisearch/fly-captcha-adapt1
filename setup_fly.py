"""Download and verify upstream data; prepare the unchanged full-graph simulator."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / 'vendor' / 'doomfly'
REVISION = '71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33'


def main():
    UPSTREAM.parent.mkdir(parents=True, exist_ok=True)
    if not UPSTREAM.exists():
        subprocess.run(['git', 'clone', '--depth=1', '--filter=blob:none', '--sparse',
                        'https://github.com/nftechie/doomfly', str(UPSTREAM)], check=True)
        subprocess.run(['git', 'fetch', '--depth=1', 'origin', REVISION], cwd=UPSTREAM, check=True)
        subprocess.run(['git', 'checkout', '--detach', REVISION], cwd=UPSTREAM, check=True)
    subprocess.run(['git', 'sparse-checkout', 'set', 'doom', 'licenses',
                    'data-provenance'], cwd=UPSTREAM, check=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=UPSTREAM, text=True).strip()
    if commit != REVISION:
        raise RuntimeError(f'Unexpected upstream revision: {commit}')
    registry = json.loads((UPSTREAM / 'doom/datasets.json').read_text())['datasets']['malecns_v1']
    lock = json.loads((UPSTREAM / 'data-provenance/malecns_v1/source.lock.json').read_text())
    directory = UPSTREAM / 'connectome_data/malecns_v1'
    directory.mkdir(parents=True, exist_ok=True)
    for name, url in registry['files'].items():
        path = directory / name
        if not path.exists():
            print(f'Downloading {name}', flush=True)
            urllib.request.urlretrieve(url, path.with_suffix('.download'))
            path.with_suffix('.download').replace(path)
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        assert digest == lock[name]['sha256'], f'Data checksum mismatch: {name}'
        print(f'Verified {name}: {path.stat().st_size:,} bytes', flush=True)
    (directory / 'source.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    if not (directory / 'normalized/report.json').exists():
        subprocess.run([sys.executable, '-m', 'doom.connectome', 'malecns_v1'], cwd=UPSTREAM, check=True)
    if not (UPSTREAM / 'outputs/doom/malecns_v1/graph.npz').exists():
        subprocess.run([sys.executable, '-m', 'doom.prepare'], cwd=UPSTREAM, check=True)
    compiler = shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        raise RuntimeError('A C++17 compiler is required')
    source = UPSTREAM / 'doom/kernel.cpp'
    library = UPSTREAM / 'outputs/doom/libneural.so'
    command = [compiler, '-O3', '-std=c++17', '-shared', '-fPIC', str(source), '-o', str(library)]
    subprocess.run(command, check=True)
    library.with_suffix('.so.json').write_text(json.dumps({
        'kernel_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'binary_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
        'model_revision': 'lif-r2-refractory-write-protection', 'compile_flags': command[1:5],
        'compiler': compiler}, indent=2) + '\n')
    (ROOT / 'vendor/SOURCE.json').write_text(json.dumps({'repository': 'https://github.com/nftechie/doomfly',
        'revision': commit, 'data': lock}, indent=2) + '\n')
    print('Full fly graph ready.', flush=True)


if __name__ == '__main__':
    main()
