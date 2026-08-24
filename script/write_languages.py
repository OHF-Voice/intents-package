"""
Generates a Python file with available domains/languages.

This is automatically run by script/package after the data files are generated.
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", help="Path to directory with <language>.json files")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)

    # Every file in here is one language's sentences, and its own "language" key
    # says which. Checking that rather than trusting the file name is what keeps
    # a stray JSON dropped into this directory from becoming a language: nothing
    # downstream would notice, since get_intents() would happily return it.
    languages = []
    for language_file in sorted(data_dir.glob("*.json")):
        with language_file.open(encoding="utf-8") as data_file:
            language = json.load(data_file).get("language")

        if language != language_file.stem:
            sys.exit(
                f"{language_file} is not a language file: expected a 'language' key "
                f"of {language_file.stem!r}, got {language!r}. Data that is not one "
                f"language's sentences belongs outside {data_dir}."
            )

        languages.append(language)

    print("LANGUAGES =", json.dumps(sorted(languages)))


if __name__ == "__main__":
    main()
