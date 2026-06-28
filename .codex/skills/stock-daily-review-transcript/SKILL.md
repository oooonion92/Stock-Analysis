# Stock Daily Review Transcript

Use this skill when the user asks to process a newly downloaded daily stock-market review audio/video file into a polished Chinese text replay note, especially for files under `F:\Downloads\复盘文件` and outputs under `D:\OneDrive\Stock\Daily review`.

## Workflow

1. Locate the newest media file in `F:\Downloads\复盘文件`.
   - Prefer audio-only MP4 when both a video+audio file and audio-only file exist.
   - If several new files are present, use `LastWriteTime` and file size to identify the latest daily review file.
2. Transcribe the media with local `faster-whisper`.
   - Use the bundled Codex Python runtime when available.
   - Default model: `tiny`, because it is fast enough for daily replay drafts.
   - Use `medium` only when the user explicitly asks for higher transcription accuracy and accepts a slower run.
   - Copy the media into a workspace temp folder before transcription if the source path has non-ASCII characters or OneDrive/download paths are awkward.
3. Save intermediate transcription files inside the workspace, not the final OneDrive folder.
   - Suggested workspace folder:
     `D:\Projects\Stock Analysis\02_daily_replay\temp_audio_transcribe\YYYYMMDD`
   - Keep raw transcript and SRT there for debugging.
4. Split the transcript into readable chunks, usually 10-minute chunks.
   - Use chunks to preserve coverage during AI refinement.
   - Pay special attention to sectors the user repeatedly cares about: 光模块, PCB, 光纤, 锂电, 国产半导体, 存储, MLCC, 长鑫链, 算力芯片, 半导体设备.
5. Produce the polished note in Simplified Chinese.
   - No timestamps in the final polished note unless the user asks.
   - Segment by modules and sectors.
   - Preserve all substantive content and trading logic.
   - Clean obvious transcription errors conservatively; do not invent stock names when uncertain.
   - Put uncertain names into natural descriptions rather than overclaiming precision.
   - Add a concise summary at the end.
6. Final save behavior:
   - Save only the polished Markdown note to:
     `D:\OneDrive\Stock\Daily review\视频复盘转写`
   - Do not copy raw transcript, SRT, chunks, or media into OneDrive unless the user asks.
   - Name the final file:
     `YYYYMMDD_深度复盘_AI精修稿.md`

## Suggested Commands

Use `scripts/transcribe_latest_review.py` to locate and transcribe the latest review media:

```powershell
& '<python>' 'C:\Users\翀\.codex\skills\stock-daily-review-transcript\scripts\transcribe_latest_review.py' --date YYYYMMDD
```

The script prints the workspace output folder and generated transcript paths. After that, read the transcript or chunks, refine with AI, and save only the final Markdown note to OneDrive.

## Refinement Style

The final note should feel like a faithful, cleaned-up study record, not a short abstract. Use module headings such as:

- 市场总体
- 光模块、PCB 与光通信
- 存储、MLCC 与长鑫链
- 国产半导体
- 锂电、锂矿与高低切
- 其他方向和个股思路
- 交易纪律
- 精炼总结

For market/stock analysis, stay aligned with the user's `02_daily_replay` methodology: classify trade type first, then judge structure, market emotion/main-line status, and position sizing. Do not treat Chanlun structure alone as a buy reason.
