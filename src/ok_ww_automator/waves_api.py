"""Waves/Kuro daily-info API adapter."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import json
import random
from typing import Any, Protocol

from .config import WavesApiConfig

WAVES_GAME_ID = 3
WAVES_CODE_TRANSPORT_ERROR = -999

MAIN_URL = "https://api.kurobbs.com"
GAME_DATA_URL = f"{MAIN_URL}/gamer/widget/game3/getData"
SIGNIN_URL = f"{MAIN_URL}/encourage/signIn/v2"

SERVER_ID = "76402e5b20be2c39f095a152090afddc"
SERVER_ID_NET = "919752ae5ea09c1ced910dd668a63ffb"
NET_SERVER_ID_MAP = {
    5: "591d6af3a3090d8ea00d8f86cf6d7501",
    6: "6eb2a235b30d05efd77bedb5cf60999e",
    7: "86d52186155b148b5c138ceb41be9650",
    8: "919752ae5ea09c1ced910dd668a63ffb",
    9: "10cd7254d57e58ae560b15d51e34b4c",
}

CONTENT_TYPE = "application/x-www-form-urlencoded; charset=utf-8"
IOS_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko)  KuroGameBox/2.9.0"
)
ANDROID_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16; 25098PN5AC Build/BP2A.250605.031.A3; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/143.0.7499.34 "
    "Mobile Safari/537.36 Kuro/2.9.0 KuroGameBox/2.9.0"
)


class HttpSession(Protocol):
    def post(self, url: str, *, headers: dict[str, str], data: dict[str, Any], timeout: float): ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class WavesDailyInfo:
    stamina: int
    backup_stamina: int
    daily_points: int


class WavesApiClient:
    def __init__(
        self,
        config: WavesApiConfig,
        *,
        session: HttpSession | None = None,
        base_url: str = MAIN_URL,
    ) -> None:
        self.config = config
        self.base_url = base_url.rstrip("/")
        self.session = session or _new_requests_session()

    def close(self) -> None:
        self.session.close()

    def get_daily_info(self, *, timeout: float = 10.0) -> dict[str, Any]:
        self.config.require_credentials()
        headers = build_base_headers()
        headers.update(
            {
                "token": self.config.token or "",
                "did": self.config.did or "",
                "b-at": "",
            }
        )
        data = {
            "type": "2",
            "sizeType": "1",
            "gameId": WAVES_GAME_ID,
            "serverId": server_id_for_role(self.config.role_id or ""),
            "roleId": self.config.role_id or "",
        }
        return self._post(f"{self.base_url}/gamer/widget/game3/getData", headers=headers, data=data, timeout=timeout)

    def sign_in(self, *, timeout: float = 10.0, now: dt.datetime | None = None) -> dict[str, Any]:
        self.config.require_credentials()
        headers = build_base_headers(dev_code="")
        headers.update({"token": self.config.token or ""})
        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": server_id_for_role(self.config.role_id or ""),
            "roleId": self.config.role_id or "",
            "reqMonth": f"{beijing_now(now).month:02}",
        }
        return self._post(f"{self.base_url}/encourage/signIn/v2", headers=headers, data=data, timeout=timeout)

    def read_daily_info(self) -> WavesDailyInfo | None:
        return extract_daily_info(self.get_daily_info())

    def _post(self, url: str, *, headers: dict[str, str], data: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            response = self.session.post(url, headers=headers, data=data, timeout=timeout)
        except Exception as exc:
            return {"code": WAVES_CODE_TRANSPORT_ERROR, "msg": str(exc), "data": None}
        return parse_response(response)


def is_api_success(response: dict[str, Any] | None) -> bool:
    if not isinstance(response, dict):
        return False
    if response.get("success") is True:
        return True
    return response.get("code") in (0, 200, 1511)


def extract_daily_info(response: dict[str, Any]) -> WavesDailyInfo | None:
    if not is_api_success(response):
        return None
    data = response.get("data")
    if not isinstance(data, dict):
        return None

    energy = data.get("energyData") or {}
    store_energy = data.get("storeEnergyData") or {}
    liveness = data.get("livenessData") or {}
    try:
        return WavesDailyInfo(
            stamina=int(energy["cur"]),
            backup_stamina=int(store_energy["cur"]),
            daily_points=int(liveness["cur"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def parse_response(response: Any) -> dict[str, Any]:
    try:
        raw_data = response.json()
    except ValueError:
        return {"code": WAVES_CODE_TRANSPORT_ERROR, "msg": "non-json response", "data": getattr(response, "text", "")}

    if isinstance(raw_data, dict):
        data = raw_data.get("data")
        if isinstance(data, str):
            try:
                raw_data["data"] = json.loads(data)
            except Exception:
                pass
        return raw_data
    return {"code": WAVES_CODE_TRANSPORT_ERROR, "msg": "unexpected response", "data": raw_data}


def build_base_headers(dev_code: str | None = None) -> dict[str, str]:
    platform_source = random.choice(["ios", "android"])
    user_agent = IOS_USER_AGENT if platform_source == "ios" else ANDROID_USER_AGENT
    if dev_code is None:
        dev_code = f"127.0.0.1, {user_agent}"
    return {
        "source": platform_source,
        "Content-Type": CONTENT_TYPE,
        "User-Agent": user_agent,
        "devCode": dev_code,
    }


def server_id_for_role(role_id: str, server_id: str | None = None) -> str:
    if server_id:
        return server_id
    if is_net_role(role_id):
        return NET_SERVER_ID_MAP.get(int(role_id) // 100000000, SERVER_ID_NET)
    return SERVER_ID


def is_net_role(role_id: str) -> bool:
    try:
        return int(role_id) >= 200000000
    except (TypeError, ValueError):
        return False


def beijing_now(value: dt.datetime | None = None) -> dt.datetime:
    beijing_tz = dt.timezone(dt.timedelta(hours=8), name="UTC+08")
    return (value or dt.datetime.now(dt.timezone.utc)).astimezone(beijing_tz)


def _new_requests_session() -> HttpSession:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("Install ok-ww-automator[waves] to use the Waves API") from exc
    return requests.Session()
