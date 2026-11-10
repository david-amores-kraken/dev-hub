"""Run the hub: python -m dev_hub"""

import sys

from dev_hub.app import create_app
from dev_hub.config import HOST, PORT


def main() -> None:
    print(f"dev-hub on http://{HOST}:{PORT}", file=sys.stderr, flush=True)
    create_app().run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
