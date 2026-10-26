"""Breeze Blue text-to-speech plugin for AstrBot.

This plugin talks to the Breeze Blue Developer API directly (no SDK required):

    POST {base}/v1/text-to-speech/{voice_id}?output_format=mp3
    xi-api-key: brz_...

It provides:

* ``breeze_blue_tts`` tool - the model calls it when it wants to speak
* ``/tts <text>``          - synthesize text and reply with a voice message
* ``/tts_voice ...``       - list voices / select a per-session voice
* WebUI voice picker       - fetch voices and choose the default voice

The implementation deliberately keeps all HTTP handling in this file so the
plugin can be dropped into ``data/plugins`` without any packaging concerns.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain, Record, Reply
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import (
    get_astrbot_plugin_data_path,
    get_astrbot_temp_path,
)

try:  # Plugin views / web APIs were added after AstrBot 4.16.
    from astrbot.api.web import error_response, json_response, request
except ImportError:  # pragma: no cover - older AstrBot still supports commands/tools
    error_response = None
    json_response = None
    request = None

PLUGIN_NAME = "astrbot_plugin_breezeblue_tts"
DEFAULT_BASE_URL = "https://api.breeze.blue"
DEFAULT_VOICE_ID = "voc_xeh3w54cqvnp"  # example voice from the Breeze Blue quickstart
MAX_API_CHARS = 2000  # Breeze Blue allows 2000 chars for accounts with a higher quota
DEFAULT_NAPCAT_AUDIO_MODE = "wav"
NAPCAT_AUDIO_MODES = frozenset({"wav", "silk", "native"})

_COMMAND_ARG_RE = re.compile(r"^\S+\s*", re.DOTALL)
_SENTENCE_END_RE = re.compile(r"(?<=[。！？!?；;…\n])")
_VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")
_LANGUAGE_CODE_RE = re.compile(r"^[A-Za-z]{2}$")
_OUTPUT_FORMAT_RE = re.compile(r"^[a-z0-9_]{1,40}$")


class _NapCatPassthroughRecord(Record):
    """Record that hands its base64 payload to NapCat unchanged.

    AstrBot's normal ``Record.convert_to_base64()`` always transcodes audio to
    WAV. For NapCat we sometimes need the original bytes (or an already encoded
    Tencent SILK stream) to reach the OneBot implementation untouched, so this
    subclass bypasses that conversion.
    """

    async def convert_to_base64(self) -> str:
        file = self.file or ""
        prefix = "base64://"
        if not file.startswith(prefix):
            raise ValueError("NapCat passthrough record requires a base64:// payload")
        return file[len(prefix) :]


# ---------------------------------------------------------------------------
# Breeze Blue API client
# ---------------------------------------------------------------------------


class BreezeBlueError(Exception):
    """An error returned by (or while calling) the Breeze Blue API."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after


@dataclass(slots=True)
class TtsRequest:
    """Parameters accepted by POST /v1/text-to-speech/{voice_id}."""

    text: str
    voice_id: str
    model_id: str | None = None
    language_code: str | None = None
    instructions: str | None = None
    output_format: str = "mp3"
    speed: float = 1.0
    volume: float = 1.0
    guidance_scale: float = 1.0
    use_speaker_boost: bool = False

    def payload(self) -> dict[str, Any]:
        """Build the JSON body. Defaults are omitted to keep requests small."""
        payload: dict[str, Any] = {"text": self.text}
        if self.model_id:
            payload["model_id"] = self.model_id
        if self.language_code:
            payload["language_code"] = self.language_code
        if self.instructions:
            payload["instructions"] = self.instructions

        voice_settings: dict[str, Any] = {}
        if abs(self.speed - 1.0) > 1e-6:
            voice_settings["speed"] = self.speed
        if abs(self.volume - 1.0) > 1e-6:
            voice_settings["volume"] = self.volume
        if abs(self.guidance_scale - 1.0) > 1e-6:
            voice_settings["guidance_scale"] = self.guidance_scale
        if self.use_speaker_boost:
            voice_settings["use_speaker_boost"] = True
        if voice_settings:
            payload["voice_settings"] = voice_settings
        return payload


class BreezeBlueClient:
    """Small async client for the endpoints used by this plugin."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session = session

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "xi-api-key": self.api_key,
            "user-agent": "astrbot-plugin-breezeblue-tts/1.2.0",
        }

    async def synthesize(self, request: TtsRequest) -> tuple[bytes, str | None]:
        """Return ``(audio_bytes, history_item_id)``.

        Breeze Blue returns the audio bytes directly for synchronous delivery.
        """
        url = f"{self.base_url}/v1/text-to-speech/{quote(request.voice_id, safe='')}"
        params = {"output_format": request.output_format, "delivery": "sync"}
        headers = {**self._headers, "accept": "audio/*"}

        try:
            async with self._session.post(
                url,
                params=params,
                json=request.payload(),
                headers=headers,
            ) as response:
                body = await response.read()
                if response.status != 200:
                    raise self._error(response.status, response.headers, body)
                if not body:
                    raise BreezeBlueError("Breeze Blue 返回了空音频。", status=200)
                return body, response.headers.get("history-item-id")
        except BreezeBlueError:
            raise
        except asyncio.TimeoutError as exc:
            raise BreezeBlueError("请求 Breeze Blue 超时，请稍后重试。") from exc
        except aiohttp.ClientError as exc:
            raise BreezeBlueError(f"无法连接 Breeze Blue：{exc}") from exc

    async def list_voices(
        self,
        *,
        search: str = "",
        language_code: str = "",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Return the parsed ``VoiceListResponse`` JSON object."""
        params: dict[str, Any] = {"page_size": max(1, min(limit, 100))}
        if search:
            params["search"] = search
        if language_code:
            params["language_code"] = language_code

        url = f"{self.base_url}/v1/voices"
        headers = {**self._headers, "accept": "application/json"}
        try:
            async with self._session.get(
                url, params=params, headers=headers
            ) as response:
                body = await response.read()
                if response.status != 200:
                    raise self._error(response.status, response.headers, body)
                data = json.loads(body.decode("utf-8"))
                if not isinstance(data, dict):
                    raise BreezeBlueError("Breeze Blue 返回了无法解析的语音列表。")
                return data
        except BreezeBlueError:
            raise
        except asyncio.TimeoutError as exc:
            raise BreezeBlueError("请求 Breeze Blue 超时，请稍后重试。") from exc
        except aiohttp.ClientError as exc:
            raise BreezeBlueError(f"无法连接 Breeze Blue：{exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BreezeBlueError("Breeze Blue 返回了无法解析的响应。") from exc

    @staticmethod
    def _error(
        status: int,
        headers: Any,
        body: bytes,
    ) -> BreezeBlueError:
        """Turn an error response into a readable exception."""
        code: str | None = None
        detail = ""
        try:
            data = json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None

        if isinstance(data, dict):
            raw_code = data.get("code")
            if raw_code:
                code = str(raw_code)
            fragments: list[str] = []
            for key in ("error", "detail", "message"):
                value = data.get(key)
                if not value:
                    continue
                if isinstance(value, str):
                    fragments.append(value)
                else:
                    fragments.append(json.dumps(value, ensure_ascii=False))
            detail = " - ".join(dict.fromkeys(fragments))
        elif body:
            detail = body.decode("utf-8", "ignore")

        detail = _short(detail.strip(), 300)
        message = f"HTTP {status}"
        if code:
            message += f" ({code})"
        if detail:
            message += f"：{detail}"

        retry_after: float | None = None
        raw_retry = headers.get("Retry-After") if headers else None
        if raw_retry:
            try:
                retry_after = float(raw_retry)
            except (TypeError, ValueError):
                retry_after = None
        return BreezeBlueError(
            message,
            status=status,
            code=code,
            retry_after=retry_after,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def split_text(text: str, limit: int) -> list[str]:
    """Split text into chunks of at most ``limit`` characters.

    Splits preferably after sentence punctuation or a newline. A single
    over-long sentence is hard-split so no request exceeds the API limit.
    """
    limit = max(1, limit)
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buffer = ""
    for part in _SENTENCE_END_RE.split(text):
        if not part:
            continue

        if len(buffer) + len(part) <= limit:
            buffer += part
            continue

        if buffer.strip():
            chunks.append(buffer.strip())
            buffer = ""

        # The part itself may still be too long (e.g. no punctuation at all).
        while len(part) > limit:
            chunks.append(part[:limit].strip())
            part = part[limit:]
        buffer = part

    if buffer.strip():
        chunks.append(buffer.strip())
    return [chunk for chunk in chunks if chunk]


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "开", "启用"}
    return bool(value)


# ---------------------------------------------------------------------------
# AstrBot plugin
# ---------------------------------------------------------------------------


@register(
    PLUGIN_NAME,
    "Qingfeng-gt",
    "使用 Breeze Blue（Breeze TTS 2）为 AstrBot 提供文字转语音。",
    "v1.2.0",
)
class BreezeBlueTTSPlugin(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context)
        self.config: Any = config or {}
        self._session: aiohttp.ClientSession | None = None
        self._client: BreezeBlueClient | None = None
        self._session_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(self._max_concurrent())
        self._silk_fallback_warned = False
        self._state: dict[str, dict[str, Any]] = {"voices": {}}
        self._state_path = (
            Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME / "state.json"
        )

        if request is not None and hasattr(context, "register_web_api"):
            context.register_web_api(
                f"/{PLUGIN_NAME}/voices",
                self.api_list_voices,
                ["GET"],
                "List Breeze Blue voices",
            )
            context.register_web_api(
                f"/{PLUGIN_NAME}/voices/select",
                self.api_select_voice,
                ["POST"],
                "Select the default Breeze Blue voice",
            )

    # -- lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        self._load_state()

    async def terminate(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        self._client = None

    # -- config helpers ----------------------------------------------------

    def _get(self, key: str, default: Any = None) -> Any:
        try:
            value = self.config.get(key, default)
        except AttributeError:
            value = default
        return default if value is None else value

    def _get_int(self, key: str, default: int, low: int, high: int) -> int:
        return _clamp_int(self._get(key, default), default, low, high)

    def _get_float(self, key: str, default: float, low: float, high: float) -> float:
        return _clamp_float(self._get(key, default), default, low, high)

    def _get_bool(self, key: str, default: bool) -> bool:
        return _truthy(self._get(key, default))

    def _api_key(self) -> str:
        configured = str(self._get("api_key", "") or "").strip()
        return configured or os.environ.get("BREEZE_API_KEY", "").strip()

    def _api_base(self) -> str:
        base = str(self._get("api_base", DEFAULT_BASE_URL) or "").strip()
        return (base or DEFAULT_BASE_URL).rstrip("/")

    def _timeout(self) -> int:
        return self._get_int("timeout", 60, 5, 300)

    def _max_chars(self) -> int:
        return self._get_int("max_chars", 1000, 50, MAX_API_CHARS)

    def _max_segments(self) -> int:
        return self._get_int("max_segments", 3, 1, 10)

    def _max_concurrent(self) -> int:
        return self._get_int("max_concurrent", 2, 1, 8)

    def _voice_list_limit(self) -> int:
        return self._get_int("voice_list_limit", 10, 1, 20)

    def _command_admin_only(self) -> bool:
        return self._get_bool("command_admin_only", False)

    def _session_settings_admin_only(self) -> bool:
        return self._get_bool("session_settings_admin_only", True)

    def _output_format(self) -> str:
        value = str(self._get("output_format", "mp3") or "").strip().lower()
        if not _OUTPUT_FORMAT_RE.match(value):
            logger.warning("无效的 Breeze Blue output_format=%r，已回退到 mp3", value)
            return "mp3"
        return value

    def _napcat_audio_mode(self) -> str:
        value = (
            str(self._get("napcat_audio_mode", DEFAULT_NAPCAT_AUDIO_MODE) or "")
            .strip()
            .lower()
        )
        if value not in NAPCAT_AUDIO_MODES:
            logger.warning(
                "无效的 napcat_audio_mode=%r，已回退到 %s",
                value,
                DEFAULT_NAPCAT_AUDIO_MODE,
            )
            return DEFAULT_NAPCAT_AUDIO_MODE
        return value

    def _output_format_for_platform(self, platform: str) -> str:
        """NapCat SILK/WAV modes need a PCM WAV source, so ask Breeze for one."""
        if platform == "aiocqhttp" and self._napcat_audio_mode() in {"silk", "wav"}:
            return "wav"
        return self._output_format()

    def _language_code(self) -> str | None:
        value = str(self._get("language_code", "") or "").strip()
        if not value:
            return None
        if not _LANGUAGE_CODE_RE.match(value):
            logger.warning(
                "无效的 language_code=%r，必须是 ISO 639-1 两字母代码", value
            )
            return None
        return value.lower()

    def _model_id(self) -> str | None:
        value = str(self._get("model_id", "") or "").strip()
        return value or None

    def _instructions(self) -> str | None:
        value = str(self._get("instructions", "") or "").strip()
        return value or None

    # -- persisted per-session state --------------------------------------

    def _load_state(self) -> None:
        raw: dict[str, Any] = {"voices": {}}
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                voices = data.get("voices")
                if isinstance(voices, dict):
                    raw["voices"] = {
                        str(k): str(v)
                        for k, v in voices.items()
                        if isinstance(v, str) and v
                    }
        except FileNotFoundError:
            pass
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("读取 Breeze Blue 插件状态失败：%s", exc)
        self._state = raw

    async def _save_state(self) -> None:
        try:
            async with self._state_lock:
                payload = json.dumps(self._state, ensure_ascii=False, indent=2)
                await asyncio.to_thread(self._write_state_sync, payload)
        except OSError as exc:
            logger.warning("保存 Breeze Blue 插件状态失败：%s", exc)

    def _write_state_sync(self, payload: str) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._state_path.with_suffix(".json.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, self._state_path)

    def _session_voice_override(self, umo: str) -> str | None:
        value = self._state.get("voices", {}).get(umo)
        return str(value) if value else None

    def _effective_voice(self, umo: str) -> str:
        override = self._session_voice_override(umo)
        configured = str(self._get("voice_id", "") or "").strip()
        return override or configured or DEFAULT_VOICE_ID

    # -- client ------------------------------------------------------------

    async def _get_client(self) -> BreezeBlueClient:
        api_key = self._api_key()
        if self._client is not None and self._client.api_key == api_key:
            return self._client

        async with self._session_lock:
            if self._client is not None and self._client.api_key == api_key:
                return self._client
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self._timeout())
                )
            self._client = BreezeBlueClient(
                api_key=api_key,
                base_url=self._api_base(),
                session=self._session,
            )
            return self._client

    def _make_request(
        self,
        text: str,
        umo: str,
        platform: str = "",
        instructions: str | None = None,
    ) -> TtsRequest:
        if instructions is None:
            effective_instructions = self._instructions()
        else:
            effective_instructions = instructions.strip() or None
        return TtsRequest(
            text=text,
            voice_id=self._effective_voice(umo),
            model_id=self._model_id(),
            language_code=self._language_code(),
            instructions=effective_instructions,
            output_format=self._output_format_for_platform(platform),
            speed=self._get_float("speed", 1.0, 0.5, 2.0),
            volume=self._get_float("volume", 1.0, 0.01, 2.0),
            guidance_scale=self._get_float("guidance_scale", 1.0, 1.0, 10.0),
            use_speaker_boost=self._get_bool("use_speaker_boost", False),
        )

    async def _synthesize(
        self,
        text: str,
        umo: str,
        platform: str = "",
        instructions: str | None = None,
    ) -> bytes:
        client = await self._get_client()
        tts_request = self._make_request(text, umo, platform, instructions)
        async with self._semaphore:
            audio, history_id = await client.synthesize(tts_request)
        if history_id:
            logger.debug("Breeze Blue 合成成功，history_item_id=%s", history_id)
        return audio

    async def _make_record(
        self,
        audio: bytes,
        text: str,
        platform: str = "",
    ) -> Record:
        """Build a Record, using a NapCat-safe payload on aiocqhttp."""
        if platform == "aiocqhttp":
            payload, passthrough = await self._prepare_napcat_audio(audio)
            record_cls = _NapCatPassthroughRecord if passthrough else Record
            return record_cls(
                file=f"base64://{base64.b64encode(payload).decode('ascii')}",
                text=text,
            )
        return Record(
            file=f"base64://{base64.b64encode(audio).decode('ascii')}",
            text=text,
        )

    async def _prepare_napcat_audio(self, audio: bytes) -> tuple[bytes, bool]:
        """Return ``(payload, must_pass_through)`` for NapCat.

        * ``silk``   - encode Tencent SILK ourselves and bypass NapCat's
                       WAV -> SILK conversion (the default).
        * ``wav``    - send Breeze's 24 kHz PCM WAV directly and let NapCat
                       convert it.
        * ``native`` - send Breeze's configured format (usually MP3) unchanged.
        """
        mode = self._napcat_audio_mode()
        if mode == "native":
            return audio, True
        if mode == "wav":
            return audio, False

        try:
            silk = await self._wav_bytes_to_tencent_silk(audio)
            return silk, True
        except Exception as exc:
            if not getattr(self, "_silk_fallback_warned", False):
                logger.warning(
                    "NapCat SILK 编码失败，已回退为直接发送音频"
                    "（后续同类错误仅记 debug）：%s",
                    exc,
                )
                self._silk_fallback_warned = True
            else:
                logger.debug("NapCat SILK 编码失败，回退为直接发送音频：%s", exc)
            return audio, True

    async def _wav_bytes_to_tencent_silk(self, wav_bytes: bytes) -> bytes:
        """Encode PCM WAV bytes to the 0x02-prefixed Tencent SILK NapCat uses."""
        from astrbot.core.utils.tencent_record_helper import wav_to_tencent_silk

        temp_dir = Path(get_astrbot_temp_path())
        await asyncio.to_thread(temp_dir.mkdir, parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        wav_path = temp_dir / f"breezeblue_tts_{token}.wav"
        silk_path = temp_dir / f"breezeblue_tts_{token}.silk"
        try:
            await asyncio.to_thread(wav_path.write_bytes, wav_bytes)
            await wav_to_tencent_silk(str(wav_path), str(silk_path))
            silk = await asyncio.to_thread(silk_path.read_bytes)
            if not silk:
                raise ValueError("SILK 编码结果为空")
            if b"#!SILK" not in silk[:10]:
                raise ValueError("SILK 编码结果缺少 #!SILK 文件头")
            logger.debug("NapCat SILK 编码成功：%d bytes", len(silk))
            return silk
        finally:
            for path in (wav_path, silk_path):
                try:
                    await asyncio.to_thread(path.unlink, missing_ok=True)
                except OSError:
                    logger.debug("清理临时音频失败：%s", path)

    def _missing_api_key_message(self) -> str:
        return (
            "尚未配置 Breeze Blue API Key。\n"
            "请在 AstrBot WebUI 的插件配置中填写 api_key，"
            "或设置环境变量 BREEZE_API_KEY 后重载插件。\n"
            "API Key 可在 Breeze Blue Developer Console 创建。"
        )

    def _friendly_error(self, exc: BreezeBlueError) -> str:
        if exc.status == 401:
            return "Breeze Blue 认证失败（401）：请检查 api_key 是否正确、是否已失效。"
        if exc.status == 403:
            return f"Breeze Blue 拒绝访问（403）：{_short(str(exc), 200)}"
        if exc.status == 404:
            return (
                f"Breeze Blue 找不到资源（404）：请确认 voice_id 是否存在。\n"
                f"{_short(str(exc), 200)}"
            )
        if exc.status == 429:
            wait = (
                f"，请在约 {int(exc.retry_after)} 秒后重试" if exc.retry_after else ""
            )
            return f"Breeze Blue 请求过于频繁（429）{wait}。"
        if exc.status in (503, 504):
            return f"Breeze Blue 服务暂时不可用（{exc.status}），请稍后重试。"
        if exc.status == 422:
            return f"Breeze Blue 参数校验失败（422）：{_short(str(exc), 250)}"
        return f"Breeze Blue 合成失败：{_short(str(exc), 300)}"

    # -- command helpers ---------------------------------------------------

    @staticmethod
    def _args(event: AstrMessageEvent) -> str:
        raw = event.get_message_str().strip()
        return _COMMAND_ARG_RE.sub("", raw, count=1).strip()

    @staticmethod
    def _quoted_text(event: AstrMessageEvent) -> str:
        for component in event.get_messages():
            if isinstance(component, Reply):
                text = getattr(component, "message_str", "") or getattr(
                    component, "text", ""
                )
                if text:
                    return str(text).strip()
        return ""

    def _can_change_session_settings(self, event: AstrMessageEvent) -> bool:
        if not self._session_settings_admin_only():
            return True
        if event.is_private_chat():
            return True
        return event.is_admin()

    # -- commands ----------------------------------------------------------

    @filter.command("tts", alias={"语音"})
    async def tts_command(self, event: AstrMessageEvent):
        """将文本合成为语音。用法：/tts <文本>，也可以引用一条消息后发送 /tts。"""
        if self._command_admin_only() and not event.is_admin():
            yield event.plain_result("该指令仅限 AstrBot 管理员使用。")
            return

        if not self._api_key():
            yield event.plain_result(self._missing_api_key_message())
            return

        text = self._args(event) or self._quoted_text(event)
        if not text:
            yield event.plain_result(
                "用法：/tts <要合成的文本>\n"
                "也可以引用一条消息后发送 /tts，将合成被引用的文本。\n"
                "查看音色：/tts_voice list"
            )
            return

        max_chars = self._max_chars()
        max_segments = self._max_segments()
        segments = split_text(text, max_chars)
        if not segments:
            yield event.plain_result("没有可合成的文本。")
            return
        if len(segments) > max_segments:
            yield event.plain_result(
                f"文本过长：共 {len(text)} 字，按每段 {max_chars} 字需要 "
                f"{len(segments)} 段，超过上限 {max_segments} 段。请缩短文本。"
            )
            return

        umo = event.unified_msg_origin
        records: list[Record] = []
        try:
            for segment in segments:
                audio = await self._synthesize(
                    segment,
                    umo,
                    event.get_platform_name(),
                )
                records.append(
                    await self._make_record(audio, segment, event.get_platform_name())
                )
        except BreezeBlueError as exc:
            logger.warning("Breeze Blue /tts 失败：%s", exc)
            yield event.plain_result(self._friendly_error(exc))
            return
        except Exception:
            logger.exception("Breeze Blue /tts 出现未预期错误")
            yield event.plain_result("语音合成失败，请查看 AstrBot 日志获取详情。")
            return

        chain: list[Any] = []
        if self._get_bool("tts_send_text", False):
            chain.append(Plain(text))
        chain.extend(records)
        yield event.chain_result(chain)

    @filter.command("tts_voice", alias={"语音音色"})
    async def tts_voice_command(self, event: AstrMessageEvent):
        """查看或切换音色。用法：/tts_voice [list|use <voice_id>|show|reset]。"""
        args = self._args(event)
        parts = args.split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub in {"list", "ls", "search", "搜索", "列表"}:
            if not self._api_key():
                yield event.plain_result(self._missing_api_key_message())
                return
            yield event.plain_result(await self._voice_list_text(rest))
            return

        if sub in {"use", "set", "使用", "切换"}:
            if not self._can_change_session_settings(event):
                yield event.plain_result("群聊中仅 AstrBot 管理员可以切换本会话音色。")
                return
            voice_id = rest.strip()
            if not voice_id or not _VOICE_ID_RE.match(voice_id):
                yield event.plain_result(
                    "用法：/tts_voice use <voice_id>\n"
                    "voice_id 形如 voc_xeh3w54cqvnp，可通过 /tts_voice list 查看。"
                )
                return
            umo = event.unified_msg_origin
            self._state.setdefault("voices", {})[umo] = voice_id
            await self._save_state()
            yield event.plain_result(f"已将会话音色切换为：{voice_id}")
            return

        if sub in {"show", "current", "当前"}:
            umo = event.unified_msg_origin
            override = self._session_voice_override(umo)
            effective = self._effective_voice(umo)
            configured = str(self._get("voice_id", "") or "").strip() or "（未设置）"
            source = "本会话设置" if override else "插件配置"
            yield event.plain_result(
                f"当前音色：{effective}\n"
                f"来源：{source}\n"
                f"插件默认音色：{configured}\n"
                f"模型：{self._model_id() or '自动选择'}\n"
                f"NapCat 语音格式：{self._napcat_audio_mode()}"
            )
            return

        if sub in {"reset", "clear", "重置"}:
            if not self._can_change_session_settings(event):
                yield event.plain_result("群聊中仅 AstrBot 管理员可以重置本会话音色。")
                return
            umo = event.unified_msg_origin
            self._state.setdefault("voices", {}).pop(umo, None)
            await self._save_state()
            yield event.plain_result(
                f"已恢复使用插件默认音色：{self._effective_voice(umo)}"
            )
            return

        yield event.plain_result(
            "用法：\n"
            "/tts_voice list [关键词] — 搜索可用音色\n"
            "/tts_voice use <voice_id> — 切换本会话音色\n"
            "/tts_voice show — 查看当前音色\n"
            "/tts_voice reset — 恢复插件默认音色"
        )

    # -- LLM tool ----------------------------------------------------------

    @filter.llm_tool(name="breeze_blue_tts")
    async def breeze_blue_tts(
        self,
        event: AstrMessageEvent,
        text: str = "",
        instructions: str = "",
    ) -> str | None:
        """将文本合成为 Breeze Blue 语音并发送到当前会话。

        当用户明确要求“发语音/语音回复/读出来/朗读”，或你判断用声音表达更合适时调用。
        每次调用应同时给出 text 和 instructions；instructions 由你根据上下文生成，
        描述这句话应有的情绪和语气，而不是照抄用户原话。
        调用成功后语音会自动发送，不需要再重复朗读同一段文字。

        Args:
            text(string): 要朗读的最终文本，只包含角色要说的话，不要包含舞台说明。
            instructions(string): 与 text 同语言的语气/情绪/语速/风格指令；无要求留空。
        """
        if not self._api_key():
            return self._missing_api_key_message()

        text = (text or "").strip()
        if not text:
            return "text 不能为空，请提供要朗读的文本。"

        segments = split_text(text, self._max_chars())
        if not segments:
            return "没有可合成的文本。"
        if len(segments) > self._max_segments():
            return (
                f"文本过长：共 {len(text)} 字，按每段 {self._max_chars()} 字需要 "
                f"{len(segments)} 段，超过上限 {self._max_segments()} 段。"
                "请缩短后重试。"
            )

        umo = event.unified_msg_origin
        platform = event.get_platform_name()
        records: list[Record] = []
        try:
            for segment in segments:
                audio = await self._synthesize(
                    segment,
                    umo,
                    platform,
                    instructions=instructions.strip() or None,
                )
                records.append(await self._make_record(audio, segment, platform))
            await event.send(event.chain_result(records))
        except BreezeBlueError as exc:
            logger.warning("Breeze Blue 工具调用失败：%s", exc)
            return self._friendly_error(exc)
        except Exception:
            logger.exception("Breeze Blue 工具调用出现未预期错误")
            return "语音合成或发送失败，请查看 AstrBot 日志获取详情。"
        return None

    # -- WebUI voice picker ------------------------------------------------

    async def api_list_voices(self):
        if request is None or json_response is None or error_response is None:
            raise RuntimeError("AstrBot web API is unavailable")
        if not self._api_key():
            return error_response("尚未配置 Breeze Blue API Key", status_code=400)

        search = str(request.query.get("search", "") or "").strip()
        language_code = str(request.query.get("language_code", "") or "").strip()
        if language_code and not _LANGUAGE_CODE_RE.match(language_code):
            language_code = ""

        try:
            client = await self._get_client()
            data = await client.list_voices(
                search=search,
                language_code=language_code,
                limit=50,
            )
        except BreezeBlueError as exc:
            logger.warning("Breeze Blue 音色视图获取失败：%s", exc)
            return error_response(f"获取音色失败：{exc}", status_code=502)
        except Exception:
            logger.exception("Breeze Blue 音色视图出现未预期错误")
            return error_response("获取音色失败，请查看 AstrBot 日志", status_code=500)

        voices: list[dict[str, Any]] = []
        for voice in data.get("voices") or []:
            if not isinstance(voice, dict):
                continue
            voices.append(
                {
                    "voice_id": str(voice.get("voice_id") or ""),
                    "name": str(voice.get("name") or "未命名"),
                    "language_code": voice.get("language_code"),
                    "gender": voice.get("gender"),
                    "age": voice.get("age"),
                    "accent": voice.get("accent"),
                    "tone": voice.get("tone") or [],
                }
            )

        return json_response(
            {
                "voices": voices,
                "total": data.get("total", len(voices)),
                "has_more": bool(data.get("has_more")),
                "selected_voice_id": self._effective_voice(""),
            }
        )

    async def api_select_voice(self):
        if request is None or json_response is None or error_response is None:
            raise RuntimeError("AstrBot web API is unavailable")

        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        voice_id = str(payload.get("voice_id") or "").strip()
        if not _VOICE_ID_RE.match(voice_id):
            return error_response("voice_id 不合法", status_code=400)

        try:
            self.config["voice_id"] = voice_id
            save = getattr(self.config, "save_config", None)
            if callable(save):
                save()
        except Exception:
            logger.exception("保存 Breeze Blue 默认音色失败")
            return error_response("保存配置失败，请查看 AstrBot 日志", status_code=500)

        logger.info("Breeze Blue 默认音色已更新为 %s", voice_id)
        return json_response({"saved": True, "voice_id": voice_id})

    # -- voice listing -----------------------------------------------------

    async def _voice_list_text(self, search: str) -> str:
        limit = self._voice_list_limit()
        language_code = self._language_code() or ""
        try:
            client = await self._get_client()
            data = await client.list_voices(
                search=search,
                language_code=language_code,
                limit=limit,
            )
            voices = data.get("voices") or []
            if not voices and language_code:
                # Search terms often refer to voices in another language.
                data = await client.list_voices(search=search, limit=limit)
                voices = data.get("voices") or []
        except BreezeBlueError as exc:
            logger.warning("Breeze Blue 音色列表失败：%s", exc)
            return self._friendly_error(exc)
        except Exception:
            logger.exception("获取 Breeze Blue 音色列表时出现未预期错误")
            return "获取音色列表失败，请查看 AstrBot 日志获取详情。"

        if not isinstance(voices, list) or not voices:
            suffix = f"（关键词：{search}）" if search else ""
            return f"没有找到可用音色{suffix}。"

        total = data.get("total")
        if isinstance(total, int) and total > len(voices):
            header = f"找到 {total} 个音色，显示前 {len(voices)} 个："
        else:
            header = f"找到 {len(voices)} 个音色，显示前 {min(len(voices), limit)} 个："
        lines = [header]
        for index, voice in enumerate(voices[:limit], start=1):
            if not isinstance(voice, dict):
                continue
            name = _short(str(voice.get("name") or "未命名"), 40)
            voice_id = str(voice.get("voice_id") or "")
            meta: list[str] = []
            if voice.get("language_code"):
                meta.append(str(voice["language_code"]))
            if voice.get("gender"):
                meta.append(str(voice["gender"]))
            if voice.get("age"):
                meta.append(str(voice["age"]))
            line = f"{index}. {name} — {voice_id}"
            if meta:
                line += "\n   " + " ｜ ".join(meta)
            lines.append(line)

        lines.append("使用 /tts_voice use <voice_id> 切换本会话音色。")
        return "\n".join(lines)
