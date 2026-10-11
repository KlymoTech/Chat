"""Independent review evidence; never converts a failed check into a pass."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
AREA = sys.argv[1]
OUT = ROOT / 'review-results' / AREA
OUT.mkdir(parents=True, exist_ok=True)
COMMANDS = {
    'frontend': [
        ('lint', ['npm', 'run', 'lint']),
        ('typecheck', ['npm', 'run', 'typecheck']),
        ('tests', ['npm', 'run', 'test', '--workspace', '@northstar/web', '--', '--reporter=default', '--reporter=junit', '--outputFile.junit=test-results.xml']),
        ('build', ['npm', 'run', 'build']),
    ],
    'backend': [
        ('lint', ['uv', 'run', 'ruff', 'check', '.']),
        ('format', ['uv', 'run', 'ruff', 'format', '--check', '.']),
        ('typecheck', ['uv', 'run', 'mypy', 'src']),
        ('tests', ['uv', 'run', 'pytest', '--junitxml=test-results.xml']),
    ],
}
results = []
for name, command in COMMANDS[AREA]:
    with (OUT / f'{name}.log').open('w', encoding='utf-8') as log:
        try:
            run = subprocess.run(command, cwd=ROOT / 'backend' if AREA == 'backend' else ROOT,
                                 stdout=log, stderr=subprocess.STDOUT, check=False, timeout=1200)
            code = run.returncode
        except subprocess.TimeoutExpired:
            code = 124
    result = {'check': name, 'command': command, 'exitCode': code}
    results.append(result)
    print(json.dumps(result), flush=True)
summary = {'area': AREA, 'githubSha': os.getenv('GITHUB_SHA'), 'results': results}
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
raise SystemExit(1 if any(item['exitCode'] for item in results) else 0)
