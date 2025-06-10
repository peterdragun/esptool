#!/usr/bin/env python3
"""
Process include-data-dirs JSON and generate Nuitka arguments
"""

import sys
import json
import argparse


def process_include_dirs(include_dirs_json):
    """
    Process include directories JSON and return Nuitka arguments

    Args:
        include_dirs_json (str): JSON string containing include directories

    Returns:
        str: Space-separated Nuitka arguments
    """
    if not include_dirs_json or include_dirs_json.strip() == "[]":
        return ""

    try:
        data = json.loads(include_dirs_json)
        flags = []

        for item in data:
            if isinstance(item, dict) and "src" in item and "dest" in item:
                flags.append(f"--include-data-dir={item['src']}={item['dest']}")

        return " ".join(flags)

    except (json.JSONDecodeError, TypeError, KeyError) as e:
        print(f"Error processing include directories: {e}", file=sys.stderr)
        return ""


def main():
    parser = argparse.ArgumentParser(
        description="Process include directories for Nuitka"
    )
    parser.add_argument("include_dirs", help="JSON string of include directories")

    args = parser.parse_args()
    result = process_include_dirs(args.include_dirs)
    print(result)


if __name__ == "__main__":
    main()
