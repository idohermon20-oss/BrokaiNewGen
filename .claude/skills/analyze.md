# Borkai Stock Analyzer

Run a full Borkai analysis on a single stock.

## Usage
`/analyze <TICKER> [horizon] [market]`

- `TICKER` — stock symbol, e.g. `ESLT`, `TEVA`, `AAPL`
- `horizon` — `short` (default) | `medium` | `long`
- `market` — `il` (default for .TA stocks) | `us`

## Instructions

Parse the arguments from `$ARGUMENTS`. Apply these defaults if omitted:
- horizon → `short`
- market → `il` if ticker looks Israeli (no dot suffix, or ends in `.TA`), else `us`

Then run:

```
!cd "C:\Users\idohe\OneDrive\מסמכים\borkaiNewGen" && python -c "
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from main import analyze
_, report_he, result = analyze('<TICKER>', '<horizon>', market='<market>', save_report=True, output_dir='reports')
print(report_he)
"
```

After the analysis completes, tell the user:
- The verdict (invest / no / conditional)
- The direction and return score
- Where the report was saved
- A brief 2-3 sentence summary of the key finding
