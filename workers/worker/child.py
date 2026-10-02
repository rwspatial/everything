"""Runs one Python process in its own OS process (so the worker can time it out or cancel it).
Usage: python -m worker.child <module>   with JOB_ID, JOB_INPUTS, WORKER_DATABASE_URL in the environment."""
import importlib
import sys

from .ctx import Ctx, emit

if __name__ == "__main__":
    mod = importlib.import_module(sys.argv[1])
    ctx = Ctx()
    emit(mod.run(ctx, ctx.inputs))
