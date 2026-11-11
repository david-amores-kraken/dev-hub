"""Review commands: python -m dev_hub.review <prepare|post|todo|address> ...

prepare <branch> [--final]     make a run folder for the personas; prints the personas and the folder
post <run-folder> <persona>    put a persona's findings into the dev hub
todo <branch>                  list the comments to act on
address <branch> <id> ...      answer a comment and mark it done
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev_hub.review.helpers import load_helpers
from dev_hub.review.post import post
from dev_hub.review.prepare import prepare
from dev_hub.review.todo import address, todo


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m dev_hub.review", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare_parser = commands.add_parser("prepare", help="make a run folder for the personas")
    prepare_parser.add_argument("branch")
    prepare_parser.add_argument("--final", action="store_true", help="also check commit messages")

    post_parser = commands.add_parser("post", help="put a persona's findings into the dev hub")
    post_parser.add_argument("run_folder", type=Path)
    post_parser.add_argument("persona")
    post_parser.add_argument("--dry-run", action="store_true", help="print what would be saved")

    todo_parser = commands.add_parser("todo", help="list the comments to act on, as JSON")
    todo_parser.add_argument("branch")

    address_parser = commands.add_parser("address", help="answer a comment and mark it resolved")
    address_parser.add_argument("branch")
    address_parser.add_argument("comment_id")
    address_parser.add_argument("--reply", required=True, help="what was done, or why not")
    address_parser.add_argument("--commit", help="the commit that deals with it")
    address_parser.add_argument("--as", dest="author", default="Agent", help="who is answering")

    args = parser.parse_args()
    if args.command == "prepare":
        personas, folder = prepare(args.branch, load_helpers(), final=args.final)
        print(f"personas: {', '.join(personas)}")
        print(folder)
    elif args.command == "post":
        print(post(args.run_folder, args.persona, dry_run=args.dry_run))
    elif args.command == "todo":
        print(json.dumps(todo(args.branch), indent=2, ensure_ascii=False))
    elif args.command == "address":
        print(address(args.branch, args.comment_id, args.reply, args.commit, args.author))


if __name__ == "__main__":
    main()
