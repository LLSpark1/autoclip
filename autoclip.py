"""The clip-making engine used by app.py.

Steps: transcribe the video -> pick the best moments -> crop to vertical
-> add word-by-word captions.
"""
import hashlib
import json
import os
import random
import re
import shutil
import statistics
import subprocess
from pathlib import Path

OUT_W, OUT_H = 1080, 1920
FONTS_DIR = Path(__file__).resolve().parent / "fonts"
DATA_DIR = Path.home() / ".autoclip"
CONFIG_PATH = DATA_DIR / "config.json"


# ---------------------------------------------------------------- helpers

def ffmpeg():
    """The ffmpeg that comes with imageio-ffmpeg (known to support captions), else the system one."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return shutil.which("ffmpeg") or "ffmpeg"


def video_info(path):
    """Width, height and duration, read from ffmpeg's output."""
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True, errors="replace").stderr
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    v = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", err)
    if not (d and v):
        raise RuntimeError("That file doesn't look like a video.")
    w, h = int(v[1]), int(v[2])
    if re.search(r"rotation of -?(90|270)", err):  # phone videos stored sideways
        w, h = h, w
    return w, h, int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3])


def slugify(text, n=40):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n] or "clip"


def fmt_ts(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg))
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------- 1. transcribe

def load_audio(video):
    """16 kHz mono audio as float32, decoded with ffmpeg (the format Whisper expects)."""
    import numpy as np
    pcm = subprocess.run([ffmpeg(), "-nostdin", "-loglevel", "error", "-i", str(video),
                          "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0


def transcribe(video, log):
    """Word-level transcript, cached so the same video is only transcribed once."""
    st = Path(video).stat()
    key = hashlib.sha1(f"{Path(video).name}|{st.st_size}".encode()).hexdigest()[:12]
    cache = DATA_DIR / "transcripts" / f"{key}.json"
    if cache.exists():
        log("Using saved transcript")
        return json.loads(cache.read_text())

    from faster_whisper import WhisperModel
    log("Loading speech model (the first time downloads it)...")
    model = WhisperModel("small", device="auto", compute_type="auto")
    segments, info = model.transcribe(load_audio(video), word_timestamps=True, vad_filter=True)
    segs = []
    for s in segments:
        words = [{"w": w.word.strip(), "s": w.start, "e": w.end} for w in s.words or [] if w.word.strip()]
        segs.append({"s": s.start, "e": s.end, "text": s.text.strip(), "words": words})
        log(f"Transcribing... {fmt_ts(s.end)} of {fmt_ts(info.duration)}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(segs))
    return segs


# ---------------------------------------------------------------- 2. pick moments

CLIP_SCHEMA = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "start": {"type": "number"},
            "end": {"type": "number"},
            "title": {"type": "string"},
            "caption": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["start", "end", "title", "caption", "hashtags"],
        "additionalProperties": False,
    }}},
    "required": ["clips"],
    "additionalProperties": False,
}


def pick_with_ai(segs, n, min_len, max_len, topic, api_key):
    import anthropic
    transcript = "\n".join(f"[{s['s']:.1f}-{s['e']:.1f}] {s['text']}" for s in segs)
    prompt = f"""You are an expert short-form video editor. Pick the {n} best standalone clips
from this {topic or 'video'} transcript for TikTok, YouTube Shorts and Reels.

- Each clip is {min_len}-{max_len} seconds long and starts and ends on transcript line boundaries.
- Start on a strong hook (bold claim, question, conflict). No slow intros.
- Make sense on its own and end on a payoff, not mid-thought.
- No overlapping clips. Best first.
- title: on-screen headline, max 7 words, creates curiosity.
- caption: post caption under 150 characters.
- hashtags: 3-5, without the # sign.

Transcript (seconds):
{transcript}"""
    resp = anthropic.Anthropic(api_key=api_key).beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"format": {"type": "json_schema", "schema": CLIP_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("the AI declined this video")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))["clips"]


HOOK_WORDS = re.compile(
    r"\b(never|always|secret|crazy|insane|honestly|truth|biggest|worst|best|mistake|actually|"
    r"nobody|everyone|money|million|why|how|stop|wrong|literally|wait|what|problem|hate|love)\b", re.I)


def pick_with_keywords(segs, n, min_len, max_len):
    """No-AI fallback: score stretches of speech by exclamations, questions and hook words."""
    candidates = []
    for i in range(len(segs)):
        score = 0
        for j in range(i, len(segs)):
            length = segs[j]["e"] - segs[i]["s"]
            if length > max_len:
                break
            t = segs[j]["text"]
            score += 2 * t.count("!") + 1.5 * t.count("?") + len(HOOK_WORDS.findall(t))
            if length >= min_len:
                hook = 3 if ("?" in segs[i]["text"] or HOOK_WORDS.search(segs[i]["text"])) else 0
                candidates.append((score / length * 30 + hook, segs[i]["s"], segs[j]["e"], i))
    picked = []
    for _, s, e, i in sorted(candidates, reverse=True):
        if all(e <= c["start"] or s >= c["end"] for c in picked):
            title = " ".join(segs[i]["text"].split()[:7])
            picked.append({"start": s, "end": e, "title": title, "caption": title,
                           "hashtags": ["fyp", "viral", "clips"]})
        if len(picked) == n:
            break
    return picked


def snap(clip, segs, total):
    """Move clip edges to the nearest sentence boundaries so no words get cut off."""
    start = min((s["s"] for s in segs), key=lambda x: abs(x - clip["start"]))
    end = min((s["e"] for s in segs), key=lambda x: abs(x - clip["end"]))
    if end > start:
        clip["start"], clip["end"] = start, end
    clip["start"], clip["end"] = max(0, clip["start"] - 0.15), min(total, clip["end"] + 0.35)
    return clip


# ---------------------------------------------------------------- 3. crop

def find_face_x(video, start, end):
    """Horizontal position of the main face in the clip (or None if no face is found)."""
    import cv2
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(video))
    xs, t = [], start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        t += 0.5
        if not ok:
            continue
        scale = 640 / frame.shape[1]
        gray = cv2.cvtColor(cv2.resize(frame, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))
        if len(faces):
            x, _, w, _ = max(faces, key=lambda f: f[2] * f[3])
            xs.append((x + w / 2) / scale)
    cap.release()
    return statistics.median(xs) if xs else None


def crop_filter(framing, src_w, src_h, face_x):
    if framing == "split":  # speaker on top, background video (input 1) below
        half = OUT_H // 2
        crop_w = min(src_w, int(src_h * OUT_W / half)) // 2 * 2
        center = face_x if face_x is not None else src_w / 2
        x = int(min(max(center - crop_w / 2, 0), src_w - crop_w))
        return (f"[0:v]crop={crop_w}:{src_h}:{x}:0,scale={OUT_W}:{half},setsar=1[top];"
                f"[1:v]scale={OUT_W}:{half}:force_original_aspect_ratio=increase,"
                f"crop={OUT_W}:{half},setsar=1[bottom];[top][bottom]vstack")
    if framing == "fit":  # whole frame on top of a blurred copy
        return ("[0:v]split[a][b];"
                f"[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},boxblur=20:2[bg];"
                f"[b]scale={OUT_W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    crop_w = min(src_w, int(src_h * 9 / 16)) // 2 * 2
    center = face_x if face_x is not None else src_w / 2
    x = int(min(max(center - crop_w / 2, 0), src_w - crop_w))
    return f"[0:v]crop={crop_w}:{src_h}:{x}:0,scale={OUT_W}:{OUT_H}"


# ---------------------------------------------------------------- 4. captions

def ass_time(t):
    t = max(0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def clean(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")").upper()


def write_captions(segs, start, end, title, path, caption_margin=560):
    """Subtitle file: headline on top, 3 words at a time with the spoken word highlighted."""
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {OUT_W}", f"PlayResY: {OUT_H}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,DejaVu Sans,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,60,{caption_margin},1",
        "Style: Title,DejaVu Sans,64,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,180,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 1,{ass_time(0)},{ass_time(end - start)},Title,,0,0,0,,{clean(title)}",
    ]
    words = [w for s in segs for w in s["words"] if w["s"] >= start - 0.05 and w["e"] <= end + 0.05]
    for g in range(0, len(words), 3):
        group = words[g:g + 3]
        for k, w in enumerate(group):
            until = group[k + 1]["s"] if k + 1 < len(group) else w["e"]
            text = " ".join("{\\c&H00E5FF&\\fscx110\\fscy110}" + clean(x["w"]) + "{\\r}" if x is w
                            else clean(x["w"]) for x in group)
            lines.append(f"Dialogue: 0,{ass_time(w['s'] - start)},{ass_time(max(until, w['e']) - start)},"
                         f"Cap,,0,0,0,,{text}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 5. render

def render(video, clip, segs, out_dir, number, framing, src_w, src_h, background=None):
    name = f"{number:02d}-{slugify(clip['title'])}"
    subs = out_dir / f"{name}.ass"
    split = framing == "split" and background
    if framing == "split" and not background:
        framing = "face"
    # In split screen the captions sit on the line between the two videos.
    write_captions(segs, clip["start"], clip["end"], clip["title"], subs, 900 if split else 560)
    face_x = find_face_x(video, clip["start"], clip["end"]) if framing in ("face", "split") else None
    # Fonts are copied next to the clips so the filter can use a short relative path
    # (avoids escaping problems with drive letters and spaces).
    filters = crop_filter(framing, src_w, src_h, face_x) + f",ass={subs.name}:fontsdir=.fonts[v]"
    duration = clip["end"] - clip["start"]
    inputs = ["-ss", f"{clip['start']:.2f}", "-t", f"{duration:.2f}", "-i", str(Path(video).resolve())]
    if split:
        bg_len = video_info(background)[2]
        offset = random.uniform(0, max(0, bg_len - duration))  # different part of it each clip
        inputs += ["-stream_loop", "-1", "-ss", f"{offset:.2f}", "-i", str(Path(background).resolve())]
    result = subprocess.run(
        [ffmpeg(), "-y", "-loglevel", "error", *inputs, "-filter_complex", filters,
         "-map", "[v]", "-map", "0:a?", "-t", f"{duration:.2f}",
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", f"{name}.mp4"],
        cwd=out_dir, capture_output=True, text=True, errors="replace")
    subs.unlink(missing_ok=True)
    if result.returncode:
        raise RuntimeError("Video rendering failed: " + result.stderr.strip()[-300:])
    clip["post_text"] = clip["caption"] + " " + " ".join("#" + t.lstrip("#") for t in clip["hashtags"])
    (out_dir / f"{name}.txt").write_text(f"{clip['title']}\n\n{clip['post_text']}\n", encoding="utf-8")
    return out_dir / f"{name}.mp4"


# ---------------------------------------------------------------- everything

def make_clips(video, out_dir, n=5, min_len=30, max_len=60, crop="face", topic="", api_key="",
               background=None, log=print):
    """Turn one video into clips. Returns a list of (mp4 path, clip info).

    crop: "face" (follow the speaker), "fit" (full frame) or "split" (speaker on top,
    the `background` video, e.g. satisfying or gameplay footage, underneath).
    """
    out_dir = Path(out_dir).resolve()
    (out_dir / ".fonts").mkdir(parents=True, exist_ok=True)
    for font in FONTS_DIR.glob("*.ttf"):
        shutil.copy(font, out_dir / ".fonts")
    src_w, src_h, total = video_info(video)

    segs = transcribe(video, log)
    if not segs:
        raise RuntimeError("No speech found in this video.")

    log("Finding the best moments...")
    clips = None
    if api_key:
        try:
            clips = pick_with_ai(segs, n, min_len, max_len, topic, api_key)
        except Exception as e:
            log(f"AI picking didn't work ({str(e)[:100]}), using the basic picker")
    if clips is None:
        clips = pick_with_keywords(segs, n, min_len, max_len)
    clips = [snap(c, segs, total) for c in clips]

    results = []
    for i, clip in enumerate(clips, 1):
        log(f"Making clip {i} of {len(clips)}: {clip['title']}")
        results.append((render(video, clip, segs, out_dir, i, crop, src_w, src_h, background), clip))
    shutil.rmtree(out_dir / ".fonts", ignore_errors=True)
    log(f"Done! {len(results)} clips saved in {out_dir}")
    return results
