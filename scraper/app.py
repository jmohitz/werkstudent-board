"""Tiny frontend: `streamlit run app.py`"""
from pathlib import Path

import pandas as pd
import streamlit as st

OUT = Path(__file__).parent / "output"
st.set_page_config(page_title="Job Radar", layout="wide")
st.title("Job Radar")

all_path = OUT / "all_jobs.csv"
if not all_path.exists():
    st.info("No data yet. Run `python main.py` first.")
    st.stop()

df = pd.read_csv(all_path)
df = df.drop_duplicates(subset=["job_url"], keep="last")

with st.sidebar:
    st.header("Filters")
    dates = sorted(df["date_found"].unique(), reverse=True)
    day = st.selectbox("Found on", ["All"] + dates)
    cats = st.multiselect("Category", sorted(df["category"].unique()), default=sorted(df["category"].unique()))
    fields = st.multiselect("Field", sorted(df["field"].dropna().unique()))
    min_rel = st.slider("Min relevance", 0, 5, 3)
    english_only = st.checkbox("Hide 'German required'", value=False)
    q = st.text_input("Search title/company")

f = df[df["category"].isin(cats) & (df["relevance"] >= min_rel)]
if day != "All":
    f = f[f["date_found"] == day]
if fields:
    f = f[f["field"].isin(fields)]
if english_only:
    f = f[f["german_required"] != "yes"]
if q:
    m = f["title"].str.contains(q, case=False, na=False) | f["company"].str.contains(q, case=False, na=False)
    f = f[m]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Shown", len(f))
for col, cat in zip((c2, c3, c4), ("working_student", "internship", "thesis")):
    col.metric(cat.replace("_", " ").title(), int((f["category"] == cat).sum()))

st.dataframe(
    f[["date_found", "category", "relevance", "title", "company", "location", "field",
       "german_required", "site", "job_url", "reason"]].sort_values(
        ["date_found", "relevance"], ascending=[False, False]),
    column_config={
        "job_url": st.column_config.LinkColumn("Link", display_text="open"),
        "relevance": st.column_config.ProgressColumn("Relevance", min_value=0, max_value=5, format="%d"),
    },
    hide_index=True,
    use_container_width=True,
)
st.download_button("Download filtered CSV", f.to_csv(index=False).encode("utf-8-sig"), "jobs_filtered.csv")
