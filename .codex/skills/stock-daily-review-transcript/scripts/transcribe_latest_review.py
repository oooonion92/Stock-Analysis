from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


DEFAULT_SOURCE = Path(r"F:\Downloads\复盘文件")
DEFAULT_WORKSPACE = Path(r"D:\Projects\Stock Analysis\02_daily_replay\temp_audio_transcribe")
MEDIA_EXTS = {".mp4", ".m4a", ".mp3", ".wav", ".aac", ".flac", ".mkv", ".mov"}


def newest_media(source: Path) -> Path:
    files = [p for p in source.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXTS]
    if not files:
        raise FileNotFoundError(f"No media files found in {source}")
    return max(files, key=lambda p: p.stat().st_mtime)


def format_ts(seconds: float) -> str:
    millis = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"


def write_chunks(segments: list[dict], chunk_dir: Path, minutes: int) -> None:
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_seconds = minutes * 60
    buckets: dict[int, list[str]] = {}
    for seg in segments:
        idx = int(seg["start"] // chunk_seconds)
        line = f"[{seg['start']:.2f}-{seg['end']:.2f}] {seg['text'].strip()}"
        buckets.setdefault(idx, []).append(line)
    for idx, lines in sorted(buckets.items()):
        start_min = idx * minutes
        end_min = start_min + minutes
        path = chunk_dir / f"chunk_{idx:02d}_{start_min:02d}-{end_min:02d}min.txt"
        path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe latest stock daily review media.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--chunk-minutes", type=int, default=10)
    args = parser.parse_args()

    source = Path(args.source)
    workspace = Path(args.workspace)
    media = newest_media(source)
    out_dir = workspace / args.date
    out_dir.mkdir(parents=True, exist_ok=True)

    local_media = out_dir / f"review_audio{media.suffix.lower()}"
    if media.resolve() != local_media.resolve():
        shutil.copy2(media, local_media)

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "Missing faster-whisper. Install it with: python -m pip install faster-whisper"
        ) from exc

    prompt = (
        "A股 复盘 证券 市场 情绪 主线 算力 半导体 国产半导体 存储 长鑫链 "
        "MLCC 光模块 PCB 光纤 CPO 磷化铟 锂电 锂矿 固态电池 半导体设备"
    )
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segment_iter, info = model.transcribe(
        str(local_media),
        language="zh",
        vad_filter=True,
        initial_prompt=prompt,
        beam_size=5,
    )
    segments = [
        {"start": s.start, "end": s.end, "text": s.text.strip()}
        for s in segment_iter
        if s.text.strip()
    ]

    transcript = out_dir / f"{args.date}_deep_review_audio_transcript_{args.model}.txt"
    srt = out_dir / f"{args.date}_deep_review_audio_transcript_{args.model}.srt"
    transcript.write_text("\n".join(seg["text"] for seg in segments), encoding="utf-8")

    srt_lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        srt_lines.extend(
            [
                str(i),
                f"{format_ts(seg['start'])} --> {format_ts(seg['end'])}",
                seg["text"],
                "",
            ]
        )
    srt.write_text("\n".join(srt_lines), encoding="utf-8")
    write_chunks(segments, out_dir / "chunks", args.chunk_minutes)

    print(f"media={media}")
    print(f"out_dir={out_dir}")
    print(f"transcript={transcript}")
    print(f"srt={srt}")
    print(f"segments={len(segments)} duration={getattr(info, 'duration', 0):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
