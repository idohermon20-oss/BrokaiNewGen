# portfolio/ — Israeli Market Portfolio Management

Planned module for Developer 2.

## Scope
- Portfolio positions, cost basis, P&L
- Signal-to-trade logic from israel_researcher outputs
- Sector-based rebalancing

## Integration
Load research data from `data/israel_researcher_state.json`.
Use the `shared/` package for common operations:

```python
import json
from pathlib import Path
from shared.stocks import find_top_stocks, filter_signals_by_score
from shared.analytics import calc_pnl, sector_weights, find_max_stock
from shared.reports import parse_financial_report, summarize_filing

state = json.loads(Path("data/israel_researcher_state.json").read_text(encoding="utf-8"))
top = find_top_stocks(state, n=10)
```

Do **not** import from `israel_researcher` directly.

## Run from project root
```bash
python portfolio/main.py
```
