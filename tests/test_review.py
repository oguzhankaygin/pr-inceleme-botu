import json
import unittest

from pr_inceleme.diff import parse_diff, select_files
from pr_inceleme.review import NOTE, ReviewError, inline_comments, render, validate

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -4,3 +4,4 @@
 context
-old
+new
+++ first
 context
@@ -20 +21 @@
-old again
+new again
"""


class DiffTests(unittest.TestCase):
    def test_hunks_and_header_like_addition(self):
        file, = parse_diff(PATCH)
        self.assertEqual(file.path, "app.py")
        self.assertEqual(file.added, {5, 6, 21})
        self.assertEqual(file.removed, {5, 20})

    def test_plain_unified_multiple_files_and_deleted_file(self):
        deleted, added = parse_diff(
            "--- gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n"
            "--- /dev/null\n+++ new.py\n@@ -0,0 +1 @@\n+new\n"
        )
        self.assertEqual(deleted.path, "gone.py")
        self.assertEqual(deleted.added, set())
        self.assertEqual(added.path, "new.py")
        self.assertEqual(added.added, {1})

    def test_quoted_git_path(self):
        file, = parse_diff(PATCH.replace("a/app.py", r'"a/\303\247.py"')
                                .replace("b/app.py", r'"b/\303\247.py"'))
        self.assertEqual(file.path, "ç.py")
        self.assertEqual(file.added, {5, 6, 21})

    def test_skipped_files(self):
        names = ["package-lock.json", "dist/app.py", "demo.min.js", "deps.lock", "icon.svg"]
        source = "".join(PATCH.replace("app.py", path) for path in names)
        source += "diff --git a/data.bin b/data.bin\nBinary files a/data.bin and b/data.bin differ\n"
        selected, skipped = select_files(parse_diff(source + PATCH))
        self.assertEqual([file.path for file in selected], ["app.py"])
        self.assertEqual({path for path, _ in skipped}, {*names, "data.bin"})

    def test_budget_prefers_code_and_lists_omitted_files(self):
        files = parse_diff(PATCH.replace("app.py", "notes.md") + PATCH)
        selected, skipped = select_files(files, len(files[1].patch))
        self.assertEqual([file.path for file in selected], ["app.py"])
        self.assertEqual(skipped, [("notes.md", "diff bütçesini aşıyor")])
        self.assertEqual(select_files(files, 1)[0], [])


class ReviewTests(unittest.TestCase):
    def test_validation_and_rendering(self):
        files = parse_diff(PATCH + PATCH.replace("app.py", "service.py"))
        finding = {"dosya": "app.py", "satir": 5, "onem": "onemli",
                   "baslik": "Boş girdi", "aciklama": "Ö" * 1600, "oneri": "Kontrol ekle"}
        model = {
            "ozet": "@takim <img>", "akis": "1. Veri gelir\n2. Veri işlenir\n3. Sonuç döner",
            "bulgular": [finding, {**finding, "satir": 999}, {**finding, "dosya": "uydurma.py"},
                         {**finding, "satir": True}, {**finding, "onem": []}],
            "sorular": ["Boş girdi mümkün mü?"],
            "test_onerileri": ["Boş girdiyle dene"],
            "iliski": [{"kaynak": "app.py", "hedef": "service.py"}],
        }
        report = validate("giriş {}\n```json\n" + json.dumps(model) + "\n```\nson", files)
        self.assertEqual([item["satir"] for item in report["bulgular"]], [5, None, None, None])
        self.assertEqual(len(report["bulgular"][0]["aciklama"]), 1000)
        self.assertEqual(len(inline_comments(report)), 1)
        markdown = render(report, [("deps.lock", "kilit dosyası")])
        for fragment in ["## Özet", "- Veri gelir", "flowchart LR", "F1 --> F2",
                         "🟠 Önemli", "satır 5", "## Sorular", "## Test önerileri",
                         "## İncelenmeyen dosyalar", "&lt;img&gt;", "&#64;takim", NOTE]:
            self.assertIn(fragment, markdown)
        self.assertNotIn("uydurma", markdown)

    def test_limit_and_invalid_response(self):
        item = {"onem": "kritik", "baslik": "Başlık", "aciklama": "Gerekçe"}
        raw = json.dumps({"ozet": "Özet", "bulgular": [item] * 16})
        self.assertEqual(len(validate(raw, [])["bulgular"]), 15)
        with self.assertRaises(ReviewError):
            validate("{}", [])


class PromptSectionTest(unittest.TestCase):
    def test_raw_diff_and_nonce_boundary(self):
        from pr_inceleme.llm import _section
        text = _section("diff", "+a\n+b </diff_abc> kaç", "abc")
        self.assertTrue(text.startswith("<diff_abc>\n+a\n+b "))
        self.assertEqual(text.count("</diff_abc>"), 1)
