import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

__version__ = "0.4.0"
APP_NAME = "mimo-cli"
CONFIG_DIR = Path(os.environ.get("MIMO_CONFIG_DIR", Path.home() / ".config" / APP_NAME))
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_BASE_URL = "https://api.xiaomimimo.com"
DEFAULT_TIMEOUT = int(os.environ.get("MIMO_TIMEOUT", "300"))
# Documented preset voices for mimo-v2.5-tts.
# "mimo_default" is the official default voice ID: it resolves to 冰糖 on the
# China cluster and Mia on other clusters (see official TTS docs).
PRESET_VOICES = [
    "mimo_default",
    "冰糖", "茉莉", "苏打", "白桦",  # 中文音色
    "Mia", "Chloe", "Milo", "Dean",  # 英文音色
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "base_url": DEFAULT_BASE_URL,
    "default_text_model": "mimo-v2.5-pro",
    "default_vision_model": "mimo-v2.5",
    "default_asr_model": "mimo-v2.5-asr",
    "default_tts_model": "mimo-v2.5-tts",
    "default_voice": "冰糖",
    "timeout": DEFAULT_TIMEOUT,
}


class MimoError(RuntimeError):
    pass


class NotYetDocumentedError(MimoError):
    pass


def load_config() -> Dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise MimoError(f"Invalid config JSON: {CONFIG_PATH}: {exc}") from exc
    if os.environ.get("MIMO_BASE_URL"):
        config["base_url"] = os.environ["MIMO_BASE_URL"]
    if os.environ.get("MIMO_TIMEOUT"):
        config["timeout"] = int(os.environ["MIMO_TIMEOUT"])
    return config


def save_config(config: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return value[:6] + "..." + value[-4:]


def get_config_value(key: str) -> Any:
    return load_config().get(key, DEFAULT_CONFIG.get(key))


def api_base() -> str:
    return str(get_config_value("base_url") or DEFAULT_BASE_URL).rstrip("/")


def chat_url() -> str:
    base = api_base()
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def timeout() -> int:
    return int(get_config_value("timeout") or DEFAULT_TIMEOUT)


def get_api_key(args: Optional[argparse.Namespace] = None, required: bool = True) -> Optional[str]:
    if args is not None and getattr(args, "api_key", None):
        return args.api_key
    key = os.environ.get("MIMO_API_KEY") or os.environ.get("XIAOMIMIMO_API_KEY")
    if key:
        return key
    key = load_config().get("api_key")
    if key:
        return key
    if required:
        raise MimoError("Missing API key. Run `mimo auth login --api-key sk-...` or set MIMO_API_KEY.")
    return None


def auth_headers(args: Optional[argparse.Namespace] = None) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {get_api_key(args)}",
        "Content-Type": "application/json",
    }


def read_text_arg(text: Optional[str], text_file: Optional[str]) -> str:
    if text_file:
        if text_file == "-":
            return sys.stdin.read()
        return Path(text_file).read_text(encoding="utf-8")
    if text is None:
        if not sys.stdin.isatty():
            data = sys.stdin.read()
            if data:
                return data
        raise MimoError("Text is required. Pass positional text, --text-file, or pipe stdin.")
    return text


def file_to_data_url(path: str) -> str:
    p = Path(path)
    mime, _ = mimetypes.guess_type(str(p))
    if not mime:
        mime = "application/octet-stream"
    raw = p.read_bytes()
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def audio_data_url(path: str) -> str:
    """Build a data URL with the MIME the MiMo API documents for audio.

    Official ASR docs require wav -> ``audio/wav`` and mp3 -> ``audio/mpeg``
    (or ``audio/mp3``). ``mimetypes.guess_type`` may return ``audio/x-wav``
    on some platforms, so we normalize here for API compatibility.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".wav":
        mime = "audio/wav"
    elif suffix == ".mp3":
        mime = "audio/mpeg"
    else:
        mime, _ = mimetypes.guess_type(str(p))
        if not mime:
            mime = "application/octet-stream"
    raw = p.read_bytes()
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def maybe_media_ref(value: str, kind: str) -> Dict[str, Any]:
    if value.startswith("http://") or value.startswith("https://") or value.startswith("data:"):
        return {kind: {"url": value} if kind in {"image_url", "video_url"} else {"data": value}}
    data_url = file_to_data_url(value)
    return {kind: {"url": data_url} if kind in {"image_url", "video_url"} else {"data": data_url}}


def post_chat(payload: Dict[str, Any], args: Optional[argparse.Namespace] = None, stream: bool = False):
    response = requests.post(
        chat_url(),
        headers=auth_headers(args),
        json=payload,
        stream=stream,
        timeout=timeout(),
    )
    if response.status_code >= 400:
        raise MimoError(f"HTTP {response.status_code}: {response.text[:2000]}")
    return response


def extract_message(data: Dict[str, Any]) -> Dict[str, Any]:
    choices = data.get("choices") or []
    if not choices:
        raise MimoError("No choices returned")
    return choices[0].get("message") or {}


def save_audio_from_message(message: Dict[str, Any], out_path: str) -> None:
    audio = message.get("audio")
    if not audio or not audio.get("data"):
        raise MimoError("No audio returned in response")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(base64.b64decode(audio["data"]))


def save_streamed_pcm16_as_wav(response, out_path: str) -> None:
    """Splice streamed TTS pcm16 chunks (delta.audio.data, base64) into a wav.

    Official MiMo streaming TTS emits 24kHz mono PCM16LE audio across SSE
    chunks. This collects every chunk's raw bytes and writes a single wav
    using only the standard library (no numpy/soundfile dependency).
    """
    import wave
    buf = bytearray()
    chunk_count = 0
    for chunk in parse_sse_lines(response):
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        audio = delta.get("audio")
        if not audio or not audio.get("data"):
            continue
        buf.extend(base64.b64decode(audio["data"]))
        chunk_count += 1
    if not buf:
        raise MimoError("No audio chunks received from streaming TTS response")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(24000)
        wf.writeframes(bytes(buf))


def print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def parse_sse_lines(response):
    for raw in response.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


def print_streaming_chat(response, raw: bool = False) -> None:
    for chunk in parse_sse_lines(response):
        if raw:
            print_json(chunk)
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        reasoning = delta.get("reasoning_content")
        content = delta.get("content")
        if reasoning:
            print(reasoning, end="", flush=True)
        if content:
            print(content, end="", flush=True)
    if not raw:
        print()


def capability_map() -> Dict[str, Any]:
    return {
        "text_models": [
            "mimo-v2.5-pro",
            "mimo-v2.5",
            "mimo-v2-pro",
            "mimo-v2-omni",
            "mimo-v2-flash",
        ],
        "asr_models": [
            "mimo-v2.5-asr",
        ],
        "tts_models": [
            "mimo-v2.5-tts",
            "mimo-v2.5-tts-voiceclone",
            "mimo-v2.5-tts-voicedesign",
            "mimo-v2-tts",
        ],
        "documented_capabilities": {
            "function_calling": ["mimo-v2.5-pro", "mimo-v2-pro", "mimo-v2.5", "mimo-v2-omni", "mimo-v2-flash"],
            "web_search": ["mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-pro", "mimo-v2-omni", "mimo-v2-flash"],
            "image_understanding": ["mimo-v2.5", "mimo-v2-omni"],
            "audio_understanding": ["mimo-v2.5", "mimo-v2-omni"],
            "video_understanding": ["mimo-v2.5", "mimo-v2-omni"],
            "speech_recognition_asr": ["mimo-v2.5-asr"],
            "tts_builtin_voice": ["mimo-v2.5-tts", "mimo-v2-tts"],
            "tts_streaming": ["mimo-v2.5-tts"],
            "tts_voice_design": ["mimo-v2.5-tts-voicedesign"],
            "tts_voice_clone": ["mimo-v2.5-tts-voiceclone"],
            "singing_style": ["mimo-v2.5-tts", "mimo-v2-tts"],
        },
        "deprecated_models": {
            "note": "Legacy models are deprecated 2026-06-30 (Beijing time) and auto-replaced.",
            "mimo-v2-pro": {"replacement": "mimo-v2.5-pro", "system_replacement_time": "2026-06-01", "deprecation_time": "2026-06-30"},
            "mimo-v2-omni": {"replacement": "mimo-v2.5", "system_replacement_time": "2026-06-01", "deprecation_time": "2026-06-30"},
            "mimo-v2-flash": {"replacement": "mimo-v2.5", "system_replacement_time": "2026-06-18", "deprecation_time": "2026-06-30"},
            "mimo-v2-tts": {"replacement": "mimo-v2.5-tts", "system_replacement_time": "2026-06-18", "deprecation_time": "2026-06-30"},
        },
        "reserved_not_yet_documented": [
            "image generation / text-to-image",
            "music generation / text-to-music",
            "GUI/computer-use API details",
        ],
    }


def cmd_models(_: argparse.Namespace) -> None:
    print_json(capability_map())


def cmd_auth_login(args: argparse.Namespace) -> None:
    config = load_config()
    key = args.api_key
    if not key:
        if sys.stdin.isatty():
            key = input("MiMo API key: ").strip()
        else:
            key = sys.stdin.read().strip()
    if not key:
        raise MimoError("API key is empty")
    config["api_key"] = key
    if args.base_url:
        config["base_url"] = args.base_url.rstrip("/")
    save_config(config)
    print(f"Saved MiMo credentials to {CONFIG_PATH}")


def cmd_auth_status(args: argparse.Namespace) -> None:
    key = get_api_key(args, required=False)
    config = load_config()
    source = "none"
    if args.api_key:
        source = "--api-key"
    elif os.environ.get("MIMO_API_KEY") or os.environ.get("XIAOMIMIMO_API_KEY"):
        source = "environment"
    elif config.get("api_key"):
        source = str(CONFIG_PATH)
    masked = None if not key else mask_secret(key)
    print_json({
        "authenticated": bool(key),
        "key_source": source,
        "key": masked,
        "base_url": api_base(),
        "config_path": str(CONFIG_PATH),
    })


def cmd_auth_logout(_: argparse.Namespace) -> None:
    config = load_config()
    existed = "api_key" in config
    config.pop("api_key", None)
    save_config(config)
    print("Removed saved API key" if existed else "No saved API key found")


def cmd_config_show(_: argparse.Namespace) -> None:
    config = load_config()
    if config.get("api_key"):
        config = dict(config)
        config["api_key"] = mask_secret(config["api_key"])
    print_json({"config_path": str(CONFIG_PATH), "config": config})


def cmd_config_set(args: argparse.Namespace) -> None:
    allowed = set(DEFAULT_CONFIG) | {"api_key"}
    if args.key not in allowed:
        raise MimoError(f"Unsupported config key: {args.key}. Allowed: {', '.join(sorted(allowed))}")
    config = load_config()
    value: Any = args.value
    if args.key == "timeout":
        value = int(value)
    if args.key == "base_url":
        value = value.rstrip("/")
    config[args.key] = value
    save_config(config)
    print(f"Set {args.key}={value if args.key != 'api_key' else '***'}")


def cmd_config_unset(args: argparse.Namespace) -> None:
    config = load_config()
    config.pop(args.key, None)
    save_config(config)
    print(f"Unset {args.key}")


def build_chat_payload(args: argparse.Namespace) -> Dict[str, Any]:
    messages = []
    if getattr(args, "messages_file", None):
        content = sys.stdin.read() if args.messages_file == "-" else Path(args.messages_file).read_text(encoding="utf-8")
        messages = json.loads(content)
    elif getattr(args, "message", None):
        for item in args.message:
            if ":" in item and item.split(":", 1)[0] in {"system", "user", "assistant", "tool"}:
                role, content = item.split(":", 1)
                messages.append({"role": role, "content": content})
            else:
                messages.append({"role": "user", "content": item})
    else:
        user_text = read_text_arg(getattr(args, "text", None), getattr(args, "text_file", None))
        messages = [{"role": "user", "content": user_text}]
    if getattr(args, "system", None):
        messages.insert(0, {"role": "system", "content": args.system})
    payload: Dict[str, Any] = {"model": args.model or get_config_value("default_text_model"), "messages": messages}
    if getattr(args, "temperature", None) is not None:
        payload["temperature"] = args.temperature
    if getattr(args, "max_tokens", None) is not None:
        payload["max_tokens"] = args.max_tokens
    if getattr(args, "thinking", False):
        payload["thinking"] = {"type": "enabled", "budget_tokens": args.budget_tokens}
    if getattr(args, "json_mode", False):
        payload["response_format"] = {"type": "json_object"}
    if getattr(args, "stream", False):
        payload["stream"] = True
    return payload


def cmd_chat(args: argparse.Namespace) -> None:
    payload = build_chat_payload(args)
    if args.stream:
        response = post_chat(payload, args=args, stream=True)
        print_streaming_chat(response, raw=args.raw)
        return
    data = post_chat(payload, args=args).json()
    if args.raw:
        print_json(data)
        return
    message = extract_message(data)
    if message.get("reasoning_content"):
        print("=== reasoning_content ===")
        print(message["reasoning_content"])
        print()
    if args.output == "json":
        print_json(message)
    else:
        print(message.get("content", ""))


def cmd_tool_call(args: argparse.Namespace) -> None:
    prompt = read_text_arg(args.text, args.text_file)
    schema = json.loads(Path(args.tools_file).read_text(encoding="utf-8"))
    payload = {
        "model": args.model or get_config_value("default_text_model"),
        "messages": [{"role": "user", "content": prompt}],
        "tools": schema,
        "tool_choice": args.tool_choice,
    }
    if args.thinking:
        payload["thinking"] = {"type": "enabled", "budget_tokens": args.budget_tokens}
    data = post_chat(payload, args=args).json()
    print_json(data if args.raw else extract_message(data))
    if args.run:
        print("\nNote: --run is reserved for a future local tool execution loop. Current version only inspects model tool_calls.", file=sys.stderr)


def cmd_web_search(args: argparse.Namespace) -> None:
    prompt = read_text_arg(args.text, args.text_file)
    tool: Dict[str, Any] = {"type": "web_search"}
    if args.forced:
        # Xiaomi MiMo official docs use force_search (not forced_search).
        tool["force_search"] = True
    if args.max_keyword is not None:
        tool["max_keyword"] = args.max_keyword
    if args.limit is not None:
        tool["limit"] = args.limit
    location = {k: v for k, v in {
        "type": "approximate" if any([args.country, args.region, args.city]) else None,
        "country": args.country,
        "region": args.region,
        "city": args.city,
    }.items() if v}
    if location:
        tool["user_location"] = location
    payload = {
        "model": args.model or get_config_value("default_text_model"),
        "messages": [{"role": "user", "content": prompt}],
        "tools": [tool],
        "tool_choice": "auto",
    }
    data = post_chat(payload, args=args).json()
    if args.raw:
        print_json(data)
        return
    msg = extract_message(data)
    print(msg.get("content", ""))
    annotations = msg.get("annotations") or []
    if annotations:
        print("\n=== annotations ===")
        print_json(annotations)
    usage = data.get("usage", {}).get("web_search_usage")
    if usage:
        print("\n=== web_search_usage ===")
        print_json(usage)


def multimodal_message(prompt: str, media_kind: str, media_value: str) -> List[Dict[str, Any]]:
    part = maybe_media_ref(media_value, media_kind)
    kind = next(iter(part.keys()))
    return [{"role": "user", "content": [
        {"type": kind, kind: part[kind]},
        {"type": "text", "text": prompt},
    ]}]


def run_multimodal(args: argparse.Namespace, media_kind: str, media_value: str, prompt: str) -> None:
    payload = {
        "model": args.model or get_config_value("default_vision_model"),
        "messages": multimodal_message(prompt, media_kind, media_value),
    }
    data = post_chat(payload, args=args).json()
    if args.raw:
        print_json(data)
    else:
        msg = extract_message(data)
        print(msg.get("content") or json.dumps(msg, ensure_ascii=False, indent=2))


def cmd_image_understand(args: argparse.Namespace) -> None:
    run_multimodal(args, "image_url", args.image, args.prompt)


def cmd_audio_understand(args: argparse.Namespace) -> None:
    run_multimodal(args, "input_audio", args.audio, args.prompt)


def cmd_video_understand(args: argparse.Namespace) -> None:
    run_multimodal(args, "video_url", args.video, args.prompt)


def cmd_tts(args: argparse.Namespace) -> None:
    text = read_text_arg(args.text, args.text_file)
    messages = []
    if args.context:
        # 自然语言风格控制 / 导演模式：通过 user 消息传入
        messages.append({"role": "user", "content": args.context})
    elif args.instruction:
        # 向后兼容：旧 --instruction 参数映射到 context
        messages.append({"role": "user", "content": args.instruction})
    if args.sing:
        text = "<style>唱歌</style>" + text
    messages.append({"role": "assistant", "content": text})
    voice = args.voice or get_config_value("default_voice")
    if voice not in PRESET_VOICES:
        print(f"Warning: '{voice}' is not a documented preset voice. Valid: {', '.join(PRESET_VOICES)}", file=sys.stderr)
    if args.stream:
        # Official streaming TTS uses pcm16 chunks; we splice them into a wav.
        payload = {
            "model": args.model or get_config_value("default_tts_model"),
            "messages": messages,
            "audio": {"voice": voice, "format": "pcm16"},
            "stream": True,
        }
        response = post_chat(payload, args=args, stream=True)
        save_streamed_pcm16_as_wav(response, args.output)
        if args.raw:
            print(f"(streamed audio written to {args.output}; raw stream not captured)")
        else:
            print(args.output)
        return
    payload = {
        "model": args.model or get_config_value("default_tts_model"),
        "messages": messages,
        "audio": {"voice": voice, "format": args.format},
        "stream": False,
    }
    data = post_chat(payload, args=args).json()
    message = extract_message(data)
    save_audio_from_message(message, args.output)
    if args.raw:
        print_json(data)
    else:
        print(args.output)


def cmd_tts_voice_design(args: argparse.Namespace) -> None:
    target_text = read_text_arg(args.text, args.text_file)
    # --context 用于音色描述/导演模式（官方 user 消息角色）
    voice_prompt = getattr(args, "context", None) or args.voice_prompt
    messages = [{"role": "user", "content": voice_prompt}]
    if not args.optimize_text_preview:
        messages.append({"role": "assistant", "content": target_text})
    payload = {
        "model": "mimo-v2.5-tts-voicedesign",
        "messages": messages,
        "audio": {"voice": "voice_design", "format": args.format, "optimize_text_preview": bool(args.optimize_text_preview)},
        "stream": False,
    }
    data = post_chat(payload, args=args).json()
    message = extract_message(data)
    save_audio_from_message(message, args.output)
    if args.raw:
        print_json(data)
    else:
        print(args.output)


def validate_voice_sample(path: str) -> None:
    """Validate voice clone sample file (format and size)."""
    p = Path(path)
    if not p.exists():
        raise MimoError(f"Voice sample file not found: {path}")
    suffix = p.suffix.lower()
    if suffix not in {".mp3", ".wav"}:
        raise MimoError(f"Unsupported voice sample format: {suffix}. Only mp3 and wav are supported.")
    size = p.stat().st_size
    if size > 10 * 1024 * 1024:
        raise MimoError(f"Voice sample file too large: {size / 1024 / 1024:.1f} MB (max 10 MB)")


def cmd_tts_voice_clone(args: argparse.Namespace) -> None:
    target_text = read_text_arg(args.text, args.text_file)
    validate_voice_sample(args.voice_sample)
    messages = []
    context = getattr(args, "context", None)
    if context:
        # 导演模式：通过 user 消息传入风格控制指令
        messages.append({"role": "user", "content": context})
    messages.append({"role": "assistant", "content": target_text})
    payload = {
        "model": "mimo-v2.5-tts-voiceclone",
        "messages": messages,
        "audio": {"voice": file_to_data_url(args.voice_sample), "format": args.format},
        "stream": False,
    }
    data = post_chat(payload, args=args).json()
    message = extract_message(data)
    save_audio_from_message(message, args.output)
    if args.raw:
        print_json(data)
    else:
        print(args.output)


def reserved_feature(name: str) -> None:
    raise NotYetDocumentedError(
        f"{name} is reserved but not implemented because Xiaomi MiMo public API docs do not currently document a stable endpoint. "
        "This command exists as a future integration point. See ERRORS.md and docs/RESERVED.md."
    )


def cmd_feishu_send_audio(args: argparse.Namespace) -> None:
    """Send an audio file as a Feishu voice message.

    Implements the full flow: wav → opus (ffmpeg) → get tenant_access_token
    → upload audio → send audio message. This is necessary because Feishu
    voice messages require uploading via /im/v1/files with msg_type=audio,
    which generic message tools don't support correctly.
    """
    audio_path = Path(args.audio_file)
    if not audio_path.exists():
        raise MimoError(f"Audio file not found: {args.audio_file}")

    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise MimoError("FEISHU_APP_ID and FEISHU_APP_SECRET environment variables are required")

    # Step 1: Convert to opus using ffmpeg
    import subprocess
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    opus_path = os.path.join(tmp_dir, "voice.opus")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-c:a", "libopus", "-b:a", "32k", opus_path],
            check=True, capture_output=True, timeout=30,
        )
    except FileNotFoundError:
        raise MimoError("ffmpeg is required for Feishu audio sending. Install with: apt install ffmpeg")
    except subprocess.CalledProcessError as e:
        raise MimoError(f"ffmpeg conversion failed: {e.stderr.decode()[:500]}")

    # Step 2: Get tenant_access_token
    token_resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    token_data = token_resp.json()
    tenant_token = token_data.get("tenant_access_token")
    if not tenant_token:
        raise MimoError(f"Failed to get Feishu tenant_access_token: {token_data.get('msg', 'unknown error')}")

    # Step 3: Get audio duration
    try:
        duration_result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", opus_path],
            capture_output=True, text=True, timeout=10,
        )
        duration_ms = int(float(duration_result.stdout.strip()) * 1000)
    except Exception:
        duration_ms = 0

    # Step 4: Upload audio file
    with open(opus_path, "rb") as f:
        upload_resp = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/files",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={"file_type": "opus", "file_name": "voice.opus", "duration": str(duration_ms)},
            files={"file": ("voice.opus", f, "audio/opus")},
            timeout=30,
        )
    upload_data = upload_resp.json()
    file_key = upload_data.get("data", {}).get("file_key")
    if not file_key:
        raise MimoError(f"Failed to upload audio to Feishu: {upload_data.get('msg', 'no file_key returned')}")

    # Step 5: Send audio message
    send_resp = requests.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={args.receive_id_type}",
        headers={"Authorization": f"Bearer {tenant_token}", "Content-Type": "application/json"},
        json={
            "receive_id": args.receive_id,
            "msg_type": "audio",
            "content": json.dumps({"file_key": file_key}),
        },
        timeout=10,
    )
    send_data = send_resp.json()
    code = send_data.get("code", -1)
    if code != 0:
        raise MimoError(f"Failed to send Feishu audio message: {send_data.get('msg', 'unknown error')}")

    # Cleanup
    try:
        os.remove(opus_path)
        os.rmdir(tmp_dir)
    except OSError:
        pass

    print(f"Feishu voice message sent to {args.receive_id_type}={args.receive_id}")


def cmd_image_generate(_: argparse.Namespace) -> None:
    reserved_feature("image generation / text-to-image")


def cmd_music_generate(_: argparse.Namespace) -> None:
    reserved_feature("music generation / text-to-music")


def cmd_asr_transcribe(args: argparse.Namespace) -> None:
    """Speech recognition (ASR) via mimo-v2.5-asr.

    Officially documented API (2026-06-02 release). Accepts a local wav/mp3
    file, converts to a data URL, and submits via /v1/chat/completions with
    the ``mimo-v2.5-asr`` model. Optional ``asr_options.language`` selects
    auto/zh/en. Supports streaming output.
    """
    audio_path = args.audio
    if not audio_path:
        raise MimoError("Audio file is required. Pass a positional path or pipe stdin.")
    p = Path(audio_path)
    if not p.exists():
        raise MimoError(f"Audio file not found: {audio_path}")
    # Validate format & size consistent with official docs (mp3/wav, <=10MB base64)
    suffix = p.suffix.lower()
    if suffix not in {".mp3", ".wav"}:
        raise MimoError(f"Unsupported audio format: {suffix}. Only mp3 and wav are supported for ASR.")
    data_url = audio_data_url(audio_path)
    payload: Dict[str, Any] = {
        "model": "mimo-v2.5-asr",
        "messages": [{
            "role": "user",
            "content": [{"type": "input_audio", "input_audio": {"data": data_url}}],
        }],
    }
    if args.language and args.language != "auto":
        payload["asr_options"] = {"language": args.language}
    if args.stream:
        payload["stream"] = True
        response = post_chat(payload, args=args, stream=True)
        for chunk in parse_sse_lines(response):
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                print(content, end="", flush=True)
        print()
        return
    data = post_chat(payload, args=args).json()
    if args.raw:
        print_json(data)
        return
    msg = extract_message(data)
    print(msg.get("content", ""))


def cmd_gui(_: argparse.Namespace) -> None:
    reserved_feature("GUI/computer-use API")


def cmd_doctor(args: argparse.Namespace) -> None:
    report: Dict[str, Any] = {
        "version": __version__,
        "config_path": str(CONFIG_PATH),
        "base_url": api_base(),
        "has_api_key": bool(get_api_key(args, required=False)),
        "checks": [],
    }
    try:
        r = requests.get(api_base(), timeout=min(timeout(), 20))
        report["checks"].append({"name": "base_url_reachable", "ok": r.status_code < 500, "status_code": r.status_code})
    except Exception as exc:
        report["checks"].append({"name": "base_url_reachable", "ok": False, "error": repr(exc)})
    if args.live and report["has_api_key"]:
        try:
            payload = {"model": args.model or get_config_value("default_text_model"), "messages": [{"role": "user", "content": "Reply with OK only."}], "max_tokens": 8}
            data = post_chat(payload, args=args).json()
            message = extract_message(data)
            response_text = message.get("content") or message.get("reasoning_content") or ""
            report["checks"].append({
                "name": "chat_completion",
                "ok": bool(response_text),
                "model": payload["model"],
                "response": response_text,
                "has_content": bool(message.get("content")),
                "has_reasoning_content": bool(message.get("reasoning_content")),
            })
        except Exception as exc:
            report["checks"].append({"name": "chat_completion", "ok": False, "error": repr(exc)})
    print_json(report)


def add_common_api_key_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-key", help="Override API key for this command")


def add_chat_args(s: argparse.ArgumentParser) -> None:
    add_common_api_key_arg(s)
    s.add_argument("text", nargs="?")
    s.add_argument("--text-file")
    s.add_argument("--message", action="append", help="Message item. Accepts 'role:content' or plain user content. Can be repeated.")
    s.add_argument("--messages-file", help="JSON messages array file, or '-' for stdin")
    s.add_argument("--model")
    s.add_argument("--system")
    s.add_argument("--temperature", type=float)
    s.add_argument("--max-tokens", type=int)
    s.add_argument("--thinking", action="store_true")
    s.add_argument("--budget-tokens", type=int, default=4096)
    s.add_argument("--json-mode", action="store_true")
    s.add_argument("--stream", action="store_true")
    s.add_argument("--output", choices=["text", "json"], default="text")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_chat)


def add_tool_call_args(s: argparse.ArgumentParser) -> None:
    add_common_api_key_arg(s)
    s.add_argument("text", nargs="?")
    s.add_argument("--text-file")
    s.add_argument("--model")
    s.add_argument("--tools-file", required=True)
    s.add_argument("--tool-choice", default="auto")
    s.add_argument("--thinking", action="store_true")
    s.add_argument("--budget-tokens", type=int, default=4096)
    s.add_argument("--run", action="store_true", help="Reserved for future local tool execution loop")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_tool_call)


def add_search_args(s: argparse.ArgumentParser) -> None:
    add_common_api_key_arg(s)
    s.add_argument("text", nargs="?")
    s.add_argument("--text-file")
    s.add_argument("--model")
    s.add_argument("--forced", action="store_true", help="Force MiMo web_search via official force_search field")
    s.add_argument("--max-keyword", type=int, help="Maximum search keywords for one request")
    s.add_argument("--limit", type=int, help="Maximum search results per keyword")
    s.add_argument("--country", help="Approximate user country, e.g. China")
    s.add_argument("--region", help="Approximate user region/province, e.g. Hubei")
    s.add_argument("--city", help="Approximate user city, e.g. Wuhan")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_web_search)


def add_multimodal_common(s: argparse.ArgumentParser) -> None:
    add_common_api_key_arg(s)
    s.add_argument("--model")
    s.add_argument("--raw", action="store_true")


def add_tts_args(s: argparse.ArgumentParser) -> None:
    add_common_api_key_arg(s)
    s.add_argument("text", nargs="?")
    s.add_argument("--text-file")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--model")
    s.add_argument("--voice", choices=PRESET_VOICES, help=f"Preset voice ({', '.join(PRESET_VOICES)})")
    s.add_argument("--format", default="wav", choices=["wav", "mp3", "opus"], help="Audio output format (ignored when --stream uses pcm16)")
    s.add_argument("--context", help="Natural language style control / director mode (replaces --instruction)")
    s.add_argument("--instruction", help="[Deprecated] Use --context instead")
    s.add_argument("--sing", action="store_true", help="Prefix text with MiMo singing style tag")
    s.add_argument("--stream", action="store_true", help="Stream audio (mimo-v2.5-tts low-latency; output as wav from pcm16)")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_tts)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mimo", description="Xiaomi MiMo API CLI")
    p.add_argument("--version", action="version", version=f"mimo {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("models", help="Show documented models and capability map")
    s.set_defaults(func=cmd_models)

    auth = sub.add_parser("auth", help="Manage saved MiMo credentials")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    s = auth_sub.add_parser("login", help="Save API key")
    s.add_argument("--api-key")
    s.add_argument("--base-url")
    s.set_defaults(func=cmd_auth_login)
    s = auth_sub.add_parser("status", help="Show auth status")
    add_common_api_key_arg(s)
    s.set_defaults(func=cmd_auth_status)
    s = auth_sub.add_parser("logout", help="Remove saved API key")
    s.set_defaults(func=cmd_auth_logout)

    cfg = sub.add_parser("config", help="Manage mimo-cli configuration")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    s = cfg_sub.add_parser("show", help="Show configuration")
    s.set_defaults(func=cmd_config_show)
    s = cfg_sub.add_parser("set", help="Set configuration key")
    s.add_argument("key")
    s.add_argument("value")
    s.set_defaults(func=cmd_config_set)
    s = cfg_sub.add_parser("unset", help="Unset configuration key")
    s.add_argument("key")
    s.set_defaults(func=cmd_config_unset)

    s = sub.add_parser("doctor", help="Check local config and optional live API connectivity")
    add_common_api_key_arg(s)
    s.add_argument("--live", action="store_true", help="Run a tiny live chat completion test")
    s.add_argument("--model")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("chat", help="Basic text chat (legacy alias for text chat)")
    add_chat_args(s)
    s = sub.add_parser("tool-call", help="Function tool calling inspection (legacy alias for text tool-call)")
    add_tool_call_args(s)
    s = sub.add_parser("web-search", help="MiMo built-in web search (legacy alias for search query)")
    add_search_args(s)

    text = sub.add_parser("text", help="Text generation and tool-calling")
    text_sub = text.add_subparsers(dest="text_command", required=True)
    s = text_sub.add_parser("chat", help="Chat completion")
    add_chat_args(s)
    s = text_sub.add_parser("tool-call", help="Function tool calling inspection")
    add_tool_call_args(s)

    search = sub.add_parser("search", help="Web search")
    search_sub = search.add_subparsers(dest="search_command", required=True)
    s = search_sub.add_parser("query", help="Search the web through MiMo web_search tool")
    add_search_args(s)

    s = sub.add_parser("image-understand", help="Image understanding (legacy alias for vision image)")
    s.add_argument("image")
    s.add_argument("prompt")
    add_multimodal_common(s)
    s.set_defaults(func=cmd_image_understand)
    s = sub.add_parser("audio-understand", help="Audio understanding (legacy alias for vision audio)")
    s.add_argument("audio")
    s.add_argument("prompt")
    add_multimodal_common(s)
    s.set_defaults(func=cmd_audio_understand)
    s = sub.add_parser("video-understand", help="Video understanding (legacy alias for vision video)")
    s.add_argument("video")
    s.add_argument("prompt")
    add_multimodal_common(s)
    s.set_defaults(func=cmd_video_understand)

    vision = sub.add_parser("vision", help="Image/audio/video understanding")
    vision_sub = vision.add_subparsers(dest="vision_command", required=True)
    s = vision_sub.add_parser("image", help="Image understanding")
    s.add_argument("image")
    s.add_argument("prompt", nargs="?", default="Describe this image.")
    add_multimodal_common(s)
    s.set_defaults(func=cmd_image_understand)
    s = vision_sub.add_parser("audio", help="Audio understanding")
    s.add_argument("audio")
    s.add_argument("prompt", nargs="?", default="Describe this audio.")
    add_multimodal_common(s)
    s.set_defaults(func=cmd_audio_understand)
    s = vision_sub.add_parser("video", help="Video understanding")
    s.add_argument("video")
    s.add_argument("prompt", nargs="?", default="Describe this video.")
    add_multimodal_common(s)
    s.set_defaults(func=cmd_video_understand)

    s = sub.add_parser("tts", help="Built-in voice TTS (legacy alias for speech synthesize)")
    add_tts_args(s)
    s = sub.add_parser("tts-voice-design", help="Voice design TTS (legacy alias for speech voice-design)")
    add_common_api_key_arg(s)
    s.add_argument("voice_prompt")
    s.add_argument("text", nargs="?")
    s.add_argument("--text-file")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--format", default="wav", choices=["wav", "mp3", "opus"])
    s.add_argument("--context", help="Voice description / director mode (overrides voice_prompt)")
    s.add_argument("--optimize-text-preview", action="store_true")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_tts_voice_design)
    s = sub.add_parser("tts-voice-clone", help="Voice clone TTS (legacy alias for speech voice-clone)")
    add_common_api_key_arg(s)
    s.add_argument("voice_sample")
    s.add_argument("text", nargs="?")
    s.add_argument("--text-file")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--format", default="wav", choices=["wav", "mp3", "opus"])
    s.add_argument("--context", help="Director mode style control instructions")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_tts_voice_clone)

    speech = sub.add_parser("speech", help="Speech synthesis")
    speech_sub = speech.add_subparsers(dest="speech_command", required=True)
    s = speech_sub.add_parser("synthesize", aliases=["synth"], help="Built-in voice TTS")
    add_tts_args(s)
    s = speech_sub.add_parser("voice-design", help="Design a new voice from prompt")
    add_common_api_key_arg(s)
    s.add_argument("voice_prompt")
    s.add_argument("text", nargs="?")
    s.add_argument("--text-file")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--format", default="wav", choices=["wav", "mp3", "opus"])
    s.add_argument("--context", help="Voice description / director mode (overrides voice_prompt)")
    s.add_argument("--optimize-text-preview", action="store_true")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_tts_voice_design)
    s = speech_sub.add_parser("voice-clone", help="Clone a voice from local audio sample")
    add_common_api_key_arg(s)
    s.add_argument("voice_sample")
    s.add_argument("text", nargs="?")
    s.add_argument("--text-file")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--format", default="wav", choices=["wav", "mp3", "opus"])
    s.add_argument("--context", help="Director mode style control instructions")
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_tts_voice_clone)
    s = speech_sub.add_parser("feishu-send", help="Send audio file as Feishu voice message")
    s.add_argument("audio_file", help="Path to audio file (wav/mp3/opus)")
    s.add_argument("receive_id_type", choices=["open_id", "chat_id"], help="Feishu receive ID type")
    s.add_argument("receive_id", help="Feishu receive ID (open_id or chat_id)")
    s.set_defaults(func=cmd_feishu_send_audio)
    s = speech_sub.add_parser("transcribe", help="Speech recognition (ASR) via mimo-v2.5-asr")
    add_common_api_key_arg(s)
    s.add_argument("audio", help="Audio file path (wav or mp3, max 10MB base64)")
    s.add_argument("--language", choices=["auto", "zh", "en"], default="auto", help="Recognition language (default: auto-detect)")
    s.add_argument("--stream", action="store_true", help="Stream transcription text as it is generated")
    s.add_argument("--raw", action="store_true", help="Print the full raw API response")
    s.set_defaults(func=cmd_asr_transcribe)

    image = sub.add_parser("image", help="Image generation reserved namespace")
    image_sub = image.add_subparsers(dest="image_command", required=True)
    s = image_sub.add_parser("generate", help="Reserved text-to-image command")
    s.add_argument("prompt", nargs="?")
    s.set_defaults(func=cmd_image_generate)

    music = sub.add_parser("music", help="Music generation reserved namespace")
    music_sub = music.add_subparsers(dest="music_command", required=True)
    s = music_sub.add_parser("generate", help="Reserved text-to-music command")
    s.add_argument("--prompt")
    s.add_argument("--lyrics")
    s.set_defaults(func=cmd_music_generate)

    gui = sub.add_parser("gui", help="GUI/computer-use reserved namespace")
    gui.set_defaults(func=cmd_gui)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
    except NotYetDocumentedError as e:
        print(f"Reserved: {e}", file=sys.stderr)
        raise SystemExit(3)
    except MimoError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
