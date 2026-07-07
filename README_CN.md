# mimo-cli 中文文档

面向 Xiaomi MiMo 开放平台**已文档化能力**的命令行工具，风格参考 MiniMax CLI：一次安装后集中使用文本、工具调用、联网搜索、多模态理解和语音合成能力。

原则：只实现公开文档中可验证的稳定接口；对产品材料中出现但公开 API 细节不足的能力，保留命名空间并返回明确提示，不伪造支持。

## 当前支持

- 文本对话 / 推理输出 / 结构化输出
- 函数 / 工具调用结果查看
- 内置 Web Search（需要账号或平台侧开启 `webSearchEnabled`）
- 图像理解
- 音频理解
- 视频理解
- TTS 内置音色
- TTS 声音设计
- TTS 声音克隆
- 唱歌风格 TTS
- TTS 流式输出（`mimo-v2.5-tts` 低延迟流式）
- 语音识别 / ASR 转写（`mimo-v2.5-asr`）

## 预留但暂不实装

以下能力目前没有足够公开稳定 API 文档，因此只保留入口：

- 图像生成 / 文生图
- 音乐生成 / 文生音乐
- GUI / computer-use

> 注：语音识别（ASR）此前为预留命令，自 v0.4.0 起已正式实装（见下方 `mimo speech transcribe`）。

## 安装

### 从 GitHub 安装

```bash
pip install git+https://github.com/will422-l/mimo-cli.git
```

如果当前网络下 GitHub git 传输不稳定，也可以从分支压缩包安装：

```bash
pip install https://github.com/will422-l/mimo-cli/archive/refs/heads/main.zip
```

### 从源码构建

```bash
python3 -m pip install build
python3 -m build
```

### 本地开发安装

```bash
git clone https://github.com/will422-l/mimo-cli.git
cd mimo-cli
python3 -m pip install -e .
```

## 快速开始

```bash
mimo auth login --api-key sk-xxxxx --base-url https://token-plan-cn.xiaomimimo.com/v1
mimo auth status
mimo doctor --live
mimo chat "简单介绍一下 MiMo"
```

也可以不落盘，用环境变量临时调用：

```bash
export MIMO_API_KEY=sk-xxxxx
export MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
mimo chat "你好"
```

## 认证与配置

```bash
mimo auth login --api-key sk-xxxxx
mimo auth login --api-key sk-xxxxx --base-url https://token-plan-cn.xiaomimimo.com/v1
mimo auth status
mimo auth logout

mimo config show
mimo config set default_text_model mimo-v2.5-pro
mimo config set base_url https://token-plan-cn.xiaomimimo.com/v1
mimo config unset api_key
```

配置默认保存到：

```text
~/.config/mimo-cli/config.json
```

环境变量覆盖：

```bash
export MIMO_API_KEY=***
export MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
export MIMO_CONFIG_DIR=/custom/config/dir
export MIMO_DEFAULT_TEXT_MODEL=mimo-v2.5
```

## 诊断

```bash
mimo doctor
mimo doctor --live
```

`doctor --live` 会真实调用一次 Chat Completion，并兼容 MiMo 返回 `reasoning_content` 但 `content` 为空的情况。

## 文本对话

```bash
mimo chat "解释一下工具调用"
mimo chat "流式输出这个回答" --stream
mimo chat "返回 JSON" --json-mode --output json
mimo text chat --message "user:你好" --message "assistant:你好" --message "user:继续解释"
mimo text chat --messages-file messages.json --output json
```

常用参数：

- `--model`: 指定模型
- `--system`: system prompt
- `--thinking`: 开启 thinking 参数
- `--budget-tokens`: thinking token 预算
- `--json-mode`: 请求 JSON object 输出
- `--stream`: 流式输出
- `--raw`: 打印完整原始响应

## 函数 / 工具调用

```bash
mimo tool-call "帮我查一下北京天气" --tools-file tools.json
mimo text tool-call "帮我查一下北京天气" --tools-file tools.json --thinking
mimo tool-call "请调用 get_weather 工具查询北京天气" --tools-file tools.json --raw
```

`tools.json` 示例：

```json
[
  {
    "type": "function",
    "function": {
      "name": "get_weather",
      "description": "Get current weather for a city",
      "parameters": {
        "type": "object",
        "properties": {
          "city": {"type": "string", "description": "City name"}
        },
        "required": ["city"]
      }
    }
  }
]
```

当前版本只查看模型返回的 `tool_calls`，不执行本地函数。`--run` 是预留给后续本地工具执行循环的接口。

已验证：MiMo 会返回 OpenAI-compatible `tool_calls`，例如 `get_weather({"city":"北京"})`。

## Web Search

```bash
mimo web-search "今天小米 AI 新闻" --forced --max-keyword 3 --limit 1
mimo web-search "武汉明天天气怎么样？" --forced --max-keyword 3 --limit 1 --country China --region Hubei --city Wuhan
mimo search query "MiMo 最新更新"
```

CLI 按官方文档使用 `force_search` 字段，并支持 `max_keyword`、`limit`、`user_location`。

注意：CLI 请求格式已被 MiMo 服务端识别为 `web_search` 工具；如果账号或 Token Plan 未开启，会返回类似错误：

```text
web search tool found in the request body, but webSearchEnabled is false
```

这不是 CLI 拼参错误，而是平台侧权限 / 开关问题。需要在 Xiaomi MiMo 开放平台或对应 Token Plan 中启用 `webSearchEnabled` 后再使用。

## 多模态理解

```bash
mimo image-understand ./demo.png "描述图片内容"
mimo audio-understand ./demo.wav "总结音频内容"
mimo video-understand ./demo.mp4 "描述视频情节"

mimo vision image ./demo.png
mimo vision audio ./demo.wav "听到了什么？"
mimo vision video ./demo.mp4 "总结视频"
```

本地媒体文件会自动转为 data URL，并通过 Chat Completion 的多模态 message content 提交。

## 语音合成

```bash
mimo tts "你好，欢迎使用 MiMo" -o hello.wav
mimo tts "祝你生日快乐" --sing -o song.wav

mimo speech synthesize "欢迎使用 MiMo" -o welcome.wav
mimo speech voice-design "年轻女声，明亮，语速偏快，适合科技新闻播报" "今天发布了新的 AI 功能。" -o design.wav
mimo speech voice-clone ./voice_sample.wav "这是声音克隆测试。" -o clone.wav
```

### 流式 TTS

`mimo-v2.5-tts` 支持低延迟流式输出。用 `--stream` 实时接收音频，CLI 会把流式 `pcm16` 分片拼成单个 wav（24kHz 单声道），无需额外依赖：

```bash
mimo tts "这是一段流式合成测试" --voice Chloe --stream -o stream.wav
```

> 声音设计（`mimo-v2.5-tts-voicedesign`）和声音克隆（`mimo-v2.5-tts-voiceclone`）的流式目前服务端为降级兼容模式，推理完成后才一次性返回。`--stream` 仍可用，但这两个模型暂时没有延迟收益。

## 语音识别（ASR）

通过 `mimo-v2.5-asr` 把音频（wav/mp3）转成文字。支持中英双语自动检测、方言（吴语/粤语/闽南语/四川话）、歌词转写，以及嘈杂/远场/多人重叠场景：

```bash
# 自动检测语言
mimo speech transcribe ./meeting.wav

# 指定中文 / 英文
mimo speech transcribe ./voice.wav --language zh
mimo speech transcribe ./voice.mp3 --language en

# 流式输出转写文字
mimo speech transcribe ./meeting.wav --stream

# 完整原始响应（usage 含 audio_tokens 和 seconds）
mimo speech transcribe ./voice.wav --raw
```

要求：输入须为 `wav` 或 `mp3`，base64 载荷 ≤ 10MB。

## 全能力映射表

| 能力 | 模型 | CLI 命令 | 状态 |
|---|---|---|---|
| 文本生成 | `mimo-v2.5-pro`, `mimo-v2.5`, `mimo-v2-pro`, `mimo-v2-omni`, `mimo-v2-flash` | `mimo chat`, `mimo text chat` | 已实装，已验证 |
| reasoning / thinking | 同文本模型 | `mimo chat --thinking` | 已实装 |
| 结构化输出 | 同文本模型 | `mimo chat --json-mode` | 已实装 |
| 函数 / 工具调用 | 同文本模型 | `mimo tool-call`, `mimo text tool-call` | 已实装，已验证返回 `tool_calls` |
| Web Search | 同文本模型 | `mimo web-search`, `mimo search query` | 已实装；账号侧需启用 `webSearchEnabled` |
| 图像理解 | `mimo-v2.5`, `mimo-v2-omni` | `mimo image-understand`, `mimo vision image` | 已实装 |
| 音频理解 | `mimo-v2.5`, `mimo-v2-omni` | `mimo audio-understand`, `mimo vision audio` | 已实装 |
| 视频理解 | `mimo-v2.5`, `mimo-v2-omni` | `mimo video-understand`, `mimo vision video` | 已实装 |
| 语音识别 / ASR | `mimo-v2.5-asr` | `mimo speech transcribe` | 已实装 |
| TTS 内置音色 | `mimo-v2.5-tts`, `mimo-v2-tts` | `mimo tts`, `mimo speech synthesize` | 已实装 |
| TTS 流式输出 | `mimo-v2.5-tts` | `mimo tts --stream` | 已实装 |
| 唱歌风格 TTS | `mimo-v2.5-tts`, `mimo-v2-tts` | `mimo tts --sing` | 已实装 |
| 声音设计 | `mimo-v2.5-tts-voicedesign` | `mimo speech voice-design` | 已实装 |
| 声音克隆 | `mimo-v2.5-tts-voiceclone` | `mimo speech voice-clone` | 已实装 |
| 图像生成 / 文生图 | 未见稳定公开 API | `mimo image generate` | 预留，明确报错 |
| 音乐生成 / 文生音乐 | 未见稳定公开 API | `mimo music generate` | 预留，明确报错 |
| GUI / computer-use | 未见稳定公开 API | `mimo gui` | 预留，明确报错 |

## 旧模型废弃说明（2026-06-30 北京时间）

以下旧模型已废弃并由 v2.5 系列自动替换。`mimo-cli` 仍允许选择它们以保持向后兼容，但新代码应直接使用 v2.5 模型：

| 废弃模型 | 替换模型 | 系统替换时间 | 下线时间 |
|---|---|---|---|
| `mimo-v2-pro` | `mimo-v2.5-pro` | 2026-06-01 | 2026-06-30 |
| `mimo-v2-omni` | `mimo-v2.5` | 2026-06-01 | 2026-06-30 |
| `mimo-v2-flash` | `mimo-v2.5` | 2026-06-18 | 2026-06-30 |
| `mimo-v2-tts` | `mimo-v2.5-tts` | 2026-06-18 | 2026-06-30 |

> 注：`mimo-v2-tts` 下线后，`mimo_default` 音色在中国集群映射为 `冰糖`、其他集群映射为 `Mia`。

## 预留命令

这些命令当前不会真正调用 API，而是返回清晰提示：

```bash
mimo image generate
mimo music generate
mimo gui
```

原因：目前公开 API 文档里还没有稳定接口说明。等官方文档或可验证接口出现后，可以直接在这些命名空间下补实现。

## 关于官方文档

本版本依据小米 MiMo 开放平台官方文档（`platform.xiaomimimo.com`）同步：

- **MiMo-V2.5 系列已开源**（MIT 协议，支持商用推理部署与二次训练，无需额外授权），模型权重见 [HuggingFace XiaomiMiMo](https://huggingface.co/collections/XiaomiMiMo/mimo-v25)。
- `mimo-v2.5-pro`：1T 参数 / 42B 激活 / 1M 上下文，面向 Agent 与 Coding 深度优化。
- `mimo-v2.5`：原生全模态（文本/图像/视频/音频），1M 上下文，Agent 能力对标 pro。
- `mimo-v2.5-asr`：中英双语 + 方言 + 歌词转写，嘈杂/远场/多人场景稳健。
- 官方同时兼容 OpenAI API 与 Anthropic API 两种格式。

## License

MIT
