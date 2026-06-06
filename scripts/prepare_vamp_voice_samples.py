#!/usr/bin/env python3
"""
Prepare local VAMP voice-training snippets from a promo video or separated vocal stem.

The script deliberately keeps the pipeline simple and inspectable:
1. Prefer an existing Demucs vocal stem when present.
2. Use ffmpeg for mono conversion, gentle speech cleanup, and loudness normalization.
3. Use librosa energy splitting to cut natural speech regions.
4. Export short WAV snippets into data/voice_samples for the local OpenVoice path.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "VAMP promo.mp4"
DEFAULT_DEMUCS_STEM = PROJECT_ROOT / "data" / "voice_work" / "demucs" / "htdemucs" / "VAMP promo" / "vocals.wav"
DEFAULT_WORK_DIR = PROJECT_ROOT / "data" / "voice_work" / "kaimil"
DEFAULT_SAMPLE_DIR = PROJECT_ROOT / "data" / "voice_samples"


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(str(part) for part in cmd))
    subprocess.run(cmd, check=True)


def choose_source(input_file: Path, vocal_stem: Path | None) -> tuple[Path, str]:
    if vocal_stem and vocal_stem.exists():
        return vocal_stem, "demucs_vocals"
    if DEFAULT_DEMUCS_STEM.exists():
        return DEFAULT_DEMUCS_STEM, "demucs_vocals"
    if input_file.exists():
        return input_file, "original_media"
    raise FileNotFoundError(f"No usable source found: {input_file}")


def clean_audio(source: Path, output: Path, sample_rate: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep processing conservative. Heavy denoise can damage speaker identity.
    filters = (
        "highpass=f=75,"
        "lowpass=f=7800,"
        "afftdn=nf=-22,"
        "loudnorm=I=-20:TP=-2:LRA=11"
    )
    run([
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-af",
        filters,
        str(output),
    ])


def merge_intervals(intervals: np.ndarray, sr: int, max_gap_s: float) -> list[tuple[int, int]]:
    if len(intervals) == 0:
        return []
    max_gap = int(max_gap_s * sr)
    merged: list[tuple[int, int]] = []
    cur_start, cur_end = int(intervals[0][0]), int(intervals[0][1])
    for start, end in intervals[1:]:
        start, end = int(start), int(end)
        if start - cur_end <= max_gap:
            cur_end = max(cur_end, end)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = start, end
    merged.append((cur_start, cur_end))
    return merged


def split_long_region(y: np.ndarray, start: int, end: int, sr: int, max_len_s: float) -> list[tuple[int, int]]:
    max_len = int(max_len_s * sr)
    if end - start <= max_len:
        return [(start, end)]

    pieces: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        target = min(cursor + max_len, end)
        if target < end:
            search_start = max(cursor + int(4.0 * sr), target - int(2.0 * sr))
            search_end = min(end, target + int(2.0 * sr))
            if search_end > search_start:
                window = np.abs(y[search_start:search_end])
                frame = max(1, int(0.08 * sr))
                if len(window) > frame:
                    energies = np.convolve(window, np.ones(frame) / frame, mode="valid")
                    target = search_start + int(np.argmin(energies))
        pieces.append((cursor, target))
        cursor = target
    return pieces


def export_snippets(
    clean_wav: Path,
    output_dir: Path,
    prefix: str,
    min_len_s: float,
    max_len_s: float,
    top_db: int,
    replace: bool,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if replace:
        for old in output_dir.glob(f"{prefix}_*.wav"):
            old.unlink()

    y, sr = librosa.load(clean_wav, sr=None, mono=True)
    intervals = librosa.effects.split(y, top_db=top_db, frame_length=2048, hop_length=512)
    regions = merge_intervals(intervals, sr, max_gap_s=0.45)

    candidates: list[tuple[int, int]] = []
    for start, end in regions:
        # Add a tiny pad so consonants are not clipped.
        pad = int(0.08 * sr)
        start = max(0, start - pad)
        end = min(len(y), end + pad)
        for piece in split_long_region(y, start, end, sr, max_len_s=max_len_s):
            dur = (piece[1] - piece[0]) / sr
            if dur >= min_len_s:
                candidates.append(piece)

    manifest: list[dict] = []
    fade = int(0.035 * sr)
    for idx, (start, end) in enumerate(candidates, start=1):
        clip = np.array(y[start:end], dtype=np.float32)
        if len(clip) == 0:
            continue
        if fade > 0 and len(clip) > fade * 2:
            clip[:fade] *= np.linspace(0.0, 1.0, fade)
            clip[-fade:] *= np.linspace(1.0, 0.0, fade)
        peak = float(np.max(np.abs(clip)) or 1.0)
        if peak > 0.98:
            clip = clip / peak * 0.96

        out = output_dir / f"{prefix}_{idx:03d}.wav"
        sf.write(out, clip, sr, subtype="PCM_16")
        rms = float(math.sqrt(float(np.mean(np.square(clip)))) if len(clip) else 0.0)
        manifest.append({
            "file": str(out.relative_to(PROJECT_ROOT)),
            "start_s": round(start / sr, 3),
            "end_s": round(end / sr, 3),
            "duration_s": round((end - start) / sr, 3),
            "rms": round(rms, 6),
        })

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare VAMP voice samples from promo audio.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--vocal-stem", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_SAMPLE_DIR)
    parser.add_argument("--prefix", default="kaimil")
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--min-len", type=float, default=4.5)
    parser.add_argument("--max-len", type=float, default=14.0)
    parser.add_argument("--top-db", type=int, default=32)
    parser.add_argument("--replace", action="store_true", help="Remove old snippets with the same prefix first.")
    args = parser.parse_args()

    input_file = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    vocal_stem = args.vocal_stem
    if vocal_stem and not vocal_stem.is_absolute():
        vocal_stem = PROJECT_ROOT / vocal_stem

    source, source_kind = choose_source(input_file, vocal_stem)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    clean_wav = args.work_dir / "conversational_kaimil_clean.wav"
    clean_audio(source, clean_wav, args.sample_rate)

    manifest = export_snippets(
        clean_wav=clean_wav,
        output_dir=args.output_dir,
        prefix=args.prefix,
        min_len_s=args.min_len,
        max_len_s=args.max_len,
        top_db=args.top_db,
        replace=args.replace,
    )

    manifest_path = args.work_dir / "conversational_kaimil_manifest.json"
    payload = {
        "source": str(source.relative_to(PROJECT_ROOT)) if source.is_relative_to(PROJECT_ROOT) else str(source),
        "source_kind": source_kind,
        "clean_wav": str(clean_wav.relative_to(PROJECT_ROOT)),
        "output_dir": str(args.output_dir.relative_to(PROJECT_ROOT)),
        "snippets": manifest,
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    total = sum(item["duration_s"] for item in manifest)
    print(f"Prepared {len(manifest)} snippets, {total:.1f}s total.")
    print(f"Clean stem: {clean_wav}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
