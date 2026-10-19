# Contributing

Thanks for helping keep AWS's outage history from disappearing.

## Set up

You need Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m unittest discover -s tests   # run the tests
uv run python scripts/serve.py                # build the data and serve the site
```

The site is plain HTML, CSS and JavaScript in `site/` with no build step. Reload the page after editing; `serve.py` disables caching.

## Before you open a pull request

* Run the tests: `uv run python -m unittest discover -s tests`.
* If you touched the pipeline, also run `uv run python scripts/rebuild.py` and `uv run python scripts/check_integrity.py`.
* Keep `scripts/fetch_archive.py`, `scripts/merge_archive.py`, `scripts/check_feed_shape.py` and `scripts/diff_snapshots.py` standard-library only. The daily workflow runs them with plain `python`.
* Use conventional commit prefixes (`feat:`, `fix:`, `docs:`, `test:`).

## Rules the data depends on

* **Don't edit `data/` by hand.** `data/*.json` are AWS's own files, written by the daily workflow. `data/archive/` is the permanent merged archive and must only grow.
* **No report is not "healthy".** A day with no incident open or updated is *no data*, never *operational*. Keep this true in any metric, label or chart.
* **Severity follows AWS's numbers:** operational (0) < impacted (1) < degraded (2) < disrupted (3).

The [Data section of the README](README.md#data) defines every metric.

## Reporting a data problem

If the site shows something that doesn't match what AWS published, open an issue with the incident link (use the site's "Copy link" button) and what you expected to see.
