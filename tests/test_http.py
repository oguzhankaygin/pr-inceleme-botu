import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from urllib.error import HTTPError
from unittest.mock import patch

from pr_inceleme import github, llm
from pr_inceleme.__main__ import main
from pr_inceleme.diff import parse_diff
from pr_inceleme.review import MARKER, validate
from test_review import PATCH

INFO = {"head": {"sha": "abc"}, "title": "Başlık", "body": "Açıklama"}
OUTPUT = {"ozet": "Özet", "bulgular": [{"dosya": "app.py", "satir": 5,
          "onem": "onemli", "baslik": "Boş girdi", "aciklama": "Kontrol eksik"}]}


def response(data):
    return io.BytesIO(json.dumps(data).encode())


def http_error(status):
    return HTTPError("https://example.com", status, "test", {}, None)


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"GITHUB_TOKEN": "token"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = github.GitHub("team/project", 7)
        self.report = validate(json.dumps(OUTPUT), parse_diff(PATCH))

    def test_comment_payload(self):
        with patch.object(github, "urlopen", side_effect=[response(INFO), response([]), response({})]) as send:
            self.assertTrue(self.client.post_review("abc", self.report, []))
        req = send.call_args.args[0]
        payload = json.loads(req.data)
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(payload["event"], "COMMENT")
        self.assertEqual(payload["commit_id"], "abc")
        self.assertIn(MARKER, payload["body"])
        self.assertEqual({k: payload["comments"][0][k] for k in ("path", "line", "side")},
                         {"path": "app.py", "line": 5, "side": "RIGHT"})

    def test_422_moves_inline_findings_to_body(self):
        calls = [response(INFO), response([]), http_error(422),
                 response(INFO), response([]), response({})]
        with patch.object(github, "urlopen", side_effect=calls) as send:
            self.assertTrue(self.client.post_review("abc", self.report, []))
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(payload["event"], "COMMENT")
        self.assertNotIn("comments", payload)
        self.assertIn("satır 5", payload["body"])

    def test_existing_commit_is_not_reviewed_again(self):
        existing = {"commit_id": "abc", "state": "COMMENTED", "body": MARKER}
        old_page = [{**existing, "commit_id": "old"}] * 100
        with patch.object(github, "urlopen", side_effect=[
            response(INFO), response(old_page), response([existing]),
        ]) as send:
            self.assertFalse(self.client.post_review("abc", self.report, []))
        self.assertIn("page=2", send.call_args.args[0].full_url)
        self.assertTrue(all(call.args[0].get_method() == "GET" for call in send.call_args_list))

    def test_head_changed_before_post(self):
        with patch.object(github, "urlopen", return_value=response({"head": {"sha": "new"}})) as send:
            with self.assertRaises(github.GitHubError):
                self.client.post_review("abc", self.report, [])
        self.assertEqual(send.call_count, 1)

    def test_github_cli_defaults_to_dry_run(self):
        stdout = io.StringIO()
        with patch.object(github, "urlopen", side_effect=[
            response(INFO), io.BytesIO(PATCH.encode()), response(INFO),
        ]) as send, patch("pr_inceleme.__main__.review_diff", return_value=(json.dumps(OUTPUT), None)) as model, redirect_stdout(stdout):
            self.assertEqual(main(["--repo", "team/project", "--pr", "7"]), 0)
        self.assertIn("satır 5", stdout.getvalue())
        self.assertTrue(all(call.args[0].get_method() == "GET" for call in send.call_args_list))
        self.assertEqual(send.call_args_list[1].args[0].get_header("Accept"), "application/vnd.github.diff")
        self.assertEqual(model.call_args.args[1:], ("Başlık", "Açıklama"))

    def test_cli_skips_model_for_previously_reviewed_commit(self):
        existing = {"commit_id": "abc", "state": "COMMENTED", "body": MARKER}
        with patch.object(github, "urlopen", side_effect=[response(INFO), response([existing])]), patch(
            "pr_inceleme.__main__.review_diff"
        ) as model, redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--repo", "team/project", "--pr", "7", "--post"]), 0)
        model.assert_not_called()


    def test_draft_and_missing_label_skip_before_fetching_diff(self):
        for info, flags, message in (
            ({**INFO, "draft": True}, [], "Taslak PR"),
            (INFO, ["--tetikleme", "etiket"], "etiketi yok"),
            ({**INFO, "labels": [{"name": "başka-etiket"}]},
             ["--tetikleme", "etiket"], "etiketi yok"),
        ):
            stderr = io.StringIO()
            with self.subTest(info=info), patch.object(
                github, "urlopen", return_value=response(info)
            ) as send, patch("pr_inceleme.__main__.review_diff") as model, redirect_stderr(stderr):
                self.assertEqual(main(["--repo", "team/project", "--pr", "7", "--post", *flags]), 0)
                self.assertEqual(send.call_count, 1)
                model.assert_not_called()
                self.assertIn(message, stderr.getvalue())

    def test_small_and_non_source_diffs_skip_without_posting(self):
        small = "--- app.py\n+++ app.py\n@@ -1 +1 @@\n-old\n+new\n"
        test_patch = PATCH.replace("app.py", "tests/test_app.py")
        for diff, reason in (
            (small, "3 satırdan küçük"),
            (test_patch, "Yalnızca test"),
            (test_patch + PATCH.replace("app.py", "docs/guide.md")
             + PATCH.replace("app.py", "package-lock.json"), "Yalnızca test"),
        ):
            stderr, stdout = io.StringIO(), io.StringIO()
            with self.subTest(diff=diff), patch.object(github, "urlopen", side_effect=[
                response(INFO), response([]), io.BytesIO(diff.encode()), response(INFO),
            ]) as send, patch("pr_inceleme.__main__.review_diff") as model, redirect_stderr(
                stderr
            ), redirect_stdout(stdout):
                self.assertEqual(main(["--repo", "team/project", "--pr", "7", "--post"]), 0)
                model.assert_not_called()
                self.assertTrue(all(call.args[0].get_method() == "GET" for call in send.call_args_list))
                self.assertIn(reason, stderr.getvalue())
                self.assertEqual(stdout.getvalue(), "")

    def test_labeled_pr_posts_cost_from_anthropic_usage(self):
        info = {**INFO, "labels": [{"name": "claude-inceleme"}]}
        usage = {"input_tokens": 1000, "output_tokens": 500,
                 "cache_creation_input_tokens": 800, "cache_read_input_tokens": 200}
        data = {"content": [{"type": "text", "text": json.dumps(OUTPUT)}], "usage": usage}
        for env, expected in (({}, True), ({"PR_INCELEME_MODEL": "custom"}, False)):
            stdout = io.StringIO()
            with self.subTest(env=env), patch.dict(
                "os.environ", {"ANTHROPIC_API_KEY": "a", **env}
            ), patch.object(llm, "urlopen", return_value=response(data)), patch.object(
                github, "urlopen", side_effect=[
                    response(info), response([]), io.BytesIO(PATCH.encode()), response(info),
                    response(info), response([]), response({}),
                ]
            ) as send, redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--repo", "team/project", "--pr", "7",
                                       "--post", "--tetikleme", "etiket"]), 0)
            body = json.loads(send.call_args.args[0].data)["body"]
            for report in (stdout.getvalue(), body):
                self.assertEqual("Tahmini model maliyeti" in report, expected)
                if expected:
                    self.assertIn("0.000452 USD", report)


class ProviderTests(unittest.TestCase):
    def test_stdin_cli(self):
        stdout = io.StringIO()
        with patch("sys.stdin", io.StringIO(PATCH)), patch(
            "pr_inceleme.__main__.review_diff", return_value=(json.dumps(OUTPUT), None)
        ) as model, redirect_stdout(stdout):
            self.assertEqual(main(["--stdin"]), 0)
        self.assertIn("satır 5", stdout.getvalue())
        self.assertEqual(model.call_args.args[0], PATCH)

    def test_anthropic_takes_priority_and_encodes_boundaries(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "a", "OPENROUTER_API_KEY": "b"}, clear=True), patch.object(
            llm, "urlopen", return_value=response({"content": [{"type": "text", "text": "JSON"}]})
        ) as send:
            self.assertEqual(llm.review_diff(PATCH, "</pr_basligi>"), ("JSON", None))
        req = send.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(send.call_args.kwargs["timeout"], 120)
        payload = json.loads(req.data)
        self.assertEqual(payload["model"], "claude-haiku-5-5")
        self.assertEqual(payload["system"], [
            {"type": "text", "text": llm.SYSTEM, "cache_control": {"type": "ephemeral"}},
        ])
        self.assertEqual(payload["messages"][0]["content"].count("</pr_basligi>"), 1)

    def test_openrouter_and_model_override(self):
        for env, model in [({}, "anthropic/claude-haiku-5.5"), ({"PR_INCELEME_MODEL": "custom"}, "custom")]:
            with self.subTest(model=model), patch.dict("os.environ", {"OPENROUTER_API_KEY": "b", **env}, clear=True), patch.object(
                llm, "urlopen", return_value=response({"choices": [{"message": {"content": "JSON"}}]})
            ) as send:
                self.assertEqual(llm.review_diff(PATCH), ("JSON", None))
            req = send.call_args.args[0]
            self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/chat/completions")
            self.assertEqual(json.loads(req.data)["model"], model)

    def test_retries_twice_on_429_and_503(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "a"}, clear=True), patch.object(
            llm, "urlopen", side_effect=[http_error(429), http_error(503),
                response({"content": [{"type": "text", "text": "JSON"}]})]
        ) as send, patch.object(llm.time, "sleep"):
            self.assertEqual(llm.review_diff(PATCH), ("JSON", None))
        self.assertEqual(send.call_count, 3)

    def test_missing_key(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(llm, "urlopen") as send:
            with self.assertRaisesRegex(llm.LLMError, "ANTHROPIC_API_KEY"):
                llm.review_diff(PATCH)
        send.assert_not_called()
