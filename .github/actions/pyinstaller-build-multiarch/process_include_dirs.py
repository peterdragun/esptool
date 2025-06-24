#!/usr/bin/env python3
"""
Process include-data-dirs JSON and generate Nuitka arguments
"""

import json
import argparse


def process_include_dirs(include_dirs_json, data_separator):
    """Convert include directories JSON to PyInstaller --add-data flags"""
    try:
        include_dirs = json.loads(include_dirs_json)
        if not include_dirs:
            return ""

        flags = []
        for item in include_dirs:
            src = item.get("src", "")
            dest = item.get("dest", "")
            if src and dest:
                # PyInstaller uses --add-data with format: source<separator>destination
                flags.append(f"--add-data='{src}{data_separator}{dest}'")

        return " ".join(flags)
    except (json.JSONDecodeError, KeyError, TypeError):
        return ""


def main():
    parser = argparse.ArgumentParser(
        description="Process include directories for Nuitka"
    )
    parser.add_argument("include_dirs", help="JSON string of include directories")
    parser.add_argument(
        "data_separator", help="Data separator for PyInstaller --add-data"
    )

    args = parser.parse_args()
    result = process_include_dirs(args.include_dirs, args.data_separator)
    print(result)


if __name__ == "__main__":
    main()
