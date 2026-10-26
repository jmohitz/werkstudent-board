# Scraper

The daily pipeline: scrape -> classify -> save to Postgres.

```bash
.venv/bin/python main.py                 # full run
.venv/bin/python main.py --only thesis   # subset of searches
```

See the repo docs:

- [Architecture](../docs/architecture.md): sources, classification, filtering
- [Configuration](../docs/configuration.md): everything in `config.yaml`
- [Operations](../docs/operations.md): running daily, quotas, troubleshooting

`app.py` (Streamlit) and `import_csv.py` are from the first CSV-based version; the board in
`../frontend` replaces the Streamlit app.
