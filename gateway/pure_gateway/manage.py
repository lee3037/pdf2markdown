"""Local operator inspection; no remote submissions or automatic retries."""
import argparse
import json

from filelock import FileLock

from .config import load_settings
from .store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "resolve-uncertain"])
    parser.add_argument("task_id", nargs="?")
    parser.add_argument("--confirmed-upstream-idle", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    # The service must be stopped before inspecting/changing recovery state.
    with FileLock(str(settings.data_dir / "gateway.lock"), timeout=0):
        store = Store(settings.data_dir)
        if args.command == "list":
            print(json.dumps([{k: t.get(k) for k in ["task_id", "status", "phase", "uncertain", "error", "last_error"]}
                              for t in store.all()], ensure_ascii=False, indent=2))
        else:
            task = store.get(args.task_id) if args.task_id else None
            if not task or not task.get("uncertain") or not args.confirmed_upstream_idle:
                parser.error("Supply an uncertain task ID and --confirmed-upstream-idle only after checking the upstream.")
            store.update(args.task_id, uncertain=False, status="failed", phase="failed", error="operator_reviewed_no_resubmit")
            print("Uncertainty gate cleared; no file was resubmitted and no artifact was deleted.")


if __name__ == "__main__":
    main()
