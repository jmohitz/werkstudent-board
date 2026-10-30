# Scraper

The daily pipeline: scrape -> classify -> save to Postgres.

```bash
.venv/bin/python main.py                 # full run
.venv/bin/python main.py --only thesis   # subset of searches
.venv/bin/python main.py --sources xing  # all terms, selected sources only
```

See the repo docs:

- [Architecture](../docs/architecture.md): sources, classification, filtering
- [Configuration](../docs/configuration.md): everything in `config.yaml`
- [Operations](../docs/operations.md): running daily, quotas, troubleshooting
