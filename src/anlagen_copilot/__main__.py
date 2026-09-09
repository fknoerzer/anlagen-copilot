"""Entry point for `python -m anlagen_copilot`.

The same ingestion the `anlagen-copilot` console script runs; both go through
`cli.main()`, so there is one code path and two ways to reach it.
"""

from anlagen_copilot.cli import main

main()
