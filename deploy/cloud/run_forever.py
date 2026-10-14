"""Run the news service continuously until Ctrl+C or SIGTERM.

Uses the existing collection, review, delivery and dashboard loops, including
their state checks, instance lock and graceful shutdown. Configure the restored
history and credentials, then set NEWS_SERVICE_ENABLED=true to start processing.
"""
from __future__ import annotations

import argparse

import worker


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    # No cycle deadline: the existing service owns all recurring work and stops
    # only when requested or when an error requires operator intervention.
    return worker.main(['run'])


if __name__ == '__main__':
    raise SystemExit(main())
