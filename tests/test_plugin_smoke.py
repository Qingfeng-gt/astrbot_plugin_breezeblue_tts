"""Offline smoke tests for the Breeze Blue AstrBot plugin.

AstrBot is not installed in this test environment, so minimal fake ``astrbot``
modules are injected before importing ``main.py``. The tests cover the pure
logic (text splitting, request payloads, error mapping), commands, the LLM
tool, the WebUI voice APIs, and NapCat audio modes with a stubbed synthesizer.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

ROOT = Path(__file__).resolve().parents[1]
TEMP_DATA = Path(tempfile.mkdtemp(prefix="bbtts-test-"))


class FakePlain:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeRecord:
    def __init__(self, file: str, **kwargs) -> None:
        self.file = file
        self.text = kwargs.get("text")


class FakeReply:
    def __init__(self, message_str: str = "") -> None:
        self.message_str = message_str


class FakeRequest:
    def __init__(self) -> None:
        self.query: dict = {}
        self._json: dict = {}

    async def json(self, default=None):
        return self._json


def fake_json_response(data, **kwargs):
    return {"status": "ok", "data": data}


def fake_error_response(message, status_code=400):
    return {"status": "error", "message": message, "status_code": status_code}


class FakeFilter:
    def command(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def llm_tool(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


class FakeStar:
    def __init__(self, context=None) -> None:
        self.context = context


class FakeContext:
    def register_web_api(self, *args, **kwargs) -> None:
        pass


class FakeEvent:
    def __init__(
        self,
        message_str: str = "",
        *,
        messages=None,
        umo: str = "aiocqhttp:FriendMessage:1",
        private: bool = True,
        admin: bool = False,
        platform_name: str = "webchat",
    ) -> None:
        self.message_str = message_str
        self.messages = messages or []
        self.unified_msg_origin = umo
        self.private = private
        self.admin = admin
        self._extras: dict = {}
        self.sent: list = []
        self.platform_name = platform_name

    def get_platform_name(self) -> str:
        return self.platform_name

    def get_message_str(self) -> str:
        return self.message_str

    def get_messages(self):
        return self.messages

    def plain_result(self, text: str):
        return ("plain", text)

    def chain_result(self, chain):
        return ("chain", chain)

    def is_private_chat(self) -> bool:
        return self.private

    def is_admin(self) -> bool:
        return self.admin

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key, value) -> None:
        self._extras[key] = value

    async def send(self, message) -> None:
        self.sent.append(message)


def _install_fake_astrbot() -> None:
    astrbot = types.ModuleType("astrbot")
    astrbot.__path__ = []
    api = types.ModuleType("astrbot.api")
    api.__path__ = []
    api.AstrBotConfig = dict
    api.logger = logging.getLogger("bbtts-test")

    api_event = types.ModuleType("astrbot.api.event")
    api_event.__path__ = []
    api_event.AstrMessageEvent = FakeEvent
    api_event.filter = FakeFilter()

    api_web = types.ModuleType("astrbot.api.web")
    api_web.__path__ = []
    api_web.request = FakeRequest()
    api_web.json_response = fake_json_response
    api_web.error_response = fake_error_response

    api_components = types.ModuleType("astrbot.api.message_components")
    api_components.__path__ = []
    api_components.Plain = FakePlain
    api_components.Record = FakeRecord
    api_components.Reply = FakeReply

    api_star = types.ModuleType("astrbot.api.star")
    api_star.__path__ = []
    api_star.Context = FakeContext
    api_star.Star = FakeStar
    api_star.register = lambda *args, **kwargs: lambda cls: cls

    core = types.ModuleType("astrbot.core")
    core.__path__ = []
    core_utils = types.ModuleType("astrbot.core.utils")
    core_utils.__path__ = []
    core_path = types.ModuleType("astrbot.core.utils.astrbot_path")
    core_path.get_astrbot_plugin_data_path = lambda: str(TEMP_DATA)
    core_path.get_astrbot_temp_path = lambda: str(TEMP_DATA / "temp")

    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": api_event,
            "astrbot.api.web": api_web,
            "astrbot.api.message_components": api_components,
            "astrbot.api.star": api_star,
            "astrbot.core": core,
            "astrbot.core.utils": core_utils,
            "astrbot.core.utils.astrbot_path": core_path,
        }
    )


_install_fake_astrbot()

spec = importlib.util.spec_from_file_location("bbtts_main", ROOT / "main.py")
plugin_main = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin_main
assert spec.loader is not None
spec.loader.exec_module(plugin_main)


def make_plugin(**overrides):
    config = {
        "api_key": "brz_test",
        "voice_id": "voc_test",
        "language_code": "zh",
        "model_id": "",
        "napcat_audio_mode": "wav",
    }
    config.update(overrides)
    return plugin_main.BreezeBlueTTSPlugin(FakeContext(), config)


class PureLogicTests(unittest.TestCase):
    def test_split_text_prefers_sentence_boundaries(self):
        self.assertEqual(
            plugin_main.split_text("你好。世界", 4),
            ["你好。", "世界"],
        )

    def test_split_text_hard_splits_long_sentence(self):
        self.assertEqual(
            plugin_main.split_text("abcdefgh", 3),
            ["abc", "def", "gh"],
        )

    def test_split_text_handles_whitespace(self):
        self.assertEqual(plugin_main.split_text("   ", 10), [])

    def test_payload_omits_defaults(self):
        request = plugin_main.TtsRequest(text="hi", voice_id="voc_x")
        self.assertEqual(request.payload(), {"text": "hi"})

    def test_payload_includes_settings(self):
        request = plugin_main.TtsRequest(
            text="hi",
            voice_id="voc_x",
            model_id="breeze-tts-2",
            language_code="zh",
            instructions="温柔地说",
            speed=1.2,
            volume=0.8,
            guidance_scale=4.0,
            use_speaker_boost=True,
        )
        payload = request.payload()
        self.assertEqual(payload["model_id"], "breeze-tts-2")
        self.assertEqual(payload["language_code"], "zh")
        self.assertEqual(payload["instructions"], "温柔地说")
        self.assertEqual(
            payload["voice_settings"],
            {
                "speed": 1.2,
                "volume": 0.8,
                "guidance_scale": 4.0,
                "use_speaker_boost": True,
            },
        )

    def test_error_parsing(self):
        error = plugin_main.BreezeBlueClient._error(
            429,
            {"Retry-After": "7"},
            json.dumps({"error": "slow down", "code": "rate_limited"}).encode(),
        )
        self.assertEqual(error.status, 429)
        self.assertEqual(error.code, "rate_limited")
        self.assertEqual(error.retry_after, 7.0)
        self.assertIn("slow down", str(error))


class PluginFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_tts_command_returns_voice_record(self):
        plugin = make_plugin()
        calls = []

        async def fake_synthesize(text, umo, platform=""):
            calls.append((text, umo))
            return b"fake-mp3-bytes"

        plugin._synthesize = fake_synthesize
        event = FakeEvent("/tts 你好世界")

        results = [result async for result in plugin.tts_command(event)]
        self.assertEqual(len(results), 1)
        kind, chain = results[0]
        self.assertEqual(kind, "chain")
        self.assertEqual(calls, [("你好世界", event.unified_msg_origin)])
        self.assertEqual(len(chain), 1)
        self.assertIsInstance(chain[0], FakeRecord)
        self.assertTrue(chain[0].file.startswith("base64://"))
        self.assertEqual(
            base64.b64decode(chain[0].file.removeprefix("base64://")),
            b"fake-mp3-bytes",
        )

    async def test_tts_command_uses_quoted_message(self):
        plugin = make_plugin()
        seen = {}

        async def fake_synthesize(text, umo, platform=""):
            seen["text"] = text
            return b"audio"

        plugin._synthesize = fake_synthesize
        event = FakeEvent("/tts", messages=[FakeReply("被引用的消息")])

        results = [result async for result in plugin.tts_command(event)]
        self.assertEqual(results[0][0], "chain")
        self.assertEqual(seen["text"], "被引用的消息")

    async def test_napcat_silk_mode_requests_wav_and_passes_through(self):
        plugin = make_plugin(output_format="mp3", napcat_audio_mode="silk")

        async def fake_silk(wav_bytes):
            self.assertEqual(wav_bytes, b"wav-from-breeze")
            return b"\x02#!SILK_V3silk"

        plugin._wav_bytes_to_tencent_silk = fake_silk

        request = plugin._make_request("你好", "umo", "aiocqhttp")
        self.assertEqual(request.output_format, "wav")
        self.assertEqual(
            plugin._make_request("你好", "umo", "webchat").output_format,
            "mp3",
        )

        record = await plugin._make_record(b"wav-from-breeze", "你好", "aiocqhttp")
        self.assertIsInstance(record, plugin_main._NapCatPassthroughRecord)
        expected = base64.b64encode(b"\x02#!SILK_V3silk").decode("ascii")
        self.assertEqual(await record.convert_to_base64(), expected)

    async def test_napcat_wav_mode_uses_normal_record(self):
        plugin = make_plugin(napcat_audio_mode="wav")
        payload, passthrough = await plugin._prepare_napcat_audio(b"wav-data")
        self.assertEqual(payload, b"wav-data")
        self.assertFalse(passthrough)

        record = await plugin._make_record(b"wav-data", "你好", "aiocqhttp")
        self.assertNotIsInstance(record, plugin_main._NapCatPassthroughRecord)

    async def test_napcat_native_mode_passes_original_audio(self):
        plugin = make_plugin(napcat_audio_mode="native")
        payload, passthrough = await plugin._prepare_napcat_audio(b"mp3-data")
        self.assertEqual(payload, b"mp3-data")
        self.assertTrue(passthrough)

    async def test_napcat_silk_failure_falls_back_to_original_audio(self):
        plugin = make_plugin(napcat_audio_mode="silk")

        async def broken_silk(wav_bytes):
            raise RuntimeError("pysilk unavailable")

        plugin._wav_bytes_to_tencent_silk = broken_silk
        payload, passthrough = await plugin._prepare_napcat_audio(b"wav-data")
        self.assertEqual(payload, b"wav-data")
        self.assertTrue(passthrough)
        self.assertTrue(plugin._silk_fallback_warned)

    async def test_webchat_keeps_normal_record(self):
        plugin = make_plugin(output_format="mp3")
        record = await plugin._make_record(b"mp3-data", "你好", "webchat")
        self.assertNotIsInstance(record, plugin_main._NapCatPassthroughRecord)
        self.assertEqual(
            base64.b64decode(record.file.removeprefix("base64://")),
            b"mp3-data",
        )

    async def test_napcat_passthrough_record_rejects_non_base64(self):
        record = plugin_main._NapCatPassthroughRecord(file="https://example.com/a.silk")
        with self.assertRaises(ValueError):
            await record.convert_to_base64()

    async def test_tts_command_rejects_too_many_segments(self):
        plugin = make_plugin(max_chars=50, max_segments=1)

        async def fake_synthesize(text, umo, platform=""):
            return b"audio"

        plugin._synthesize = fake_synthesize
        event = FakeEvent("/tts " + "a" * 101)  # 3 segments of at most 50 chars

        results = [result async for result in plugin.tts_command(event)]
        self.assertEqual(results[0][0], "plain")
        self.assertIn("文本过长", results[0][1])

    async def test_llm_tool_sends_voice_with_instructions(self):
        plugin = make_plugin()
        calls = []

        async def fake_synthesize(
            text,
            umo,
            platform="",
            instructions=None,
        ):
            calls.append((text, umo, platform, instructions))
            return b"audio"

        plugin._synthesize = fake_synthesize
        event = FakeEvent(platform_name="aiocqhttp")

        result = await plugin.breeze_blue_tts(
            event,
            text="你好",
            instructions="温柔、平静地说",
        )

        self.assertIsNone(result)
        self.assertEqual(
            calls,
            [
                (
                    "你好",
                    event.unified_msg_origin,
                    "aiocqhttp",
                    "温柔、平静地说",
                )
            ],
        )
        self.assertEqual(len(event.sent), 1)
        kind, chain = event.sent[0]
        self.assertEqual(kind, "chain")
        self.assertEqual(len(chain), 1)
        self.assertIsInstance(chain[0], FakeRecord)
        self.assertEqual(chain[0].text, "你好")

    async def test_llm_tool_requires_text(self):
        plugin = make_plugin()
        event = FakeEvent()

        result = await plugin.breeze_blue_tts(event, text="   ")

        self.assertIsInstance(result, str)
        self.assertIn("text", result)
        self.assertEqual(event.sent, [])

    async def test_llm_tool_reports_missing_api_key(self):
        plugin = make_plugin()
        plugin._api_key = lambda: ""
        event = FakeEvent()

        result = await plugin.breeze_blue_tts(event, text="你好")

        self.assertIn("API Key", result)
        self.assertEqual(event.sent, [])

    async def test_llm_tool_maps_breeze_error(self):
        plugin = make_plugin()

        async def fake_synthesize(
            text,
            umo,
            platform="",
            instructions=None,
        ):
            raise plugin_main.BreezeBlueError("bad key", status=401)

        plugin._synthesize = fake_synthesize
        event = FakeEvent()

        result = await plugin.breeze_blue_tts(event, text="你好")

        self.assertIn("401", result)

    async def test_state_round_trip(self):
        plugin = make_plugin()
        plugin._state["voices"]["umo:1"] = "voc_saved"
        await plugin._save_state()

        restored = make_plugin()
        restored._load_state()
        self.assertEqual(restored._state["voices"]["umo:1"], "voc_saved")

    async def test_api_list_voices(self):
        plugin = make_plugin()
        captured = {}

        class FakeClient:
            async def list_voices(
                self,
                *,
                search: str = "",
                language_code: str = "",
                limit: int = 10,
            ):
                captured.update(
                    search=search,
                    language_code=language_code,
                    limit=limit,
                )
                return {
                    "voices": [
                        {
                            "voice_id": "voc_1",
                            "name": "测试音色",
                            "language_code": "zh",
                            "gender": "female",
                            "age": "young",
                            "tone": ["calm"],
                        }
                    ],
                    "total": 1,
                    "has_more": False,
                }

        async def fake_get_client():
            return FakeClient()

        plugin._get_client = fake_get_client
        plugin_main.request.query = {"search": "女声", "language_code": "zh"}

        response = await plugin.api_list_voices()

        self.assertEqual(response["status"], "ok")
        self.assertEqual(
            captured,
            {"search": "女声", "language_code": "zh", "limit": 50},
        )
        data = response["data"]
        self.assertEqual(data["selected_voice_id"], "voc_test")
        self.assertEqual(data["voices"][0]["voice_id"], "voc_1")
        self.assertEqual(data["voices"][0]["name"], "测试音色")

    async def test_api_select_voice(self):
        plugin = make_plugin()
        plugin_main.request._json = {"voice_id": "voc_new"}

        response = await plugin.api_select_voice()

        self.assertEqual(response["status"], "ok")
        self.assertEqual(plugin.config["voice_id"], "voc_new")

    async def test_api_select_voice_rejects_invalid_id(self):
        plugin = make_plugin()
        plugin_main.request._json = {"voice_id": "../bad"}

        response = await plugin.api_select_voice()

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["status_code"], 400)
        self.assertEqual(plugin.config["voice_id"], "voc_test")

    async def test_api_list_voices_requires_api_key(self):
        plugin = make_plugin()
        plugin._api_key = lambda: ""

        response = await plugin.api_list_voices()

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["status_code"], 400)

    async def test_group_session_settings_require_admin(self):
        plugin = make_plugin()
        event = FakeEvent("/tts_voice use voc_other", private=False, admin=False)

        results = [result async for result in plugin.tts_voice_command(event)]
        self.assertEqual(results[0][0], "plain")
        self.assertIn("管理员", results[0][1])
        self.assertNotIn(event.unified_msg_origin, plugin._state["voices"])


class ClientHTTPTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the real aiohttp request/response path against a local server."""

    async def asyncSetUp(self):
        self.captured = {}

        async def tts_handler(request):
            self.captured["tts"] = {
                "voice_id": request.match_info["voice_id"],
                "headers": dict(request.headers),
                "query": dict(request.query),
                "json": await request.json(),
            }
            voice_id = request.match_info["voice_id"]
            if voice_id == "voc_missing":
                return web.json_response(
                    {
                        "ok": False,
                        "code": "voice_not_found",
                        "error": "missing",
                        "detail": "no such voice",
                    },
                    status=404,
                )
            if voice_id == "voc_slow":
                return web.json_response(
                    {
                        "ok": False,
                        "code": "rate_limited",
                        "error": "slow down",
                        "detail": "retry later",
                    },
                    status=429,
                    headers={"Retry-After": "3"},
                )
            return web.Response(
                body=b"ID3audio",
                headers={
                    "Content-Type": "audio/mpeg",
                    "history-item-id": "hist_1",
                },
            )

        async def voices_handler(request):
            self.captured["voices"] = {
                "headers": dict(request.headers),
                "query": dict(request.query),
            }
            return web.json_response(
                {
                    "voices": [{"voice_id": "voc_x", "name": "Test"}],
                    "total": 1,
                    "has_more": False,
                }
            )

        app = web.Application()
        app.router.add_post("/v1/text-to-speech/{voice_id}", tts_handler)
        app.router.add_get("/v1/voices", voices_handler)
        self.server = TestServer(app)
        await self.server.start_server()
        self.session = aiohttp.ClientSession()
        self.client = plugin_main.BreezeBlueClient(
            "brz_test",
            str(self.server.make_url("")).rstrip("/"),
            self.session,
        )

    async def asyncTearDown(self):
        await self.session.close()
        await self.server.close()

    async def test_synthesize_request_and_response(self):
        audio, history_id = await self.client.synthesize(
            plugin_main.TtsRequest(text="你好", voice_id="voc_x", speed=1.2)
        )

        self.assertEqual(audio, b"ID3audio")
        self.assertEqual(history_id, "hist_1")
        captured = self.captured["tts"]
        self.assertEqual(captured["voice_id"], "voc_x")
        self.assertEqual(captured["headers"]["xi-api-key"], "brz_test")
        self.assertEqual(
            captured["query"],
            {"output_format": "mp3", "delivery": "sync"},
        )
        self.assertEqual(
            captured["json"],
            {"text": "你好", "voice_settings": {"speed": 1.2}},
        )

    async def test_synthesize_maps_429(self):
        with self.assertRaises(plugin_main.BreezeBlueError) as context:
            await self.client.synthesize(
                plugin_main.TtsRequest(text="x", voice_id="voc_slow")
            )
        error = context.exception
        self.assertEqual(error.status, 429)
        self.assertEqual(error.code, "rate_limited")
        self.assertEqual(error.retry_after, 3.0)

    async def test_synthesize_maps_404(self):
        with self.assertRaises(plugin_main.BreezeBlueError) as context:
            await self.client.synthesize(
                plugin_main.TtsRequest(text="x", voice_id="voc_missing")
            )
        self.assertEqual(context.exception.status, 404)
        self.assertIn("voice_not_found", str(context.exception))

    async def test_list_voices_request(self):
        data = await self.client.list_voices(search="女声", language_code="zh", limit=5)
        self.assertEqual(data["voices"][0]["voice_id"], "voc_x")
        captured = self.captured["voices"]
        self.assertEqual(captured["headers"]["xi-api-key"], "brz_test")
        self.assertEqual(
            captured["query"],
            {"page_size": "5", "search": "女声", "language_code": "zh"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
