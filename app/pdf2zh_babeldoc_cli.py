from __future__ import annotations

import argparse
import sys

from pdf2zh.pdf2zh import yadt_main


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pdf2zh BabelDOC without double-reading prompt files.")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--service", required=True)
    parser.add_argument("--lang-in", dest="lang_in", default="en")
    parser.add_argument("--lang-out", dest="lang_out", default="zh")
    parser.add_argument("--output")
    parser.add_argument("--thread", type=int, default=4)
    parser.add_argument("--pages")
    parser.add_argument("--prompt")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--ignore-cache", action="store_true")
    args = parser.parse_args()

    args.dir = False
    args.raw_pages = [args.pages] if args.pages else []
    return yadt_main(args)


if __name__ == "__main__":
    sys.exit(main())
