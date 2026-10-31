import argparse
import json
from pathlib import Path

from .contract import Contract, plan, invalidated


def main():
    parser = argparse.ArgumentParser(description="Audit compatibility before reusing recorded experience.")
    commands = parser.add_subparsers(dest="command", required=True)
    compare = commands.add_parser("plan", help="Compare two complete environment contracts")
    compare.add_argument("old", type=Path)
    compare.add_argument("new", type=Path)
    deps = commands.add_parser("invalidate", help="Find derived artifacts invalidated by a change")
    deps.add_argument("graph", type=Path)
    deps.add_argument("changed", nargs="+")
    args = parser.parse_args()
    if args.command == "plan":
        result = plan(Contract.from_dict(json.loads(args.old.read_text())),
                      Contract.from_dict(json.loads(args.new.read_text())))
    else:
        result = invalidated(json.loads(args.graph.read_text()), args.changed)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
