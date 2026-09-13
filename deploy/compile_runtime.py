"""Compile the pinned, unchanged upstream native source on the deployment CPU."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('vendor', type=Path)
args = parser.parse_args()
compiler = shutil.which('clang++') or shutil.which('g++')
if not compiler:
    raise SystemExit('Install a C++17 compiler first.')
source = args.vendor/'doom/kernel.cpp'
library = args.vendor/'outputs/doom/libneural.so'
library.parent.mkdir(parents=True, exist_ok=True)
command = [compiler, '-O3', '-std=c++17', '-shared', '-fPIC', str(source), '-o', str(library)]
subprocess.run(command, check=True)
record = {'kernel_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'binary_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
          'model_revision': 'lif-r2-refractory-write-protection', 'compile_flags': command[1:5]}
library.with_suffix('.so.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record))
