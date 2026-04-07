# Retranslate Report to Hebrew

Re-translate an existing English Borkai report to Hebrew (full report, chunked).
Useful when a previous Hebrew translation was cut off or incomplete.

## Usage
`/retranslate <TICKER> [horizon]`

- `TICKER` — e.g. `AYAL`, `ESLT`
- `horizon` — `short` (default) | `medium` | `long`

## Instructions

Parse ticker and horizon from `$ARGUMENTS` (horizon defaults to `short`).

Run:

```
!cd "C:\Users\idohe\OneDrive\מסמכים\borkaiNewGen" && python -c "
import sys, io, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from borkai.config import load_config
import openai
from main import translate_to_hebrew

# Find the most recent English report for this ticker
pattern = f'reports/**/*<TICKER>*<horizon>*.md'
files = glob.glob(pattern, recursive=True)
files = [f for f in files if '_he' not in f]
if not files:
    print('No English report found. Run /analyze <TICKER> first.')
    sys.exit(1)
latest = max(files, key=os.path.getmtime)
print(f'Found: {latest}')
with open(latest, encoding='utf-8') as f:
    report_en = f.read()

config = load_config(market='il')
client = openai.OpenAI(api_key=config.openai_api_key)
report_he = translate_to_hebrew(report_en, client, config)

out = latest.replace('.md', '_he.md')
with open(out, 'w', encoding='utf-8') as f:
    f.write(report_he)
print(f'Saved: {out}')
print(f'Lines: {len(report_he.splitlines())}')
"
```

After completion, confirm the output file path and line count.
