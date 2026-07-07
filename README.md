# mimo-cli

Official-style Xiaomi MiMo command-line interface for the **documented** public API surface.

`mimo-cli` is a practical open-source CLI for:

- text chat
- function/tool calling inspection
- built-in web search
- image understanding
- audio understanding
- video understanding
- speech synthesis (built-in voice)
- speech synthesis (voice design)
- speech synthesis (voice clone)
- speech recognition / ASR (transcription)
- Feishu voice message sending

It also includes **reserved namespaces** for capabilities that appear in product/news materials but are **not yet documented as stable public API endpoints**. Those commands intentionally fail with a clear message instead of pretending support.

## Install

### From GitHub

```bash
pip install git+https://github.com/will422-l/mimo-cli.git
```

If GitHub git transport is unstable in your network, install from the branch archive instead:

```bash
pip install https://github.com/will422-l/mimo-cli/archive/refs/heads/main.zip
```

### Build from source

```bash
python3 -m pip install build
python3 -m build
```

### Local editable install

```bash
git clone https://github.com/will422-l/mimo-cli.git
cd mimo-cli
python3 -m pip install -e .
```

## Quick start

```bash
mimo auth login --api-key sk-xxxxx
mimo auth status
mimo doctor
mimo chat "What can Xiaomi MiMo do?"
```

## Command overview

### Auth & config

```bash
mimo auth login --api-key sk-xxxxx
mimo auth status
mimo auth logout

mimo config show
mimo config set default_text_model mimo-v2.5-pro
mimo config set base_url https://token-plan-cn.xiaomimimo.com/v1
mimo config unset api_key
```

### Diagnostics

```bash
mimo doctor
mimo doctor --live
```

### Text chat

```bash
mimo chat "Explain MiMo briefly"
mimo text chat --message "user:Hello" --message "assistant:Hi" --message "user:Summarize tool calling"
mimo text chat --messages-file messages.json --output json
mimo chat "Stream this response" --stream
```

### Function tool calling

```bash
mimo tool-call "Check Beijing weather" --tools-file tools.json
mimo text tool-call "Check Beijing weather" --tools-file tools.json --thinking
```

> `--run` is currently reserved for a future local tool execution loop. Current releases inspect model tool calls but do not execute local functions yet.

### Web search

```bash
mimo web-search "Latest Xiaomi AI news" --forced
mimo search query "MiMo release notes"
```

### Vision / multimodal understanding

```bash
mimo image-understand ./demo.png "Describe the image"
mimo audio-understand ./demo.wav "Summarize the audio"
mimo video-understand ./demo.mp4 "Describe the video"

mimo vision image ./demo.png
mimo vision audio ./demo.wav "What is being said?"
mimo vision video ./demo.mp4 "Summarize the scene"
```

### Speech synthesis

```bash
# Preset voice TTS
mimo tts "Hello from MiMo" -o hello.wav
mimo tts "Happy birthday to you" --sing -o song.wav
mimo tts "温柔地说" --voice 冰糖 -o gentle.wav

# Natural language style control (director mode)
mimo tts "冷静，冷静..." --voice 冰糖 --context "紧张的语气，语速加快" -o tense.wav

# Voice design
mimo speech voice-design "Young female voice, bright, fast-paced" "Today we launched new AI features." -o design.wav

# Voice clone
mimo speech voice-clone ./voice_sample.wav "This is a cloned-voice demo." -o clone.wav

# Voice clone with director mode
mimo speech voice-clone ./voice_sample.wav --context "用温柔的语气，语速稍慢" "没关系，慢慢来" -o clone_director.wav
```

#### Preset voices

| Voice ID | Language | Gender | Style |
|----------|----------|--------|-------|
| 冰糖 | 中文 | 女性 | 活泼少女 |
| 茉莉 | 中文 | 女性 | 知性女声 |
| 苏打 | 中文 | 男性 | 阳光少年 |
| 白桦 | 中文 | 男性 | 成熟男声 |
| Mia | English | Female | Lively girl |
| Chloe | English | Female | Sweet Dreamy |
| Milo | English | Male | Sunny boy |
| Dean | English | Male | Steady Gentle |

#### Natural language control (--context)

All TTS models support `--context` for style/director mode:

- **Multi-style**: Switch between narration → whisper → shout within one utterance
- **Multi-emotion**: Composite emotions like "suppressed anger" or "laughing through tears"
- **Director mode**: Full character + scene + direction control for role-play / dubbing

Example director mode:
```bash
mimo tts "你以为我会原谅你吗" --voice 白桦 \
  --context "角色：冷酷的反派，场景：面对背叛，指导：语速极慢，每个字都像在舌尖滚过" \
  -o villain.wav
```

#### Audio tag control

Insert emotion/action tags in parentheses within the text:

```bash
mimo tts "（紧张，深呼吸）呼……冷静，冷静。（小声）领带歪没歪？" --voice 冰糖 -o interview.wav
mimo tts "(sighs deeply) I don't know anymore. (suddenly firm) But I won't give up!" --voice Mia -o english.wav
```

#### Singing

```bash
mimo tts "(唱歌)原谅我这一生不羁放纵爱自由" --voice 冰糖 -o song.wav
```

#### Audio format

All TTS commands support `--format wav|mp3|opus`:

```bash
mimo tts "Hello" --voice Mia --format mp3 -o hello.mp3
```

#### Streaming TTS

`mimo-v2.5-tts` supports low-latency streaming output. Use `--stream` to receive audio in real time; the CLI splices the streamed `pcm16` chunks into a single wav (24kHz mono) — no extra dependencies required:

```bash
mimo tts "This is a streaming test" --voice Chloe --stream -o stream.wav
```

> Voice design (`mimo-v2.5-tts-voicedesign`) and voice clone (`mimo-v2.5-tts-voiceclone`) streaming is currently in a downgraded compatibility mode on the server side — they only return the result once after inference completes. `--stream` still works but offers no latency benefit for those two models yet.

### Speech recognition (ASR)

Transcribe audio (wav/mp3) to text via `mimo-v2.5-asr`. Supports bilingual Chinese/English with auto-detection, dialects (Wu/Cantonese/Minnan/Sichuanese), lyrics, and noisy/far-field/multi-speaker audio:

```bash
# Auto-detect language
mimo speech transcribe ./meeting.wav

# Force Chinese / English recognition
mimo speech transcribe ./voice.wav --language zh
mimo speech transcribe ./voice.mp3 --language en

# Stream the transcript as it is generated
mimo speech transcribe ./meeting.wav --stream

# Full raw response (usage includes audio_tokens + seconds)
mimo speech transcribe ./voice.wav --raw
```

Requirements: input must be `wav` or `mp3`, base64 payload ≤ 10MB.

### Feishu voice message sending

Send TTS-generated audio as a native Feishu voice message (not a file attachment):

```bash
# Generate voice
mimo tts "好的，马上就好！" --voice 冰糖 -o /tmp/voice.wav

# Send to Feishu DM (open_id)
mimo speech feishu-send /tmp/voice.wav open_id ou_xxxxxx

# Send to Feishu group (chat_id)
mimo speech feishu-send /tmp/voice.wav chat_id oc_xxxxxx
```

Requires environment variables:
- `FEISHU_APP_ID` — Feishu app ID
- `FEISHU_APP_SECRET` — Feishu app secret

Requires: `ffmpeg` (for WAV→Opus conversion)

> **Why not use a generic message tool?** Feishu voice messages require uploading via `/im/v1/files` with `msg_type: audio`, then sending with the `file_key`. Generic message tools typically don't implement this flow and would send audio as a file attachment instead of a voice bubble.

## Reserved future namespaces

These commands are intentionally present as stable UX placeholders, but they currently return a clear "not yet documented" error:

```bash
mimo image generate
mimo music generate
mimo gui
```

Why? Because Xiaomi MiMo public docs currently do **not** provide enough stable API detail for these capabilities, and this project prefers explicit placeholders over fake support. (Speech recognition / ASR was previously reserved but is now implemented — see `mimo speech transcribe` above.)

## Documented capability map

### Explicitly documented in current MiMo public API docs

- `mimo-v2.5-pro` / `mimo-v2.5` / `mimo-v2-pro` / `mimo-v2-omni` / `mimo-v2-flash`
  - text generation (1M context / 128K output for pro & v2.5; 256K/128K for omni; 256K/64K for flash)
  - deep thinking (thinking mode)
  - function calling
  - structured output
  - web search
- `mimo-v2.5` / `mimo-v2-omni`
  - image understanding
  - audio understanding
  - video understanding
- `mimo-v2.5-asr` (released 2026-06-02)
  - speech recognition / transcription (Chinese + English + dialects + lyrics)
- `mimo-v2.5-tts`
  - built-in voice TTS (8 preset voices + `mimo_default`)
  - natural language style control / director mode
  - audio tag control
  - singing style
  - low-latency streaming output
- `mimo-v2.5-tts-voicedesign`
  - voice design from text description
  - director mode
- `mimo-v2.5-tts-voiceclone`
  - voice cloning from audio sample (mp3/wav, max 10MB)
  - director mode
- `mimo-v2-tts`
  - older TTS model (deprecated 2026-06-30, auto-replaced by `mimo-v2.5-tts`)

### Legacy model deprecation (2026-06-30, Beijing time)

The following legacy models are deprecated and auto-replaced by their v2.5 counterparts. `mimo-cli` keeps them selectable for backward compatibility, but new code should target the v2.5 models:

| Deprecated | Replacement | System replacement | Deprecation |
|---|---|---|---|
| `mimo-v2-pro` | `mimo-v2.5-pro` | 2026-06-01 | 2026-06-30 |
| `mimo-v2-omni` | `mimo-v2.5` | 2026-06-01 | 2026-06-30 |
| `mimo-v2-flash` | `mimo-v2.5` | 2026-06-18 | 2026-06-30 |
| `mimo-v2-tts` | `mimo-v2.5-tts` | 2026-06-18 | 2026-06-30 |

### Reserved, not implemented until publicly documented

- image generation / text-to-image
- music generation / text-to-music
- GUI / computer-use API

## Notes

- Local media files are automatically converted to data URLs for documented multimodal endpoints. Audio MIME types are normalized to the values the API documents (`audio/wav`, `audio/mpeg`) regardless of the local `mimetypes` mapping.
- ASR input must be `wav` or `mp3`, with the base64 payload ≤ 10MB.
- Voice clone samples are validated: only mp3/wav format, max 10MB.
- Web Search must be enabled for the API key / endpoint you are using. Xiaomi MiMo Token Plan keys can be endpoint-scoped: a key that works on `https://token-plan-cn.xiaomimimo.com/v1` may be invalid on `https://api.xiaomimimo.com/v1`. If the server returns `webSearchEnabled is false`, the request has reached MiMo but that key/endpoint still has Web Search disabled.
- Saved credentials are stored in `~/.config/mimo-cli/config.json` unless `MIMO_CONFIG_DIR` is set.

## Changelog

### 0.4.0 — Synced with official MiMo docs (ASR, streaming TTS, deprecation)

- **Added ASR (speech recognition)**: `mimo speech transcribe` now actually calls `mimo-v2.5-asr` instead of returning a reserved error. Supports `--language auto|zh|en`, `--stream`, `--raw`. Input is wav/mp3 (≤10MB base64), MIME normalized to `audio/wav` / `audio/mpeg` per official docs.
- **Added streaming TTS**: `mimo tts --stream` uses `mimo-v2.5-tts` low-latency streaming (`pcm16`), spliced into a 24kHz mono wav with only the standard library (no numpy/soundfile dependency).
- **Restored `mimo_default`** as a documented valid voice ID (resolves to 冰糖 on the China cluster, Mia elsewhere).
- **Updated capability map**: added `asr_models`, `tts_streaming`, `speech_recognition_asr`; removed "standalone ASR HTTP API" from reserved list.
- **Documented legacy model deprecation** (2026-06-30): `mimo-v2-pro/omni/flash/tts` auto-replaced by v2.5 counterparts; surfaced in `mimo models` output.
- **Docs refreshed** against the official platform docs (`platform.xiaomimimo.com`), including the MiMo-V2.5 open-source (MIT) and Orbit program notes.

### 0.3.0 — Integrated Xiaomi official MiMo-Skills

- Added `--context` parameter to all TTS commands (preset voice, voice-design, voice-clone) for natural language style control and director mode
- Added preset voice validation (8 official voices: 冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean)
- Added `--format wav|mp3|opus` choices for all TTS commands
- Added voice-clone sample validation (format: mp3/wav only, max 10MB)
- Added `mimo speech feishu-send` command for sending audio as native Feishu voice messages
- Changed default voice from `mimo_default` to `冰糖` (matches official documentation)

### 0.2.0

- Initial public release

## License

MIT
