"""python -m pr_inceleme giriş noktası."""

import argparse
import sys
from pathlib import Path

from .diff import DEFAULT_BUDGET, is_test_doc_or_lock, parse_diff, select_files
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
    parser.add_argument("--tetikleme", choices=("otomatik", "etiket"), default="otomatik")
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
            if info.get("draft"):
                print("Taslak PR, inceleme atlandı.", file=sys.stderr)
                return 0
            if args.tetikleme == "etiket" and not any(
                label.get("name") == "claude-inceleme" for label in info.get("labels", [])
            ):
                print("claude-inceleme etiketi yok, inceleme atlandı.", file=sys.stderr)
                return 0
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

        changes = parse_diff(source_text)
        paths = {path for file in changes for path in (file.old_path, file.new_path) if path}
        if paths and all(is_test_doc_or_lock(path) for path in paths):
            print("Yalnızca test, doküman veya kilit dosyası değişmiş, inceleme atlandı.",
                  file=sys.stderr)
            return 0
        if sum(len(file.added) + len(file.removed) for file in changes) < 3:
            print("Diff 3 satırdan küçük, inceleme atlandı.", file=sys.stderr)
            return 0
        files, skipped = select_files(changes, args.budget)
        if files:
            output, cost = review_diff("".join(file.patch for file in files), title, description)
            report = validate(output, files)
            report["cost_usd"] = cost
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
