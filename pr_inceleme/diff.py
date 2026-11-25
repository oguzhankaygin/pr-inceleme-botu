"""Unified diff ayrıştırma ve dosya bazında bütçeleme."""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

DEFAULT_BUDGET = 60_000
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
QUOTED = re.compile(r'^"(?:[^"\\]|\\.)*"')
ESCAPE = re.compile(rb"\\([0-7]{3}|.)")


def _path(value, prefix=""):
    quoted = QUOTED.match(value)
    if quoted:
        raw = quoted[0][1:-1].encode()
        escapes = {b"t": b"\t", b"n": b"\n", b"r": b"\r",
                   b"a": b"\a", b"b": b"\b", b"f": b"\f", b"v": b"\v"}

        def decode(match):
            key = match[1]
            if len(key) == 3 and int(key, 8) <= 255:
                return bytes([int(key, 8)])
            return escapes.get(key, key)

        value = ESCAPE.sub(decode, raw).decode("utf-8", "replace")
    else:
        value = value.split("\t", 1)[0]
    if value == "/dev/null":
        return None
    return value.removeprefix(prefix)


@dataclass
class FileDiff:
    old_path: str | None = None
    new_path: str | None = None
    lines: list[str] = field(default_factory=list)
    added: set[int] = field(default_factory=set)
    removed: set[int] = field(default_factory=set)
    binary: bool = False

    @property
    def path(self):
        return self.new_path or self.old_path or "(bilinmeyen dosya)"

    @property
    def patch(self):
        return "\n".join(self.lines) + "\n"


def parse_diff(source):
    files = []
    current = None
    git_header = False
    old_left = new_left = 0
    old_line = new_line = 0
    for line in source.split("\n"):
        line = line.removesuffix("\r")
        if line.startswith("diff --git "):
            header = line[11:]
            quoted = QUOTED.match(header)
            if quoted:
                old, new = quoted[0], header[quoted.end():].lstrip()
            else:
                old, sep, new = header.rpartition(" b/")
                if not sep:
                    old, _, new = header.partition(" ")
                else:
                    new = "b/" + new
            current = FileDiff(_path(old, "a/"), _path(new, "b/"), [line])
            files.append(current)
            git_header = True
            old_left = new_left = 0
            continue
        if current is not None and (old_left or new_left) and line[:1] in ("+", "-", " "):
            current.lines.append(line)
            if line[0] != "+":
                if line[0] == "-":
                    current.removed.add(old_line)
                old_line += 1
                old_left -= 1
            if line[0] != "-":
                if line[0] == "+":
                    current.added.add(new_line)
                new_line += 1
                new_left -= 1
            continue
        if line.startswith("--- ") and (current is None or current.added or current.removed):
            current = FileDiff()
            files.append(current)
            git_header = False
        if current is None or not line:
            continue
        current.lines.append(line)
        if line.startswith("--- "):
            current.old_path = _path(line[4:], "a/" if git_header else "")
        elif line.startswith("+++ "):
            current.new_path = _path(line[4:], "b/" if git_header else "")
        elif git_header and line.startswith(("rename from ", "copy from ")):
            current.old_path = _path(line.split(" ", 2)[2])
        elif git_header and line.startswith(("rename to ", "copy to ")):
            current.new_path = _path(line.split(" ", 2)[2])
        elif line.startswith(("Binary files ", "GIT binary patch")):
            current.binary = True
        elif match := HUNK.match(line):
            old_line, old_count, new_line, new_count = match.groups()
            old_line, new_line = int(old_line), int(new_line)
            old_left = int(old_count) if old_count is not None else 1
            new_left = int(new_count) if new_count is not None else 1
    return files


def skip_reason(file):
    path = PurePosixPath(file.path.lower())
    if file.binary or path.suffix in {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif",
        ".bmp", ".tiff", ".tif", ".pdf", ".zip", ".woff", ".woff2",
    }:
        return "ikili dosya veya görsel"
    if path.name in {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
                     "go.sum", "composer.lock", "bun.lockb"} or path.suffix == ".lock":
        return "kilit dosyası"
    if {"dist", "build", "generated", "node_modules"} & set(path.parts[:-1]) or path.name.endswith(
        (".min.js", ".min.css", ".js.map", ".css.map", ".generated.py")
    ):
        return "üretilmiş dosya"
    return None


def select_files(files, budget=DEFAULT_BUDGET):
    selected, skipped, candidates = [], [], []
    for file in files:
        reason = skip_reason(file)
        if reason:
            skipped.append((file.path, reason))
        else:
            candidates.append(file)
    candidates.sort(key=lambda file: (
        PurePosixPath(file.path.lower()).suffix in {".md", ".rst", ".txt"},
        -(len(file.added) + len(file.removed)),
    ))
    for file in candidates:
        size = len(file.patch)
        if size > budget:
            skipped.append((file.path, "diff bütçesini aşıyor"))
        else:
            selected.append(file)
            budget -= size
    return selected, skipped
