import sys

import pandas as pd

from db import save_jobs

path = sys.argv[1] if len(sys.argv) > 1 else "output/all_jobs.csv"
df = pd.read_csv(path, encoding="utf-8-sig")
inserted = save_jobs(df)
print(f"Inserted {inserted} new jobs ({len(df) - inserted} already in the database or duplicates).")