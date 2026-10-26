# Breeze Blue 语音（AstrBot 插件）

[![CI](https://github.com/Qingfeng-gt/astrbot_plugin_breezeblue_tts/actions/workflows/ci.yml/badge.svg)](https://github.com/Qingfeng-gt/astrbot_plugin_breezeblue_tts/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

把 [Breeze Blue](https://breezeblue.ai) 的文字转语音（Breeze TTS 2）接入 AstrBot。插件直接调用 Breeze Blue Developer API，不需要额外安装 SDK。

> 当前实现是 TTS 接入，不包含语音识别（STT）。项目使用 MIT 许可证。

## 功能

- `/tts <文本>`：合成为语音消息；也可以引用一条消息后发送 `/tts`。
- `/tts_voice list [关键词]`：搜索账号可用的音色。
- `/tts_voice use <voice_id>`：为当前会话切换音色（持久化保存）。
- `/tts_voice show` / `/tts_voice reset`：查看或恢复默认音色。
- `/tts_auto on|off|status`：按会话开启/关闭“AI 回复自动转语音”。
- 自动语音：AI 的纯文本回复可自动替换为语音；可配置是否保留文字。
- NapCat/QQ：默认直接生成腾讯 SILK 语音，绕过 NapCat 的 WAV→SILK 二次转换，避免 QQ 语音杂音。
- 长文本按标点分段合成（受 Breeze Blue 每请求 1000/2000 字符限制）。
- 完整的错误处理：401、403、404、422、429（含 Retry-After）、503/504。

## 安装

1. 将本目录放到 AstrBot 的插件目录：

   ```text
   AstrBot/data/plugins/astrbot_plugin_breezeblue_tts/
   ```

   也可以把整个目录打包为 zip，在 AstrBot WebUI 的“插件”页安装；或者直接克隆仓库：

   ```bash
   cd AstrBot/data/plugins
   git clone https://github.com/Qingfeng-gt/astrbot_plugin_breezeblue_tts
   ```

2. 在 AstrBot WebUI 的“插件”页重载插件（或重启 AstrBot）。

3. 打开插件配置，填写 **Breeze Blue API Key**（形如 `brz_...`）。API Key 在 Breeze Blue Developer Console 的 API keys 页面创建。

   - 也可以通过环境变量提供：`BREEZE_API_KEY=brz_...`。配置项优先。
   - 首次使用建议先执行 `/tts_voice list` 确认音色可用。

4. 发送 `/tts 你好，这是一段测试语音`。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/tts <文本>` | 合成语音。参数为空时会读取被引用消息的文本。 |
| `/tts_voice list [关键词]` | 搜索可用音色，显示名称、`voice_id`、语言、性别、年龄。 |
| `/tts_voice use <voice_id>` | 当前会话使用指定音色，保存到 `data/plugin_data`。 |
| `/tts_voice show` | 显示当前音色、来源和模型。 |
| `/tts_voice reset` | 删除本会话音色覆盖，恢复插件默认音色。 |
| `/tts_auto on` | 开启本会话的 AI 回复自动语音。 |
| `/tts_auto off` | 关闭本会话的 AI 回复自动语音。 |
| `/tts_auto status` | 查看当前状态和来源（会话设置/插件默认）。 |

默认情况下，群聊里只有 AstrBot 管理员能修改会话设置（`session_settings_admin_only`），私聊不受限制。

## 配置

所有配置都可以在 WebUI 中修改，修改后重载插件生效。

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `api_key` | string(secret) | 空 | Breeze Blue API Key，留空时读取环境变量 `BREEZE_API_KEY`。 |
| `api_base` | string | `https://api.breeze.blue` | API 地址，一般无需修改。 |
| `voice_id` | string | `voc_xeh3w54cqvnp` | 默认音色，示例值来自 Breeze Blue 快速开始。 |
| `model_id` | string | 空 | 可选 `breeze-tts-2` / `breeze-tts-2-multilingual`，留空自动选择。 |
| `language_code` | string | `zh` | ISO 639-1 两字母代码，留空自动。 |
| `output_format` | string | `mp3` | `mp3`、`wav`、`wav_48000`、`opus`、`aac`、`flac`、`pcm` 等；非 NapCat 平台使用。 |
| `napcat_audio_mode` | string | `silk` | NapCat 专用：`silk`（推荐，插件直接生成腾讯 SILK）、`wav`（24kHz PCM，由 NapCat 转换）、`native`（Breeze 原始格式，由 NapCat 转换）。 |
| `instructions` | text | 空 | 表演指令，例如“用温柔、平静的语气说”。 |
| `speed` | float | `1.0` | 0.5–2.0。 |
| `volume` | float | `1.0` | 0.01–2.0。 |
| `guidance_scale` | float | `1.0` | 1–10，表现力引导强度。 |
| `use_speaker_boost` | bool | `false` | 增强说话人相似度。 |
| `timeout` | int | `60` | HTTP 请求超时（秒）。 |
| `max_chars` | int | `1000` | 单段字符上限（Breeze Blue 默认 1000，获批账户可到 2000）。 |
| `max_segments` | int | `3` | 长文本最大分段数，超过则拒绝。 |
| `max_concurrent` | int | `2` | 同时进行的合成请求数。 |
| `tts_send_text` | bool | `false` | `/tts` 是否同时发送原文。 |
| `auto_tts` | bool | `false` | 所有会话默认开启自动语音。 |
| `auto_tts_only_llm` | bool | `true` | 只转换 LLM 生成的结果。 |
| `auto_tts_keep_text` | bool | `false` | 自动语音时是否保留文字消息。 |
| `session_settings_admin_only` | bool | `true` | 群聊中仅管理员可改会话设置。 |
| `command_admin_only` | bool | `false` | `/tts` 仅限管理员使用，避免普通用户消耗额度。 |
| `voice_list_limit` | int | `10` | `/tts_voice list` 显示条数。 |

## NapCat / QQ 语音

AstrBot 的 `aiocqhttp` 适配器会把 `Record` 统一转成 WAV，再交给 NapCat；NapCat 发送 QQ 语音时还要把 WAV 转成腾讯 SILK。这个二次转换是 QQ 语音出现杂音、电流声的高发环节。

插件对 `aiocqhttp`（NapCat）默认使用 `napcat_audio_mode=silk`：

1. 向 Breeze Blue 请求原生 24kHz PCM WAV；
2. 用 AstrBot 自带的 `wav_to_tencent_silk`（pysilk）生成 QQ 兼容的 `0x02#!SILK_V3` 音频；
3. 通过一个透传 `Record` 子类把 SILK 直接交给 NapCat，NapCat 检测到已经是 SILK 后不会再转码。

如果仍然有问题，可以在插件配置里依次尝试：

- `silk`：推荐，直接发送 SILK，绕过 NapCat 二次转码。
- `wav`：发送 24kHz PCM WAV，由 NapCat 转换。
- `native`：发送 Breeze 原始格式（通常是 MP3），由 NapCat 转换。

同时建议：

- 升级 **NapCat ≥ v4.18.36**，该版本修复了音频格式识别、SILK 时长和重采样尾帧处理。
- 只启用一套 TTS 方案，避免 AstrBot 自带 TTS 与其他 TTS 插件同时改写回复。
- 流式回复不会被本插件自动转语音；如需自动语音，请关闭流式输出。

## 自动语音的边界

为了不破坏消息内容、也避免意外扣费，自动语音只在以下条件全部满足时触发：

1. 本会话的自动语音已开启；
2. 结果是 AI（LLM）生成的，且不是流式结果；
3. 消息链中只有纯文本，没有图片、At、语音等组件；
4. 文本不为空且不超过 `max_chars`；
5. 已经配置了 API Key。

否则保持原文字回复。转换失败时也会自动回退为原文字，并在 AstrBot 日志中记录原因。流式输出不会被转换。

自动语音会把每条符合条件的 AI 回复送到 Breeze Blue，产生相应费用。建议按需开启，必要时把 `/tts` 设为仅管理员可用。

## Breeze Blue 接口说明

插件使用同步 TTS 接口：

```http
POST https://api.breeze.blue/v1/text-to-speech/{voice_id}?output_format=mp3&delivery=sync
xi-api-key: brz_...
Content-Type: application/json

{
  "text": "要合成的文本",
  "model_id": "breeze-tts-2",
  "language_code": "zh",
  "instructions": "可选，表演指令",
  "voice_settings": {
    "speed": 1.0,
    "volume": 1.0,
    "guidance_scale": 1.0,
    "use_speaker_boost": false
  }
}
```

- 成功时返回音频二进制流，响应头 `history-item-id` 为生成记录 ID。未显式修改的 `voice_settings` 字段会被插件省略。
- 音色列表：`GET https://api.breeze.blue/v1/voices`，支持 `search`、`language_code`、`page_size` 等参数。
- 默认每请求最多 1000 字符；超过时会被拒绝而不是截断。中文非流式场景下，Breeze Blue 会对超过 500 字符的文本在服务端分段（最多 5 段），插件则在发送前按 `max_chars` 主动分段。
- 429/503/504 会带 `Retry-After` 响应头。

更多细节见 [Breeze Blue 快速开始](https://docs.breezeblue.ai/quickstart)、[TTS 指南](https://docs.breezeblue.ai/guides/text-to-speech) 和 [转换端点参考](https://docs.breezeblue.ai/api-reference/text-to-speech/convert-text-to-speech)。

## 数据与隐私

- 合成的文本会发送到 Breeze Blue API。
- API Key 保存在 AstrBot 插件配置中；配置项使用 `secret` 仅做界面遮罩，不会加密文件本身，请注意文件权限。
- 会话级设置保存在：

  ```text
  AstrBot/data/plugin_data/astrbot_plugin_breezeblue_tts/state.json
  ```

  内容只有会话 UMO 到音色/自动语音开关的映射，不包含聊天内容。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 401 | API Key 错误或已失效，重新在 Developer Console 创建。 |
| 403 | Key 没有权限使用该音色/模型，换一个音色或检查账户权限。 |
| 404 | `voice_id` 不存在；用 `/tts_voice list` 重新选择。 |
| 422 | 参数不合法，常见原因：`language_code` 不是两字母、模型与语言不兼容、文本超过长度限制。 |
| 429 | 触发限流，按 `Retry-After` 等待后重试，或降低 `max_concurrent`。 |
| QQ 语音是杂音/电流声 | 确认 `napcat_audio_mode=silk`；升级 NapCat ≥ v4.18.36；关闭其他 TTS 插件；仍不行依次尝试 `wav`、`native`。 |
| NapCat 发送语音失败或没有声音 | 改用 `wav` 或 `native`，检查 AstrBot/NapCat 日志中的 ffmpeg、ntsilk、pysilk 错误；确认 NapCat 的语音功能可用。 |
| 语音发送失败且日志提到 ffmpeg | 安装 ffmpeg 并加入 PATH；NapCat 的 `silk` 模式本身不需要系统 ffmpeg，但 `wav`/`native` 回退可能需要。 |
| 自动语音不触发 | 检查 `/tts_auto status`、是否流式输出、回复是否含图片/At、文本是否超过 `max_chars`。 |

## 开发与测试

插件附带了离线测试：使用假的 `astrbot` 模块和本地 aiohttp 测试服务器，覆盖文本分段、请求体、HTTP 请求/响应、错误映射、指令和自动语音流程，不需要 AstrBot 实例或真实 API Key。

```bash
uv run --python 3.13 --with aiohttp python tests/test_plugin_smoke.py
```

代码风格使用 ruff（配置见 `pyproject.toml`）：

```bash
uvx ruff check main.py tests
uvx ruff format main.py tests
```

## 后续可扩展

- 用 Breeze Blue 的 Realtime WebSocket（`breeze-tts-2`）做边生成边播放的语音流。
- 增加 voice clone / voice design 的管理指令。
- 如果你的场景需要语音识别，Breeze Blue 快速开始目前只覆盖 TTS，需要等官方提供 STT 接口后再接入。

## 与 AstrBot 规范对应

- 插件唯一名以 `astrbot_plugin_` 开头，入口文件为 `main.py`。
- 插件类继承 `Star`，使用 `@filter.command` 注册指令，使用 `@filter.on_decorating_result` 修改发送前的结果。
- 语音消息使用 `astrbot.api.message_components.Record`，由 AstrBot 按平台适配为原生语音。
- 配置通过 `_conf_schema.json` 定义，并在 `__init__` 注入 `AstrBotConfig`。
- 持久化数据写入 `data/plugin_data/`，不写入插件目录。

参考：[AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)、[插件配置](https://docs.astrbot.app/dev/star/guides/plugin-config.html)。

## 许可证

[MIT](LICENSE) © 2026 Qingfeng-gt
