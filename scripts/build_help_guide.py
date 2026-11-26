"""Write app/backend/resources/help_guide.py from the documentation of scipion-docs, for the help chat.

Each "## " section of a page of the parts in AREAS becomes one entry: its part, its page, its title, its text
(without images, HTML or markup) and its address in the published documentation. The parts for developers
(backend, frontend, development, release) are left out. Run it again when the documentation changes:

    python scripts/build_help_guide.py ../scipion-docs
"""
import argparse
import os
import pprint
import re
import sys

SITE = "https://fonsecareyna82.github.io/scipion-docs/"
OUT = os.path.join(os.path.dirname(__file__), "..", "app", "backend", "resources", "help_guide.py")
# Pages that are not for the users of the web
SKIP = {"index.md"}
# The parts of the documentation for the people who use or run ScipionWeb, in the order they are read
AREAS = ("user-guide", "getting-started", "installation", "configuration", "operations", "cli", "support")


def slug(title: str) -> str:
    """The anchor MkDocs gives a heading."""
    text = re.sub(r"[^\w\s-]", "", title.strip().lower())
    return re.sub(r"[\s]+", "-", text).strip("-")


def cleanText(markdown: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^!!!\s*\w+\s*\"([^\"]*)\"", r"\1:", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*(---|\*\*\*)\s*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`]{1,3}", "", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sections(path: str, page: str, area: str = "user-guide"):
    with open(path, encoding="utf-8") as handle:
        content = handle.read()
    pageTitle = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
    pageTitle = pageTitle.group(1).strip() if pageTitle else page
    parts = re.split(r"^##\s+(.+)$", content, flags=re.MULTILINE)
    for index in range(1, len(parts), 2):
        title = parts[index].strip()
        text = cleanText(parts[index + 1])
        if not text:
            continue
        yield {"area": area, "page": pageTitle, "title": title, "text": text,
               "url": "%s%s/%s/#%s" % (SITE, area, page[:-3], slug(title))}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("docs", help="the scipion-docs folder")
    args = parser.parse_args()
    if not os.path.isdir(os.path.join(args.docs, "docs", "user-guide")):
        sys.exit("No user guide in %s" % args.docs)
    entries = []
    for area in AREAS:
        folder = os.path.join(args.docs, "docs", area)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if name.endswith(".md") and name not in SKIP:
                entries.extend(sections(os.path.join(folder, name), name, area))
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write('"""The sections of the documentation (scipion-docs) for its users, for the help chat.\n\n'
                     'Written by scripts/build_help_guide.py: do not change it by hand."""\n\n')
        handle.write("GUIDE = ")
        handle.write(pprint.pformat(entries, width=118, sort_dicts=False))
        handle.write("\n")
    print("%d sections written to %s" % (len(entries), os.path.normpath(OUT)))


if __name__ == "__main__":
    main()
