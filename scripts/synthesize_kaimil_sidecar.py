#!/usr/bin/env python3
"""Generate VAMP speech with local MeloTTS + OpenVoice kAImil conversion.

This script is intended to run under .venv-openvoice (Python 3.10). It prints a
single JSON object to stdout so the Flask app can call it as a sidecar.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import torch
from melo.api import TTS

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def synthesize(text: str, voice_name: str, speaker_id: int, speed: float, pitch: float) -> dict:
    from backend.llm.voice_cloner import VoiceCloner

    cache_dir = PROJECT_ROOT / "cache" / "voice"
    cache_dir.mkdir(parents=True, exist_ok=True)

    key = hashlib.md5(f"{voice_name}|{speaker_id}|{speed}|{pitch}|{text}".encode("utf-8")).hexdigest()
    base_path = cache_dir / f"melo_base_{key}.wav"
    raw_path = cache_dir / f"kaimil_raw_{key}.wav"
    output_path = cache_dir / f"kaimil_{key}.wav"
    embedding_path = cache_dir / f"{voice_name}_embedding.pt"
    src_se_path = PROJECT_ROOT / "models" / "openvoice_v2" / "base_speakers" / "ses" / "en-default.pth"

    if output_path.exists():
        return {"success": True, "path": str(output_path), "cached": True, "engine": "openvoice_sidecar"}

    if not embedding_path.exists():
        raise FileNotFoundError(f"Missing trained embedding: {embedding_path}")
    if not src_se_path.exists():
        raise FileNotFoundError(f"Missing source speaker embedding: {src_se_path}")

    tts = TTS(language="EN", device="cpu")
    tts.tts_to_file(text, speaker_id, str(base_path), speed=speed, quiet=True)

    cloner = VoiceCloner()
    cloner._load_models()
    src_se = torch.load(str(src_se_path), map_location="cpu")
    tgt_se = torch.load(str(embedding_path), map_location="cpu")
    cloner.tone_converter.convert(
        str(base_path),
        src_se=src_se,
        tgt_se=tgt_se,
        output_path=str(raw_path),
        message="@VAMP",
    )

    if pitch and abs(pitch - 1.0) > 0.01:
        # Pitch the converted voice down without keeping the chipmunk register.
        # asetrate changes pitch; atempo brings duration closer to natural pace.
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-y",
                "-i",
                str(raw_path),
                "-af",
                f"asetrate=24000*{pitch},aresample=24000,atempo={1 / pitch}",
                str(output_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        raw_path.replace(output_path)

    return {"success": True, "path": str(output_path), "cached": False, "engine": "openvoice_sidecar"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--voice-name", default="Conversational kAImil")
    parser.add_argument("--speaker-id", type=int, default=0)
    parser.add_argument("--speed", type=float, default=0.90)
    parser.add_argument("--pitch", type=float, default=0.86)
    args = parser.parse_args()

    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = synthesize(args.text, args.voice_name, args.speaker_id, args.speed, args.pitch)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e), "engine": "openvoice_sidecar"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
