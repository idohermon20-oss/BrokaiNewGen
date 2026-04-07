# Borkai TASE Scanner

Scan the Tel Aviv Stock Exchange for the best short-term opportunities.

## Usage
`/scan-tase [horizon]`

- `horizon` — `short` (default) | `medium` | `long`

## Instructions

Parse the horizon from `$ARGUMENTS` (default: `short`).

Run the scan:

```
!cd "C:\Users\idohe\OneDrive\מסמכים\borkaiNewGen" && python scan_tase.py
```

After it completes, read the ranking summary from `reports/<today>/short/ranking_summary.md` (or the relevant horizon folder) and present the top 10 stocks with their scores and a one-line rationale for each.
