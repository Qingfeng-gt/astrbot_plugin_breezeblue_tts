# Breeze Blue 语音（AstrBot 插件）

[![CI](https://github.com/Qingfeng-gt/astrbot_plugin_breezeblue_tts/actions/workflows/ci.yml/badge.svg)](https://github.com/Qingfeng-gt/astrbot_plugin_breezeblue_tts/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

把 [Breeze Blue](https://breezeblue.ai) 的文字转语音（Breeze TTS 2）接入 AstrBot。插件直接调用 Breeze Blue Developer API，不需要额外安装 SDK。

> 当前实现是 TTS 接入，不包含语音识别（STT）。项目使用 MIT 许可证。

## 功能

- **LLM 工具 `breeze_blue_tts`**：由模型在需要语音时主动调用，不会把所有回复默认转成语音；每次调用同时携带朗读文本和表演指令。
- `/tts <文本>`：手动合成语音；也可以引用一条消息后发送 `/tts`。
- `/tts_voice list [关键词]`：搜索账号可用的音色。
- `/tts_voice use <voice_id>`：为当前会话切换音色（持久化保存）。
- `/tts_voice show` / `/tts_voice reset`：查看或恢复默认音色。
- **WebUI 音色选择视图**：点击“获取音色”，查看名称和 Voice ID，并直接设为全局默认音色。
- NapCat/QQ：默认使用 `wav` 模式，适配当前 QQ 环境；也保留 `silk` / `native` 回退。
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
   - 首次使用建议打开插件详情页的「Breeze Blue 音色」视图，点击“获取音色”并选择一个默认音色。

4. 发送 `/tts 你好，这是一段测试语音`，或在对话中让 AI 调用语音工具。

## 指令

| 指令 / 工具 | 说明 |
| --- | --- |
| `breeze_blue_tts`（LLM 工具） | 模型在需要语音时调用；参数 `text` + `instructions`，合成后直接发送语音。 |
| `/tts <文本>` | 手动合成语音。参数为空时会读取被引用消息的文本。 |
| `/tts_voice list [关键词]` | 搜索可用音色，显示名称、`voice_id`、语言、性别、年龄。 |
| `/tts_voice use <voice_id>` | 当前会话使用指定音色，保存到 `data/plugin_data`。 |
| `/tts_voice show` | 显示当前音色、来源、模型和 NapCat 语音格式。 |
| `/tts_voice reset` | 删除本会话音色覆盖，恢复插件默认音色。 |

默认情况下，群聊里只有 AstrBot 管理员能修改会话设置（`session_settings_admin_only`），私聊不受限制。

## 配置

所有配置都可以在 WebUI 中修改，修改后重载插件生效。

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `api_key` | string(secret) | 空 | Breeze Blue API Key，留空时读取环境变量 `BREEZE_API_KEY`。 |
| `api_base` | string | `https://api.breeze.blue` | API 地址，一般无需修改。 |
| `voice_id` | string | `voc_xeh3w54cqvnp` | 默认音色。推荐在 WebUI 音色视图里获取并选择。 |
| `model_id` | string | 空 | 可选 `breeze-tts-2` / `breeze-tts-2-multilingual`，留空自动选择。 |
| `language_code` | string | `zh` | ISO 639-1 两字母代码，留空自动。 |
| `output_format` | string | `mp3` | `mp3`、`wav`、`wav_48000`、`opus`、`aac`、`flac`、`pcm` 等；非 NapCat 平台使用。 |
| `napcat_audio_mode` | string | `wav` | NapCat 专用：`wav`（推荐，当前 QQ 环境实测可用）、`silk`（插件直接生成腾讯 SILK，部分 NapCat 版本发送不出去）、`native`（Breeze 原始格式，由 NapCat 转换）。 |
| `instructions` | text | 空 | 工具调用没有提供 `instructions` 时使用的默认表演指令。推荐让模型在工具调用中随文本一起生成。 |
| `speed` | float | `1.0` | 0.5–2.0。 |
| `volume` | float | `1.0` | 0.01–2.0。 |
| `guidance_scale` | float | `1.0` | 1–10，表现力引导强度。 |
| `use_speaker_boost` | bool | `false` | 增强说话人相似度。 |
| `timeout` | int | `60` | HTTP 请求超时（秒）。 |
| `max_chars` | int | `1000` | 单段字符上限（Breeze Blue 默认 1000，获批账户可到 2000）。 |
| `max_segments` | int | `3` | 长文本最大分段数，超过则拒绝。 |
| `max_concurrent` | int | `2` | 同时进行的合成请求数。 |
| `tts_send_text` | bool | `false` | `/tts` 是否同时发送原文。 |
| `session_settings_admin_only` | bool | `true` | 群聊中仅管理员可改会话设置。 |
| `command_admin_only` | bool | `false` | `/tts` 仅限管理员使用，避免普通用户消耗额度。 |
| `voice_list_limit` | int | `10` | `/tts_voice list` 显示条数。 |

## NapCat / QQ 语音

AstrBot 的 `aiocqhttp` 适配器会把 `Record` 转成 WAV，再交给 NapCat；NapCat 发送 QQ 语音时还要把 WAV 转成腾讯 SILK。

当前实测结果：

- `wav`：QQ 语音正常。
- `silk`：插件直接生成的 SILK 在当前 NapCat 环境**发送不出去**，因此不再作为默认值。

所以默认配置为 `napcat_audio_mode=wav`：

1. 向 Breeze Blue 请求原生 24kHz PCM WAV；
2. AstrBot 的 aiocqhttp 适配器以 WAV 交给 NapCat；
3. NapCat 转成 SILK 并发送。

可选模式：

- `wav`（默认，推荐）：当前环境实测可用。
- `silk`：插件直接生成 `0x02#!SILK_V3`，绕过 NapCat 二次转换；如果 NapCat 收不到语音就不要使用。
- `native`：发送 Breeze 原始格式（通常是 MP3），由 NapCat 转换。

建议升级 **NapCat ≥ v4.18.36**，并只启用一套 TTS 方案，避免多个 TTS 同时改写回复。NapCat 的 `wav`/`silk` 模式会忽略 `output_format`，其他平台仍使用 `output_format`。

## LLM 语音工具

插件注册名为 `breeze_blue_tts` 的 LLM 工具。AI 在以下场景主动调用：

- 用户明确要求“发语音 / 语音回复 / 读出来 / 朗读”；
- 或模型判断用声音表达更合适。

不会把所有回复默认转成语音。工具参数：

| 参数 | 说明 |
| --- | --- |
| `text` | 要朗读的最终文本 |
| `instructions` | 与 `text` 同语言的表演指令（语气、情绪、语速、风格） |

调用示例（由模型生成）：

```json
{
  "name": "breeze_blue_tts",
  "arguments": {
    "text": "今天辛苦了，早点休息。",
    "instructions": "温柔、放慢语速、带一点笑意地说"
  }
}
```

工具会合成并直接发送语音；调用成功后不需要再重复朗读同一段文字。`instructions` 是随每次文本一起传给 Breeze Blue 的，配置里的 `instructions` 只在工具没有提供时作为默认值。如果模型不调用工具，可以在人格/系统提示词中明确要求“需要语音时使用 `breeze_blue_tts` 工具”，并确认当前模型提供商/Agent 已启用工具调用。

## WebUI 音色选择

AstrBot 的 `_conf_schema.json` 不支持在单个配置项里嵌入自定义按钮，因此插件按 AstrBot 官方“插件可视化视图”规范提供了 `views/voices` 页面：

1. 在 AstrBot 插件页打开本插件详情；
2. 进入「Breeze Blue 音色」视图；
3. 点击 **获取音色**；
4. 列表会显示音色名称、Voice ID、语言、性别、年龄、风格；
5. 点击 **设为默认**，直接写入 `voice_id` 配置。

该视图依赖 AstrBot 的插件视图/Plugin API（约 v4.24.1 之后）。旧版本仍可使用 `/tts_voice list` 和 `/tts_voice use <voice_id>`。

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

  内容只有会话 UMO 到音色覆盖的映射，不包含聊天内容。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 401 | API Key 错误或已失效，重新在 Developer Console 创建。 |
| 403 | Key 没有权限使用该音色/模型，换一个音色或检查账户权限。 |
| 404 | `voice_id` 不存在；用 `/tts_voice list` 重新选择。 |
| 422 | 参数不合法，常见原因：`language_code` 不是两字母、模型与语言不兼容、文本超过长度限制。 |
| 429 | 触发限流，按 `Retry-After` 等待后重试，或降低 `max_concurrent`。 |
| QQ 语音是杂音/电流声 | 确认 `napcat_audio_mode=wav`；升级 NapCat ≥ v4.18.36；关闭其他 TTS 插件。 |
| NapCat 发送语音失败或没有声音 | 使用 `wav` 或 `native`；`silk` 在当前环境可能发送不出去。检查 AstrBot/NapCat 日志中的 ffmpeg、ntsilk 错误。 |
| 语音发送失败且日志提到 ffmpeg | 安装 ffmpeg 并加入 PATH；`wav`/`native` 模式依赖 NapCat 的音频转换。 |
| 模型不调用语音工具 | 在人格/系统提示词中要求“需要语音时调用 `breeze_blue_tts`”；确认模型提供商/Agent 已启用工具调用。 |
| 找不到“获取音色”按钮 | 打开插件详情页里的「Breeze Blue 音色」视图；该功能需要 AstrBot 插件视图支持（约 4.24.1+）。 |

## 开发与测试

插件附带了 29 个离线测试：使用假的 `astrbot` 模块和本地 aiohttp 测试服务器，覆盖文本分段、请求体、HTTP 请求/响应、错误映射、指令、LLM 工具、WebUI 音色 API 和 NapCat 音频模式，不需要 AstrBot 实例或真实 API Key。

```bash
uv run --python 3.13 --with aiohttp --no-project python tests/test_plugin_smoke.py
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
- 插件类继承 `Star`，使用 `@filter.command` 注册指令，使用 `@filter.llm_tool` 注册按需调用的语音工具。
- 语音消息使用 `astrbot.api.message_components.Record`，由 AstrBot 按平台适配为原生语音。
- 配置通过 `_conf_schema.json` 定义，并在 `__init__` 注入 `AstrBotConfig`。
- 音色选择使用 AstrBot 官方插件视图（`views/voices`）和 `context.register_web_api()`。
- 持久化数据写入 `data/plugin_data/`，不写入插件目录。

参考：[AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)、[插件配置](https://docs.astrbot.app/dev/star/guides/plugin-config.html)。

## 许可证

[MIT](LICENSE) © 2026 Qingfeng-gt
