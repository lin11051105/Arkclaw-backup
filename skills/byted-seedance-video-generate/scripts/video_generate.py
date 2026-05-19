import argparse
import asyncio
import base64
import json
import mimetypes
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

API_KEY = (
    os.getenv("ARK_API_KEY")
    or os.getenv("MODEL_VIDEO_API_KEY")
    or os.getenv("MODEL_AGENT_API_KEY")
)
API_BASE = (
    os.getenv("ARK_BASE_URL")
    or os.getenv("MODEL_VIDEO_API_BASE")
    or "https://ark.cn-beijing.volces.com/api/v3"
).rstrip("/")
API_BASE = re.sub(r"/api/coding/(?:lite/|pro/)?v3$", "/api/v3", API_BASE)

DEFAULT_MODEL = "doubao-seedance-2-0-260128"

_MIME_MAP = {
    "image": {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".gif": "image/gif",
    },
    "video": {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
    },
    "audio": {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
    },
}

_ALLOWED_EXTENSIONS = set()
for _exts in _MIME_MAP.values():
    _ALLOWED_EXTENSIONS.update(_exts.keys())

_BLOCKED_PATH_PREFIXES = (
    "/etc/",
    "/proc/",
    "/sys/",
    "/dev/",
    "/run/",
    "/var/log/",
    "/var/run/",
)

_BLOCKED_PATH_SUFFIXES = (
    "/.ssh/",
    "/.gnupg/",
    "/.env",
    "/.aws/",
    "/.kube/",
    "/.docker/",
    "/.git/",
)

_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
_WARN_FILE_SIZE_BYTES = 20 * 1024 * 1024


def _validate_local_file(file_path: str, media_type: str = "image") -> None:
    resolved = os.path.realpath(file_path)
    if not os.path.isfile(resolved):
        raise ValueError(f"File not found: {file_path}")

    for prefix in _BLOCKED_PATH_PREFIXES:
        if resolved.startswith(prefix):
            raise ValueError(f"Access denied: path '{file_path}' is under a restricted system directory")

    for suffix in _BLOCKED_PATH_SUFFIXES:
        if suffix in resolved:
            raise ValueError(f"Access denied: path '{file_path}' contains a restricted directory ({suffix})")

    home = os.path.expanduser("~")
    for sensitive in [".ssh", ".gnupg", ".aws", ".kube", ".docker"]:
        sensitive_dir = os.path.join(home, sensitive)
        if resolved.startswith(sensitive_dir + os.sep):
            raise ValueError(f"Access denied: path '{file_path}' is under a restricted user directory (~/{sensitive})")

    ext = os.path.splitext(resolved)[1].lower()
    allowed = set(_MIME_MAP.get(media_type, {}).keys())
    if ext not in allowed:
        raise ValueError(
            f"File extension '{ext}' is not allowed for media type '{media_type}'. "
            f"Allowed: {sorted(allowed)}"
        )

    file_size = os.path.getsize(resolved)
    if file_size > _MAX_FILE_SIZE_BYTES:
        size_mb = file_size / (1024 * 1024)
        max_mb = _MAX_FILE_SIZE_BYTES / (1024 * 1024)
        raise ValueError(
            f"Local file too large: {file_path} ({size_mb:.1f}MB). "
            f"Maximum allowed: {max_mb:.0f}MB. "
            f"Please compress or resize the file and try again."
        )
    if file_size > _WARN_FILE_SIZE_BYTES:
        size_mb = file_size / (1024 * 1024)
        max_mb = _MAX_FILE_SIZE_BYTES / (1024 * 1024)
        print(
            f"Warning: Local file {file_path} is {size_mb:.1f}MB. "
            f"Limit is {max_mb:.0f}MB. Large files may slow down processing."
        )


def _is_local_file(value: str) -> bool:
    if not value:
        return False
    if value.startswith(("http://", "https://", "data:")):
        return False
    return os.path.isfile(value)


def _local_file_to_data_uri(file_path: str, media_type: str = "image") -> str:
    _validate_local_file(file_path, media_type)
    ext = os.path.splitext(file_path)[1].lower()
    mime = _MIME_MAP.get(media_type, {}).get(ext) or mimetypes.guess_type(file_path)[0]
    if not mime:
        mime = "application/octet-stream"
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _resolve_url(value: str, media_type: str = "image") -> str:
    if _is_local_file(value):
        print(f"Detected local file: {value}, converting to base64 data URI...")
        return _local_file_to_data_uri(value, media_type)
    return value


def _resolve_urls(values: List[str], media_type: str = "image") -> List[str]:
    return [_resolve_url(v, media_type) for v in values]


@dataclass
class VideoTaskResult:
    video_name: str
    task_id: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None
    error_detail: Optional[dict] = None
    status: str = "pending"
    execution_expires_after: Optional[int] = None


@dataclass
class VideoGenerationConfig:
    first_frame: Optional[str] = None
    last_frame: Optional[str] = None
    reference_images: List[str] = field(default_factory=list)
    reference_videos: List[str] = field(default_factory=list)
    reference_audios: List[str] = field(default_factory=list)
    generate_audio: Optional[bool] = None
    ratio: Optional[str] = None
    duration: Optional[int] = None
    resolution: Optional[str] = None
    frames: Optional[int] = None
    camera_fixed: Optional[bool] = None
    seed: Optional[int] = None
    watermark: Optional[bool] = None
    tools: Optional[List[Dict]] = None


def _get_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }


def _build_content(prompt: str, config: VideoGenerationConfig) -> list:
    content = [{"type": "text", "text": prompt}]

    if config.first_frame:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": config.first_frame},
                "role": "first_frame",
            }
        )

    if config.last_frame:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": config.last_frame},
                "role": "last_frame",
            }
        )

    for ref_image in config.reference_images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": ref_image},
                "role": "reference_image",
            }
        )

    for ref_video in config.reference_videos:
        content.append(
            {
                "type": "video_url",
                "video_url": {"url": ref_video},
                "role": "reference_video",
            }
        )

    for ref_audio in config.reference_audios:
        content.append(
            {
                "type": "audio_url",
                "audio_url": {"url": ref_audio},
                "role": "reference_audio",
            }
        )

    return content


def _should_disable_audio(
    model_name: str, generate_audio: Optional[bool]
) -> Optional[bool]:
    if generate_audio is False:
        return None
    if model_name.startswith("doubao-seedance-1-0") and generate_audio:
        print(
            "Warning: doubao-seedance-1-0 series do not support audio generation. Use doubao-seedance-1-5 for audio."
        )
        return None
    return generate_audio


def _is_text_to_video(config: VideoGenerationConfig) -> bool:
    return not (
        config.first_frame
        or config.last_frame
        or config.reference_images
        or config.reference_videos
        or config.reference_audios
    )


def _build_request_body(
    prompt: str, config: VideoGenerationConfig, model_name: str
) -> dict:
    body = {
        "model": model_name,
        "content": _build_content(prompt, config),
    }

    if config.tools is not None and _is_text_to_video(config):
        body["tools"] = config.tools

    generate_audio = _should_disable_audio(model_name, config.generate_audio)
    if generate_audio is not None:
        body["generate_audio"] = generate_audio

    optional_fields = [
        "ratio",
        "duration",
        "resolution",
        "frames",
        "camera_fixed",
        "seed",
        "watermark",
    ]
    for field_name in optional_fields:
        value = getattr(config, field_name, None)
        if value is not None:
            body[field_name] = value

    return body


async def _create_video_task(
    prompt: str, config: VideoGenerationConfig, model_name: str
) -> dict:
    url = f"{API_BASE}/contents/generations/tasks"
    body = _build_request_body(prompt, config, model_name)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, headers=_get_headers(), json=body)
        response.raise_for_status()
        return response.json()


async def _get_task_status(task_id: str) -> dict:
    url = f"{API_BASE}/contents/generations/tasks/{task_id}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url, headers=_get_headers())
        response.raise_for_status()
        return response.json()


def _parse_item_to_config(item: dict) -> VideoGenerationConfig:
    first_frame = item.get("first_frame")
    if first_frame:
        first_frame = _resolve_url(first_frame, "image")
    last_frame = item.get("last_frame")
    if last_frame:
        last_frame = _resolve_url(last_frame, "image")
    return VideoGenerationConfig(
        first_frame=first_frame,
        last_frame=last_frame,
        reference_images=_resolve_urls(item.get("reference_images", []), "image"),
        reference_videos=_resolve_urls(item.get("reference_videos", []), "video"),
        reference_audios=_resolve_urls(item.get("reference_audios", []), "audio"),
        generate_audio=item.get("generate_audio"),
        ratio=item.get("ratio"),
        duration=item.get("duration"),
        resolution=item.get("resolution"),
        frames=item.get("frames"),
        camera_fixed=item.get("camera_fixed"),
        seed=item.get("seed"),
        watermark=item.get("watermark"),
        tools=item.get("tools"),
    )


async def _process_single_item(item: dict, model_name: str) -> VideoTaskResult:
    video_name = item["video_name"]
    prompt = item["prompt"]
    config = _parse_item_to_config(item)

    try:
        task_data = await _create_video_task(prompt, config, model_name)
        task_id = task_data.get("id")
        return VideoTaskResult(
            video_name=video_name,
            task_id=task_id,
            status="created",
            execution_expires_after=task_data.get("execution_expires_after"),
        )
    except httpx.HTTPStatusError as e:
        error_text = e.response.text if e.response else str(e)
        error_detail = None
        try:
            error_detail = json.loads(error_text)
        except Exception:
            error_detail = {"raw_error": error_text}
        return VideoTaskResult(
            video_name=video_name,
            error=error_text,
            error_detail=error_detail,
            status="failed",
        )
    except Exception as e:
        return VideoTaskResult(
            video_name=video_name,
            error=str(e),
            error_detail={"raw_error": str(e)},
            status="failed",
        )


async def _poll_task_status(
    task_id: str,
    video_name: str,
    max_wait_seconds: int = 1200,
    poll_interval: int = 10,
) -> VideoTaskResult:
    max_polls = max_wait_seconds // poll_interval
    polls = 0

    while polls < max_polls:
        result = await _get_task_status(task_id)
        status = result.get("status")

        if status == "succeeded":
            video_url = result.get("content", {}).get("video_url")
            return VideoTaskResult(
                video_name=video_name,
                task_id=task_id,
                video_url=video_url,
                status="succeeded",
                execution_expires_after=result.get("execution_expires_after"),
            )

        if status == "failed":
            error = result.get("error", {})
            return VideoTaskResult(
                video_name=video_name,
                task_id=task_id,
                error=str(error),
                error_detail=error,
                status="failed",
                execution_expires_after=result.get("execution_expires_after"),
            )

        print(f"Video {video_name} status: {status}, waiting...")
        await asyncio.sleep(poll_interval)
        polls += 1

    result = await _get_task_status(task_id)
    return VideoTaskResult(
        video_name=video_name,
        task_id=task_id,
        error="polling_timeout",
        status="pending",
        execution_expires_after=result.get("execution_expires_after"),
    )


async def video_task_query(task_id: str) -> Dict:
    result = await _get_task_status(task_id)
    status = result.get("status")
    response = {
        "task_id": task_id,
        "status": status,
        "video_url": None,
        "error": None,
        "model": result.get("model"),
        "created_at": result.get("created_at"),
        "updated_at": result.get("updated_at"),
        "execution_expires_after": result.get("execution_expires_after"),
    }

    if status == "succeeded":
        response["video_url"] = result.get("content", {}).get("video_url")
    elif status == "failed":
        response["error"] = result.get("error")

    return response


async def video_generate(
    params: list,
    batch_size: int = 10,
    max_wait_seconds: int = 1200,
    model_name: str = None,
) -> Dict:
    model = model_name or os.getenv("MODEL_VIDEO_NAME", DEFAULT_MODEL)

    success_list = []
    error_list = []
    error_details = []
    pending_list = []

    for start_idx in range(0, len(params), batch_size):
        batch = params[start_idx : start_idx + batch_size]

        task_results = await asyncio.gather(
            *[_process_single_item(item, model) for item in batch]
        )

        created_tasks = []
        for r in task_results:
            if r.status == "created" and r.task_id:
                created_tasks.append(r)
            elif r.status == "failed":
                error_list.append(r.video_name)
                if r.error_detail:
                    error_details.append(
                        {
                            "video_name": r.video_name,
                            "error": r.error_detail,
                        }
                    )

        poll_results = await asyncio.gather(
            *[
                _poll_task_status(r.task_id, r.video_name, max_wait_seconds)
                for r in created_tasks
            ]
        )

        for result in poll_results:
            if result.status == "succeeded":
                success_list.append({result.video_name: result.video_url})
                print(f"Video {result.video_name} completed: {result.video_url}")
            elif result.status == "failed":
                error_list.append(result.video_name)
                error_details.append(
                    {
                        "video_name": result.video_name,
                        "error": result.error_detail,
                    }
                )
                print(f"Video {result.video_name} failed: {result.error}")
            elif result.status == "pending":
                pending_list.append(
                    {
                        "video_name": result.video_name,
                        "task_id": result.task_id,
                        "execution_expires_after": result.execution_expires_after,
                        "message": f"Task still running. Use video_task_query('{result.task_id}') to check status later.",
                    }
                )

    if success_list and not error_list and not pending_list:
        status = "success"
    elif success_list:
        status = "partial_success"
    else:
        status = "error"

    return {
        "status": status,
        "success_list": success_list,
        "error_list": error_list,
        "error_details": error_details,
        "pending_list": pending_list,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate videos using Seedance models"
    )
    parser.add_argument("--prompt", "-p", help="Text description of the video")
    parser.add_argument("--name", "-n", default="video", help="Video name identifier")
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="Model name (default: doubao-seedance-2-0-260128)",
    )
    parser.add_argument(
        "--ratio",
        "-r",
        choices=["16:9", "9:16", "4:3", "3:4", "1:1", "2:1", "21:9", "adaptive"],
        default="16:9",
        help="Aspect ratio (default: 16:9)",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=int,
        default=None,
        help="Video duration in seconds (2-15)",
    )
    parser.add_argument(
        "--resolution",
        choices=["480p", "720p", "1080p"],
        default=None,
        help="Video resolution",
    )
    parser.add_argument(
        "--first-frame", "-f", default=None, help="First frame image URL"
    )
    parser.add_argument("--last-frame", "-l", default=None, help="Last frame image URL")
    parser.add_argument(
        "--ref-images",
        nargs="+",
        default=None,
        help="Reference image URLs (1-4 images)",
    )
    parser.add_argument(
        "--ref-videos",
        nargs="+",
        default=None,
        help="Reference video URLs (0-3 videos)",
    )
    parser.add_argument(
        "--ref-audios",
        nargs="+",
        default=None,
        help="Reference audio URLs (0-3 audios)",
    )
    parser.add_argument(
        "--generate-audio",
        action="store_true",
        help="Generate audio (Seedance 1.5 only)",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed for reproducibility"
    )
    parser.add_argument("--no-watermark", action="store_true", help="Disable watermark")
    parser.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=1200,
        help="Max wait time in seconds (default: 1200)",
    )
    parser.add_argument(
        "--query-task", "-q", default=None, help="Query task status by task_id"
    )

    args = parser.parse_args()

    if not API_KEY:
        raise PermissionError(
            "ARK_API_KEY or MODEL_VIDEO_API_KEY or MODEL_AGENT_API_KEY not found in environment variables."
        )

    if args.query_task:
        result = asyncio.run(video_task_query(args.query_task))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if not args.prompt:
        print("Error: --prompt is required when not using --query-task")
        sys.exit(1)

    item = {
        "video_name": args.name,
        "prompt": args.prompt,
        "ratio": args.ratio,
        "watermark": not args.no_watermark,
    }

    if args.first_frame:
        item["first_frame"] = args.first_frame
    if args.last_frame:
        item["last_frame"] = args.last_frame
    if args.ref_images:
        item["reference_images"] = args.ref_images
    if args.ref_videos:
        item["reference_videos"] = args.ref_videos
    if args.ref_audios:
        item["reference_audios"] = args.ref_audios
    if args.generate_audio:
        item["generate_audio"] = True
    if args.duration:
        item["duration"] = args.duration
    if args.resolution:
        item["resolution"] = args.resolution
    if args.seed is not None:
        item["seed"] = args.seed

    result = asyncio.run(
        video_generate([item], max_wait_seconds=args.timeout, model_name=args.model)
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
