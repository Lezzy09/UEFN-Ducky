# Video Attachments v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Background frame/transcript preparation on drop, model-aware image limits from provider data, ffmpeg shipped inside the app, and audio transcription for videos.

**Architecture:** Builds on branch `feat/video-attachments` (v1 complete). New backend modules `backend/agent/video/prep.py` and `audio.py`; `limits.media_limits_for(provider, model)` replaces fixed limits; `ModelInfo` gains media fields filled by provider plugins (separate repos). ffmpeg is fetched and SHA-checked at build time and embedded under `tools/ffmpeg`.

**Tech Stack:** Python (pytest), React/TS (vitest), PyInstaller spec, ffmpeg/ffprobe, OpenAI transcription via existing `backend/voice/transcription.py`.

**Spec:** `docs/superpowers/specs/2026-10-06-video-attachments-v2-design.md` (v2, binding) on top of `docs/superpowers/specs/2026-10-05-video-attachments-design.md`.

## Global Constraints

- Worktree only: `C:/Users/PC/Documents/UEFN DUCKY APP et Plugin/UEFN-Ducky-video`, branch `feat/video-attachments`. Never run git in `.../UEFN-Ducky` (the user's main checkout). Plugin work happens in `C:/Users/PC/Documents/UEFN DUCKY APP et Plugin/Plugin DUCKY/uefn-plugin-<name>` on a new branch `feat/model-media-limits` in each repo.
- Auto limits: settings `video_frames_per_video` and `max_images_per_message` accept `0 = Auto` (new default 0); manual ranges stay 1–40 and 1–100. Provider default request image max: `anthropic` 100, `openai` 500, `gemini` 3000, any other 20. Auto frames per video = `min(20, request_max)`; Auto images per message = `request_max`.
- Transcription: OpenAI only via `transcribe_audio(b64, "audio/mpeg")`; MP3 mono 16 kHz 48 kb/s; skip if MP3 > 24 MiB; never blocks sending; only when the recipient gets frames (not Gemini native).
- Notes (exact English strings): `No transcript — needs an OpenAI key`, `No audio track`, `Audio too long to transcribe`, `Transcription failed: <error>`.
- Transcript block in model input: `Transcript of video "<name>":\n<text>`.
- Bundled ffmpeg path inside the app: `tools/ffmpeg/` (ffmpeg.exe, ffprobe.exe, *.dll, LICENSE.txt). Same pinned archive/SHA as `ffmpeg_install` constants.
- Never silently drop a video (v1 rule still binding). UI copy English. Commits: no `Co-Authored-By`. Revert `ducky_app/frontend/ui_web/web/tsconfig.tsbuildinfo` before committing.
- Baselines: pytest 9 pre-existing failures (store/test_phase3 ×2, test_upgrade_boot ×1, test_atomic_json ×1, test_cursor_model_list ×5); vitest all pass; tsc 0 errors; eslint 1 pre-existing error (ChatPane textarea `style`).

---

### Task V1: Model-aware media limits

**Files:**
- Modify: `ducky_app/backend/agent/model_fetch.py` (`ModelInfo`)
- Modify: `ducky_app/backend/agent/video/limits.py`, `budget.py`, `send.py`, `routing.py`
- Modify: `ducky_app/backend/agent/attachments.py` (current-message image cap), `ducky_app/frontend/ui_web/agent_modes.py`, `ducky_app/backend/agent/runner.py` (pass model to budget/send)
- Modify: `ducky_app/frontend/settings.py` (defaults 0), `ducky_app/frontend/ui_web/panel_api_video.py` (accept 0), `web/src/views/settings/VideosTab.tsx` (Auto)
- Tests: `backend/agent/video/test_limits.py`, `test_budget.py` (exists from v1 fix wave — extend), `test_send.py`, `frontend/ui_web/test_panel_api_video.py`, `VideosTab.test.tsx`

**Interfaces (produces):**
- `ModelInfo.max_images: int | None = None`, `ModelInfo.supports_video: bool | None = None`, `ModelInfo.supports_audio: bool | None = None`
- `limits.PROVIDER_IMAGE_MAX = {"anthropic": 100, "openai": 500, "gemini": 3000}`, `limits.DEFAULT_IMAGE_MAX = 20`
- `limits.request_image_max(provider: str, model: str) -> int` (ModelInfo.max_images if > 0, else table, else 20)
- `limits.media_limits_for(provider: str, model: str) -> VideoLimits` (same dataclass; resolves Auto=0 per Global Constraints; `max_bytes` from settings as before)
- `video_limits()` stays (provider-agnostic: Auto resolves with provider "" → 20/20) for callers without a model.
- `routing.needs_frames(..., provider, external, model: str = "")`: Gemini native also requires `ModelInfo.supports_video is not False`.
- `budget.apply_media_budget(per_message, *, provider, model: str = "")` uses `request_image_max(provider, model)`.
- `send.prepare_video_frames(..., model: str = "")`, `send.backfill_history_frames(..., model: str = "")` use `media_limits_for`.

- [ ] Step 1: failing tests — `request_image_max` table + ModelInfo override (monkeypatch `backend.agent.model_fetch.get_model_info`); `media_limits_for` Auto vs manual; budget with model max 5 keeps only frames that fit; prepare_video_frames frame count follows model (e.g. openai → 20, a model with max_images=8 → 8); `needs_frames` gemini with `supports_video=False` → True; panel `set_video_settings({"video_frames_per_video": 0})` stores 0 and `get_video_settings` reports `0` plus `"auto": {"frames_per_video": ..., "max_images_per_message": ...}` resolved for provider "" ; VideosTab shows an "Auto" checkbox per field (checked when value 0; unchecking sets the last manual value or the default 20/40).
- [ ] Step 2: run, see RED.
- [ ] Step 3: implement. Thread `model` (turn model id) from `agent_modes.run_message` (`turn_model`) and from the runner (find the model id on the runner config; if absent, pass `""`) into `prepare_video_frames`, `backfill_history_frames`, `apply_media_budget`; the current-message image cap in `parse_attachment_dicts(current=True)` uses `media_limits_for(provider, model)` when called from `prepare_outgoing_user_message` (has provider/model) — add optional `provider`/`model` keywords to `parse_attachment_dicts` and pass them where known.
- [ ] Step 4: GREEN + `ducky_app/backend/agent ducky_app/frontend` suites vs baseline; vitest VideosTab; tsc.
- [ ] Step 5: commit `feat(video): image limits follow the model`.

---

### Task V2: Audio extraction + transcription

**Files:**
- Create: `ducky_app/backend/agent/video/audio.py`, `ducky_app/backend/agent/video/test_audio.py`
- Modify: `message_attachment.py` (`transcript: str = ""`), `attachments.py` (`_parse_video` reads `raw["transcript"]`, str, cap 200_000 chars), `multimodal_content.py` (transcript block), `send.py` (transcribe at send/backfill when missing), `conversation_attachments.py` (persist/hydrate keep `transcript`, `transcript_note`), `agent_modes.py` (external agents: append transcript after the `Video file:` hint), `send.runtime_video_dict` (carry `transcript`)
- Tests: `test_audio.py`, `test_multimodal_video.py`, `test_send.py`

**Interfaces (produces):**
```python
@dataclass(frozen=True)
class TranscriptResult:
    text: str          # "" when unavailable
    note: str          # "" on success, else one of the Global Constraints notes

def has_audio(ffprobe: Path, video: Path, timeout_s: float = 15) -> bool
def extract_mp3(ffmpeg: Path, video: Path, out: Path, timeout_s: float = 120) -> Path
def transcribe_video(video: Path) -> TranscriptResult   # uses ensure_installed(); writes/reads cache <video>.transcript.txt / <video>.transcript-note.txt
def transcript_paths(video: Path) -> tuple[Path, Path]  # (text file, note file) next to the video
```
`transcribe_video` order: cache hit → return; `has_audio` False → note "No audio track"; extract mp3 to `<video>.audio.mp3` (deleted after); size > 24 MiB → "Audio too long to transcribe"; call `backend.voice.transcription.transcribe_audio(base64, "audio/mpeg")`; `ok False` with key/gateway message → "No transcript — needs an OpenAI key" when the error text mentions "key" or "gateway", else `Transcription failed: <error>`; write cache files; ffmpeg errors map to `Transcription failed: …` (never raise VideoError — transcription is best-effort). ffmpeg args: `-nostdin -v error -i <video> -vn -ac 1 -ar 16000 -b:a 48k -f mp3 -y <out>`; ffprobe: `-v error -select_streams a -show_entries stream=index -of csv=p=0`. Use `frames._runner` for subprocesses (same no-window/errors handling).

- `send.prepare_video_frames`: after frames for a row, if `"transcript_note" not in row`, run `transcribe_video` (push status "Transcribing audio from <name>…") and set `row["transcript"]` / `row["transcript_note"]`. Same in `backfill_history_frames` (mark changed).
- Builders: for a video sent as frames (non-native), if `att.transcript` emit `{"type":"text","text": f'Transcript of video "{att.name}":\n{att.transcript}'}` (OpenAI/Anthropic) / `Part.from_text(...)` (Gemini) right before its frames; Gemini native → no transcript; omitted videos → no transcript.

- [ ] Step 1: failing tests (fake `_runner` + fake `transcribe_audio`): no audio → note; ok → text cached, second call doesn't re-run ffmpeg/transcribe; no key → exact note; >24 MiB → note; ffmpeg rc≠0 → "Transcription failed"; builders include the block for frames path and not for Gemini native; prepare_video_frames sets transcript fields; external hint includes transcript; hydrate/persist round-trip keeps transcript.
- [ ] Step 2–4: RED, implement, GREEN + suites. Real-ffmpeg check: with `DUCKY_FFMPEG_DIR` (controller provides) generate a 2 s video with a sine tone (`-f lavfi -i sine=frequency=440:duration=2`) and assert `has_audio` True and `extract_mp3` writes a non-empty file (transcribe faked).
- [ ] Step 5: commit `feat(video): transcribe video audio for frame-based models`.

---

### Task V3: Background preparation on drop

**Files:**
- Create: `ducky_app/backend/agent/video/prep.py`, `test_prep.py`
- Modify: `frontend/ui_web/panel_api_video.py` (start prep in `stage_video_attachment`; new `get_video_prep_status(staged_ids: list[str] | None = None)`; add to the PanelApi method registry test list), `conversation_attachments.persist_message_attachments` (copy sibling prep files), `web/src/types/panel.ts`, `web/src/hooks/useComposerAttachments.ts`, `web/src/components/ComposerAttachmentChips.tsx` (+ tests)

**Interfaces (produces):**
```python
def start_prep(staged_id: str, *, frames: int, transcribe: bool) -> dict  # idempotent per staged_id; returns status
def prep_status(staged_id: str) -> dict
# status: {"state": "queued"|"extracting"|"transcribing"|"ready"|"error", "frames_done": int,
#          "frames_total": int, "transcript": "ok"|"none"|"skipped", "transcript_note": str, "error": str}
```
- One daemon worker thread per job, at most 2 concurrent jobs (semaphore). Worker: `ensure_installed()` (bundled or download), then `extract_frames(staged_path, frames)` — report progress by counting existing `frame_paths(staged_path, frames)` files from a polling status read (no callback needed) — then, if `transcribe`, `audio.transcribe_video(staged_path)`. Any `VideoError` → state "error" with message. `transcribe=False` → transcript "skipped".
- `stage_video_attachment`: decide `needs = _video_needs_ffmpeg(...)` (existing; now also pass the conv's model); if needs → `start_prep(staged_id, frames=media_limits_for(provider, model).frames_per_video (group/unknown → video_limits()), transcribe=True)`; return `prep` status in the response; if not needs → `prep: {"state": "ready", ...transcript "skipped"}`.
- `persist_message_attachments` video branch: after copying the video, copy every sibling `Path(att.file_path).parent.glob(Path(att.file_path).name + ".*")` (frames `*.fNN-KK.jpg`, `*.transcript.txt`, `*.transcript-note.txt`) to `full.with_name(full.name + suffix)` where suffix = sibling name minus the staged name; ignore copy errors for siblings (they are a cache — the send path re-extracts/re-transcribes).
- Frontend: video ComposerAttachment gains `prep?: VideoPrepStatusDto`; after staging, poll `get_video_prep_status([ids])` every 700 ms while any video is not ready/error (replaces the ffmpeg-status poll; keep install/download progress if state is "queued" and ffmpeg is installing — show "Preparing ffmpeg…"). Chip labels: `Extracting frames 7/20`, `Transcribing audio…`, `Ready`, error text; when ready and `transcript_note` non-empty show it as a small secondary line (title + text). `hasPendingVideos` true until state ready or error. Retry on error re-calls `stage`? No — add `retry_video_prep(staged_id)` API that restarts the job.

- [ ] Steps: failing tests (prep with fake extract/transcribe: progress, ready, error, idempotent start, concurrency cap; panel stage starts prep only when needed; persist copies siblings with renamed prefix and extract_frames then reports no ffmpeg runs; hook polls prep status and maps labels; chips show progress/note) → RED → implement → GREEN + suites + vitest + tsc.
- [ ] Commit `feat(video): prepare frames and transcript in the background on drop`.

---

### Task V4: Ship ffmpeg inside the app

**Files:**
- Create: `build/fetch_ffmpeg.py`, `build/test_fetch_ffmpeg.py`
- Modify: `build/build_exes.py` (call fetch before PyInstaller), `build/unified.spec` (datas `tools/ffmpeg`), `.gitignore` (`build/ffmpeg-bundle/`), `ducky_app/backend/agent/video/ffmpeg_install.py` (bundled lookup, `status()["bundled"]`, `remove()` never touches bundled), `test_ffmpeg_install.py`, `web/src/views/settings/VideosTab.tsx` (+test), `web/src/types/panel.ts` (`FfmpegStatusDto.bundled?: boolean`), `THIRD_PARTY_NOTICES.md`

**Interfaces:**
- `fetch_ffmpeg.ensure_bundle(dest: Path = build/ffmpeg-bundle) -> Path`: if `dest/.installed` matches `FFMPEG_VERSION` → return; else download `FFMPEG_URL` with the same streaming + SHA-256 check and member filter as `ffmpeg_install` (import and reuse `_wanted_member`, `FFMPEG_*` constants; refactor a shared `download_verified(url, sha, dest_zip)` + `extract_members(zip, dest)` into `ffmpeg_install` so both use it), write marker, return dest. Raise on mismatch (build fails loudly).
- `ffmpeg_install.bundled_dir() -> Path | None`: `packaged_data_root() / "tools" / "ffmpeg"` when packaged and both exes exist; `binaries()` returns it first.
- unified.spec: for each file in `ROOT/build/ffmpeg-bundle` (except `.installed`) append `(str(path), "tools/ffmpeg")`; if the folder is missing, raise RuntimeError("run build/fetch_ffmpeg.py") — build_exes calls it first so this only fires on manual PyInstaller runs.

- [ ] Steps: failing tests (fetch with fake download: verified extract, reuse when marker matches, mismatch raises; `binaries()` prefers bundled when `packaged_data_root` patched; status bundled; remove leaves bundled; VideosTab shows "Included with UEFN-Ducky (<version>)" and no buttons when bundled) → RED → implement → GREEN.
- [ ] Real check: run `py build/fetch_ffmpeg.py` once (downloads 67 MB, verifies) — controller may point `DUCKY_FFMPEG_ZIP` env var at an already-downloaded zip to skip the network (support it in `ensure_bundle`: if set and the file's SHA matches, use it).
- [ ] Update THIRD_PARTY_NOTICES: move FFmpeg to "Bundled dependencies" (LGPL-2.1-or-later, BtbN win64-lgpl-shared, shipped in `tools/ffmpeg/` with its `LICENSE.txt`, run as a separate process; source at ffmpeg.org).
- [ ] Commit `feat(video): ship ffmpeg inside the app`.

---

### Task V5: Provider plugins report media limits (6 repos)

**Repos:** `Plugin DUCKY/uefn-plugin-{anthropic,openai,google,ollama,kimi,spacexai}` — each on new branch `feat/model-media-limits` from its `main`.

For each plugin's model fetch (`backend/model_fetch.py`), pass the new fields through `_model_info(...)` (which already drops fields an older host lacks):
- **anthropic** `_anthropic_info_from_item`: `caps["image_input"]` → `max_images` from the first int among keys `max_images`, `max_count`, `max_images_per_request` (else None); `supports_video`/`supports_audio` from `caps["video_input"]["supported"]` / `caps["audio_input"]["supported"]` when present (else None).
- **google** `_gemini_info_from_model`: `supports_video` / `supports_audio` via a modality scan like `_record_mentions_image_modalities` (generalize to `_record_mentions_modality(record, word)` with words "video"/"audio"); `max_images` from record keys `max_images`/`maxImages` if present.
- **openai**: `supports_audio = "audio" in features or "audio_input" in features` when features known; `max_images` from record keys `max_images`/`max_image_inputs` if present.
- **ollama**: `supports_video`/`supports_audio` from `caps` list words; `max_images` None.
- **kimi**, **spacexai**: `max_images` from record keys `max_images` if present; modalities via `input_modalities` list if present.
Each: a focused test in the plugin's existing test file for model fetch (create `backend/test_model_media_fields.py` where none exists) using a fabricated API record with and without the fields, run with the plugin's own conftest (`python -m pytest backend -q` from the plugin root with the host venv). Commit per repo: `feat: report image/video/audio limits from the model API`. No push.

---

### Task V6: Notices, full verification, build

- [ ] Full suites vs baselines (pytest, vitest, tsc, lint).
- [ ] `py build/build_exes.py --no-bump` with `PYTHONUTF8=1` → verify `dist/UEFN-Ducky-<ver>/_internal/tools/ffmpeg/ffmpeg.exe` exists and runtime-smoke ok. Revert build-generated tracked files afterwards (`git checkout --` the files the build touched).
- [ ] Commit any remaining doc changes.
