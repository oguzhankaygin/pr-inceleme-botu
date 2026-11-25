"""python -m pr_inceleme giriş noktası."""

import argparse
import sys
from pathlib import Path

from .diff import DEFAULT_BUDGET, parse_diff, select_files
from .github import GitHub, GitHubError
from .llm import LLMError, review_diff
from .review import ReviewError, render, validate


def main(argv=None):
    parser = argparse.ArgumentParser(description="Türkçe pull request inceleme raporu üret.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--diff", type=Path, metavar="DOSYA")
    source.add_argument("--stdin", action="store_true")
    source.add_argument("--repo", metavar="OWNER/NAME")
    parser.add_argument("--pr", type=int, metavar="N")
    parser.add_argument("--post", action="store_true", help="GitHub'a COMMENT incelemesi gönder.")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, metavar="KARAKTER")
    args = parser.parse_args(argv)
    if args.repo and (args.pr is None or args.pr <= 0):
        parser.error("--repo ile pozitif bir --pr numarası gerekir.")
    if not args.repo and (args.pr is not None or args.post):
        parser.error("--pr ve --post yalnızca --repo ile kullanılabilir.")
    if args.budget <= 0:
        parser.error("--budget pozitif olmalı.")

    try:
        client = None
        title = description = ""
        if args.repo:
            client = GitHub(args.repo, args.pr)
            info = client.info()
            sha = info["head"]["sha"]
            if args.post and client.already_reviewed(sha):
                print("Bu commit için bot incelemesi zaten var.", file=sys.stderr)
                return 0
            title, description = info.get("title") or "", info.get("body") or ""
            source_text = client.diff()
            if client.info()["head"]["sha"] != sha:
                raise GitHubError("Diff alınırken PR commit'i değişti. Tekrar deneyin.")
        elif args.stdin:
            source_text = sys.stdin.read()
        else:
            source_text = args.diff.read_text(encoding="utf-8", errors="replace")

        files, skipped = select_files(parse_diff(source_text), args.budget)
        if files:
            output = review_diff("".join(file.patch for file in files), title, description)
            report = validate(output, files)
        else:
            report = validate('{"ozet":"İncelenebilir diff dosyası bulunamadı."}', files)
        print(render(report, skipped), end="")
        if args.post:
            if client.post_review(sha, report, skipped):
                print("GitHub incelemesi gönderildi.", file=sys.stderr)
            else:
                print("Bu commit için bot incelemesi zaten var.", file=sys.stderr)
        return 0
    except (GitHubError, LLMError, ReviewError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
    except OSError:
        print("Hata: Diff girdisi okunamadı.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
