import argparse
import os
from importlib import import_module

from jinja2 import Environment, FileSystemLoader

from extension import SqlvmExtension


def evaluate_template(loader, filename, functions):
    environment = Environment(loader=loader, extensions=[SqlvmExtension])
    environment.globals.update(**functions)
    return environment.get_template(filename).render()


def main(args):
    try:
        language = import_module(
            "languages.{language_name}".format(language_name=args.language)
        )
    except ModuleNotFoundError:
        raise ModuleNotFoundError(
            "could not find {language_name}".format(language_name=args.language)
        )

    language_functions = {
        name: fn for name, fn in language.__dict__.items() if callable(fn)
    }
    loader = FileSystemLoader(".")
    print(evaluate_template(loader, args.filename, language_functions).strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="convert SQL-like language to a SQL statement"
    )
    parser.add_argument(
        "--language",
        "-l",
        nargs="?",
        default="mysql",
        help="specify SQL language (default: mysql)",
    )
    parser.add_argument("filename", help="the file to translate")
    args = parser.parse_args()
    main(args)
