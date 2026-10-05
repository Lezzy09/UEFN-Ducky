"""Panel API: video uploads (staging), Settings → Videos, and the ffmpeg install."""

from __future__ import annotations

from typing import Any

import frontend.ui_web.panel_api as _pa


class PanelApiVideoMixin:
    def stage_video_attachment(
        self, conv_id: str = "", name: str = "", mime: str = "", data_base64: str = ""
    ) -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install
        from backend.agent.video.staging import stage_video

        try:
            staged = stage_video(str(name or ""), str(mime or ""), str(data_base64 or ""))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        needs = _video_needs_ffmpeg(str(conv_id or "").strip(), staged)
        ff = ffmpeg_install.start_install() if needs else ffmpeg_install.status()
        return {"ok": True, **staged, "needs_ffmpeg": needs, "ffmpeg": ff}

    def get_video_settings(self, conv_id: str = "") -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install
        from backend.agent.video import limits as L
        from backend.agent.video.limits import video_limits

        s = _pa.PanelSettings.load()
        lim = video_limits()
        return {
            "ok": True,
            "video_max_mb": lim.max_bytes // (1024 * 1024),
            "video_frames_per_video": L.clamp_auto(
                getattr(s, "video_frames_per_video", 0), *L.FRAMES_PER_VIDEO_RANGE, 0
            ),
            "max_images_per_message": L.clamp_auto(
                getattr(s, "max_images_per_message", 0), *L.MAX_IMAGES_PER_MESSAGE_RANGE, 0
            ),
            "auto": _auto_limits(str(conv_id or "").strip()),
            "ffmpeg": ffmpeg_install.status(),
        }

    def set_video_settings(self, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        from backend.agent.video import limits as L

        data = _pa._coerce_mapping(patch, label="video settings patch")
        s = _pa.PanelSettings.load()
        if "video_max_mb" in data:
            s.video_max_mb = L.clamp(data["video_max_mb"], *L.VIDEO_MAX_MB_RANGE, L.DEFAULT_VIDEO_MAX_MB)
        if "video_frames_per_video" in data:
            s.video_frames_per_video = L.clamp_auto(
                data["video_frames_per_video"], *L.FRAMES_PER_VIDEO_RANGE, 0
            )
        if "max_images_per_message" in data:
            s.max_images_per_message = L.clamp_auto(
                data["max_images_per_message"], *L.MAX_IMAGES_PER_MESSAGE_RANGE, 0
            )
        s.save()
        return self.get_video_settings()

    def get_ffmpeg_status(self) -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install

        return ffmpeg_install.status()

    def install_ffmpeg(self) -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install

        return ffmpeg_install.start_install()

    def remove_ffmpeg(self) -> dict[str, Any]:
        from backend.agent.video import ffmpeg_install

        return ffmpeg_install.remove()


def _video_needs_ffmpeg(conv_id: str, staged: dict[str, Any]) -> bool:
    """Gemini-only single chats with a small supported video never need ffmpeg."""
    from backend.agent.coding_agents.base import normalize_coding_agent
    from backend.agent.video.routing import needs_frames
    from frontend.ui_web import project_chats

    conv = project_chats.load_conversation(conv_id) if conv_id else None
    if conv is None or getattr(conv, "is_group", False):
        return True
    external = normalize_coding_agent(getattr(conv, "coding_agent", None) or "ducky") != "ducky"
    return needs_frames(
        staged["mime"],
        int(staged["size_bytes"]),
        provider=str(getattr(conv, "provider", "") or ""),
        external=external,
        model=str(getattr(conv, "model", "") or ""),
    )


def _auto_limits(conv_id: str) -> dict[str, int]:
    """What Auto resolves to: the chat's provider/model when known, else provider-agnostic."""
    from backend.agent.video.limits import AUTO_FRAMES_CAP, request_image_max
    from frontend.ui_web import project_chats

    provider = model = ""
    conv = project_chats.load_conversation(conv_id) if conv_id else None
    if conv is not None and not getattr(conv, "is_group", False):
        provider = str(getattr(conv, "provider", "") or "")
        model = str(getattr(conv, "model", "") or "")
    rmax = request_image_max(provider, model)
    return {"frames_per_video": min(AUTO_FRAMES_CAP, rmax), "max_images_per_message": rmax}
