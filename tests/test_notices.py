import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import NoticeConfig
from ok_ww_automator.models import RunResult, SheetRunConfig
from ok_ww_automator.notices import (
    MailgunNoticeClient,
    WxPusherNoticeClient,
    build_notice_message,
    should_notify,
)
from ok_ww_automator.time_utils import BEIJING_TZ


class FakeResponse:
    def __init__(self, body=None) -> None:
        self.body = body or {"code": 1000}
        self.raise_count = 0

    def raise_for_status(self) -> None:
        self.raise_count += 1

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, response=None) -> None:
        self.response = response or FakeResponse()
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.response


class NoticesTest(unittest.TestCase):
    def test_should_notify_all_final_statuses_until_healthchecks_exist(self) -> None:
        base = dt.datetime(2026, 5, 16, 5, 0, tzinfo=BEIJING_TZ)

        self.assertTrue(should_notify(RunResult("daily", base, base, "failure")))
        self.assertTrue(should_notify(RunResult("daily", base, base, "needs review")))
        self.assertTrue(should_notify(RunResult("daily", base, base, "success")))
        self.assertTrue(should_notify(RunResult("daily", base, base, "skipped")))
        self.assertFalse(should_notify(RunResult("daily", base, None, "running")))

    def test_build_notice_message_includes_problem_context(self) -> None:
        base = dt.datetime(2026, 5, 16, 5, 0, tzinfo=BEIJING_TZ)
        result = RunResult(
            "daily",
            base,
            base,
            "needs review",
            daily_points=60,
            decision="retry exhausted",
            error="bad",
        )

        message = build_notice_message(result, SheetRunConfig(which_to_farm="模拟领域"), account_id="cn")

        self.assertIn("[cn]", message.subject)
        self.assertIn("需复查", message.subject)
        self.assertIn("retry exhausted", message.text)
        self.assertIn("<!doctype html>", message.html)
        self.assertIn("执行概览", message.html)
        self.assertIn("bad", message.html)

    def test_mailgun_client_posts_message(self) -> None:
        session = FakeSession()
        config = NoticeConfig(
            enabled=True,
            channels=("mailgun",),
            mailgun_api_key="key",
            mailgun_domain="example.com",
            mailgun_recipient="me@example.com",
        )
        base = dt.datetime(2026, 5, 16, 5, 0, tzinfo=BEIJING_TZ)
        result = RunResult("daily", base, base, "failure")

        MailgunNoticeClient(config, session=session).notify(result, SheetRunConfig())

        url, kwargs = session.posts[0]
        self.assertEqual(url, "https://api.mailgun.net/v3/example.com/messages")
        self.assertEqual(kwargs["auth"], ("api", "key"))
        self.assertEqual(kwargs["data"]["to"], "me@example.com")
        self.assertIn("html", kwargs["data"])

    def test_wxpusher_client_posts_simple_push(self) -> None:
        session = FakeSession()
        config = NoticeConfig(enabled=True, channels=("wxpusher",), wxpusher_spt="spt")
        base = dt.datetime(2026, 5, 16, 5, 0, tzinfo=BEIJING_TZ)
        result = RunResult("stamina", base, base, "failure")

        WxPusherNoticeClient(config, session=session).notify(result, SheetRunConfig())

        url, kwargs = session.posts[0]
        self.assertEqual(url, "https://wxpusher.zjiecode.com/api/send/message/simple-push")
        self.assertEqual(kwargs["json"]["spt"], "spt")
        self.assertEqual(kwargs["json"]["contentType"], 2)


if __name__ == "__main__":
    unittest.main()
