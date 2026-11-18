"""Entry point for one pipeline run, executed as a subprocess so the portal can kill it.
Usage: python -m app.run_job --run-id N"""
import argparse
import logging

from .runner import execute_run

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, required=True)
    execute_run(ap.parse_args().run_id)
