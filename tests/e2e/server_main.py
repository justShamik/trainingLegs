"""Run the Flask app against a given DB with COROS/Gemini stubbed (test-only entry point).

    python -m tests.e2e.server_main --db path/to/temp.db --port 5051 [--seed] [--real-coros]
"""
import argparse
import os
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--seed", action="store_true", help="wipe and seed the DB with e2e fixtures first")
    ap.add_argument("--real-coros", action="store_true", help="do NOT stub COROS/Gemini")
    args = ap.parse_args()

    if args.seed:
        from tests.e2e.seed import seed
        seed(args.db)
    if not args.real_coros:
        from tests.e2e import fake_coros
        fake_coros.install()

    from app.web.routes import create_app
    app = create_app(db_path=args.db)
    app.run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False, debug=False)


if __name__ == "__main__":
    sys.path.insert(0, os.getcwd())
    main()
