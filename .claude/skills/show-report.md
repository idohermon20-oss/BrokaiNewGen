# Show Latest Report

Display the most recent saved Hebrew report for a ticker.

## Usage
`/show-report <TICKER>`

## Instructions

Parse the ticker from `$ARGUMENTS`.

1. Search for the latest report file matching the pattern:
   `reports/**/*<TICKER>*_he.md` or `report_<TICKER>*_he.md` in the project root.
   Also check the project root directly.

2. Read and display the full contents of the most recently modified matching file.

3. If no report is found, tell the user to run `/analyze <TICKER>` first.
