# status-archive

AWS doesn't keep old status updates around. Their status feed
([status.aws.amazon.com](https://status.aws.amazon.com)) only shows what's
happening right now, and once an incident is resolved it quietly drops off.
So if you wanted to know "was there a problem last month?" the answer was
basically no.

This project fixes that.

The idea is simple: I grab a copy of the feed every day and commit it to git.
Git keeps every version, so over time I end up with a full history even
though AWS never stored one. Then a script replays that history, stitches
the snapshots together, and turns them into something you can actually
query.

Right now it's early days. The plan is:

1. Archive the feed daily
2. Rebuild incident timelines from the snapshots
3. Serve the result through a small API

Built with Python, FastAPI, and SQLite. Python because it's nice for this
kind of messy text scraping, SQLite because the data fits in a file, and
FastAPI because it gives you a usable API for almost free.

This is mostly a learning project, but if AWS ever breaks hard, it might
come in handy too.
