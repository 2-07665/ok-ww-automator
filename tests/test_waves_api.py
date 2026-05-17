from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import WavesApiConfig
from ok_ww_automator.waves_api import (
    SERVER_ID,
    WavesApiClient,
    WavesDailyInfo,
    extract_daily_info,
    is_api_success,
    parse_response,
    server_id_for_role,
)


class FakeResponse:
    def __init__(self, payload=None, text="", json_exc=None) -> None:
        self.payload = payload
        self.text = text
        self.json_exc = json_exc

    def json(self):
        if self.json_exc is not None:
            raise self.json_exc
        return self.payload


class FakeSession:
    def __init__(self, responses=None, exc=None) -> None:
        self.responses = list(responses or [])
        self.exc = exc
        self.posts = []
        self.closed = False

    def post(self, url, *, headers, data, timeout):
        self.posts.append((url, headers, data, timeout))
        if self.exc is not None:
            raise self.exc
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class WavesApiTest(unittest.TestCase):
    def test_parse_response_decodes_nested_data_json(self) -> None:
        response = FakeResponse({"code": 0, "data": '{"energyData": {"cur": "12"}}'})

        parsed = parse_response(response)

        self.assertEqual(parsed["data"]["energyData"]["cur"], "12")

    def test_parse_response_handles_non_json(self) -> None:
        parsed = parse_response(FakeResponse(text="oops", json_exc=ValueError("bad")))

        self.assertEqual(parsed["code"], -999)
        self.assertEqual(parsed["data"], "oops")

    def test_extract_daily_info_returns_metrics(self) -> None:
        info = extract_daily_info(
            {
                "code": 0,
                "data": {
                    "energyData": {"cur": "120"},
                    "storeEnergyData": {"cur": "40"},
                    "livenessData": {"cur": "80"},
                },
            }
        )

        self.assertEqual(info, WavesDailyInfo(stamina=120, backup_stamina=40, daily_points=80))

    def test_extract_daily_info_rejects_failed_response(self) -> None:
        self.assertIsNone(extract_daily_info({"code": 500, "data": {}}))

    def test_is_api_success_accepts_legacy_signin_code(self) -> None:
        self.assertTrue(is_api_success({"code": 1511}))
        self.assertFalse(is_api_success({"code": 500}))

    def test_server_id_for_role_uses_net_mapping(self) -> None:
        self.assertEqual(server_id_for_role("100000001"), SERVER_ID)
        self.assertEqual(server_id_for_role("800000000"), "919752ae5ea09c1ced910dd668a63ffb")

    def test_client_posts_daily_info_with_config_credentials(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "energyData": {"cur": 200},
                            "storeEnergyData": {"cur": 10},
                            "livenessData": {"cur": 100},
                        },
                    }
                )
            ]
        )
        client = WavesApiClient(
            WavesApiConfig(enabled=True, role_id="123", token="tok", did="did"),
            session=session,
            base_url="https://example.test",
        )

        info = client.read_daily_info()

        self.assertEqual(info, WavesDailyInfo(stamina=200, backup_stamina=10, daily_points=100))
        url, headers, data, timeout = session.posts[0]
        self.assertEqual(url, "https://example.test/gamer/widget/game3/getData")
        self.assertEqual(headers["token"], "tok")
        self.assertEqual(headers["did"], "did")
        self.assertEqual(data["roleId"], "123")
        self.assertEqual(timeout, 10.0)

    def test_client_transport_error_returns_failure_response(self) -> None:
        session = FakeSession(exc=RuntimeError("network"))
        client = WavesApiClient(
            WavesApiConfig(enabled=True, role_id="123", token="tok", did="did"),
            session=session,
        )

        response = client.get_daily_info()

        self.assertEqual(response["code"], -999)
        self.assertIn("network", response["msg"])


if __name__ == "__main__":
    unittest.main()
