#!/usr/bin/env python3
"""AutoClip Studio: drop in a long video, get ready-to-post vertical clips."""
import multiprocessing
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import autoclip

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")  # don't send usage data anywhere

APP_NAME = "AutoClip Studio"
OUTPUT_ROOT = Path.home() / "AutoClip Clips"
BACKGROUND_DIR = autoclip.DATA_DIR / "background"

LENGTHS = {"Short (15-30s)": (15, 30), "Medium (30-60s)": (30, 60), "Long (60-90s)": (60, 90)}
FRAMING = {
    "Follow the speaker": "face",
    "Show full frame": "fit",
    "Split screen (satisfying video below)": "split",
}

# Installed apps have no console; keep a log file for troubleshooting instead.
# AUTOCLIP_LOG picks the file (used by the automated build tests).
if os.environ.get("AUTOCLIP_LOG") or sys.stdout is None or sys.stderr is None:
    log_path = Path(os.environ.get("AUTOCLIP_LOG") or autoclip.DATA_DIR / "app.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(log_path, "w", buffering=1, encoding="utf-8")
    import faulthandler
    faulthandler.enable(sys.stderr)  # also record hard crashes


def saved_background():
    files = sorted(BACKGROUND_DIR.glob("*")) if BACKGROUND_DIR.exists() else []
    return files[0] if files else None


def save_background(path):
    """Keep a copy of the split-screen video so it's remembered next time."""
    shutil.rmtree(BACKGROUND_DIR, ignore_errors=True)
    BACKGROUND_DIR.mkdir(parents=True)
    return Path(shutil.copy(path, BACKGROUND_DIR / Path(path).name))


def open_folder(path):
    if platform.system() == "Windows":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if platform.system() == "Darwin" else "xdg-open", str(path)])


def make(videos, topic, count, length, framing, background, api_key):
    import gradio as gr
    if not videos:
        raise gr.Error("Drop a video in first.")
    videos = videos if isinstance(videos, list) else [videos]
    api_key = (api_key or "").strip()
    autoclip.save_config({"api_key": api_key})
    if background:
        background = save_background(background)
    else:
        background = saved_background()
    if FRAMING[framing] == "split" and not background:
        raise gr.Error("For split screen, add a satisfying video under Settings first.")

    # One folder per batch, with a subfolder per video.
    out_dir = OUTPUT_ROOT / f"{datetime.now():%Y-%m-%d %H-%M-%S}"
    min_len, max_len = LENGTHS[length]
    lines, box = [], {"clips": [], "errors": []}

    def work():
        for i, video in enumerate(videos, 1):
            lines.append(f"--- Video {i} of {len(videos)}: {Path(video).name}")
            try:
                box["clips"] += autoclip.make_clips(
                    video, out_dir / autoclip.slugify(Path(video).stem, 30), n=int(count),
                    min_len=min_len, max_len=max_len, crop=FRAMING[framing], topic=topic,
                    api_key=api_key, background=background, log=lines.append)
            except Exception as e:  # keep going with the other videos
                box["errors"].append(f"{Path(video).name}: {e}")
                lines.append(f"Skipped {Path(video).name}: {e}")

    t = threading.Thread(target=work, daemon=True)
    t.start()
    while t.is_alive():
        yield "\n".join(lines[-12:]) or "Starting...", gr.skip(), ""
        time.sleep(0.5)
    clips = [{"path": str(p), **c} for p, c in box["clips"]]
    summary = f"Done! {len(clips)} clips from {len(videos) - len(box['errors'])} of {len(videos)} videos."
    if box["errors"]:
        summary += "\nProblems:\n" + "\n".join(box["errors"])
    yield summary, clips, str(out_dir) if clips else ""


def build_ui():
    import gradio as gr
    bg = saved_background()
    with gr.Blocks(title=APP_NAME) as demo:
        gr.Markdown(f"# 🎬 {APP_NAME}\nDrop in long videos. Get clips ready for TikTok, Shorts and Reels.")
        clips_state, folder = gr.State([]), gr.State("")

        with gr.Row(equal_height=False):
            with gr.Column(scale=2, min_width=300):
                video = gr.File(label="Your videos (drop as many as you like)", file_types=["video"],
                                type="filepath", file_count="multiple", height=140)
                topic = gr.Textbox(label="What's it about? (optional)",
                                   placeholder="e.g. business podcast, gaming stream")
                with gr.Accordion("Settings", open=False):
                    count = gr.Slider(1, 10, value=5, step=1, label="Clips per video")
                    length = gr.Radio(list(LENGTHS), value="Medium (30-60s)", label="Clip length")
                    framing = gr.Radio(list(FRAMING), value="Follow the speaker", label="Framing",
                                       info="Split screen keeps viewers watching longer")
                    background = gr.File(label="Satisfying video for split screen",
                                         file_types=["video"], type="filepath", height=100)
                    gr.Markdown(f"<small>Using saved video: {bg.name}. Drop a new one to replace it.</small>"
                                if bg else
                                "<small>e.g. parkour gameplay, slime, soap cutting. Use footage you own "
                                "or royalty-free (Pexels, Pixabay). It's remembered for next time.</small>")
                    api_key = gr.Textbox(label="Anthropic API key (for smarter clip picks)",
                                         type="password", placeholder="sk-ant-...",
                                         value=autoclip.load_config().get("api_key", ""),
                                         info="Optional. Get one at console.anthropic.com")
                go = gr.Button("Make my clips", variant="primary", size="lg")
                status = gr.Textbox(label="Status", lines=6, interactive=False, autoscroll=True)
                gr.Button("📂 Open clips folder").click(
                    lambda f: open_folder(f or OUTPUT_ROOT), folder, None)

            with gr.Column(scale=3, min_width=340):
                @gr.render(inputs=clips_state)
                def show(clips):
                    if not clips:
                        gr.Markdown("### Your clips will show up here")
                        return
                    for row in range(0, len(clips), 2):
                        with gr.Row():
                            for c in clips[row:row + 2]:
                                with gr.Column(min_width=240):
                                    gr.Video(c["path"], height=440, show_label=False, interactive=False)
                                    gr.Textbox(c["post_text"], label="Caption to post",
                                               buttons=["copy"], lines=2)

        go.click(make, [video, topic, count, length, framing, background, api_key],
                 [status, clips_state, folder])
        gr.Markdown("<small>Only clip videos you own or have permission to use.</small>")
    return demo


def start_server():
    import gradio as gr
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    demo = build_ui()
    demo.queue().launch(
        server_name="127.0.0.1",
        allowed_paths=[str(OUTPUT_ROOT)],
        theme=gr.themes.Soft(primary_hue="violet"),
        footer_links=[],
        prevent_thread_lock=True,
        quiet=True,
    )
    return demo


def selftest(video=None):
    """Checks a packaged build works: run with --selftest [video-with-speech]."""
    import urllib.request
    import cv2
    import faster_whisper  # noqa: F401  (import check)
    from faster_whisper.utils import get_assets_path

    exe = autoclip.ffmpeg()
    filters = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    assert " ass " in filters, "ffmpeg has no caption (ass) support"
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    assert not cascade.empty(), "face detector data missing"
    assert list(autoclip.FONTS_DIR.glob("*.ttf")), "caption font missing"
    assert list(Path(get_assets_path()).glob("*.onnx")), "speech detection model missing"
    print("ffmpeg:", exe)
    try:
        import webview  # noqa: F401
        print("app window support: OK")
    except Exception as e:  # not fatal: the app falls back to the browser
        print("app window support: unavailable,", e)

    demo = start_server()
    page = urllib.request.urlopen(demo.local_url, timeout=30).read().decode()
    assert APP_NAME in page, "app page did not load"
    demo.close()
    print("app page OK")

    if video:  # full run: transcription (downloads the speech model), picking, rendering
        out = Path.home() / "autoclip-selftest"
        shutil.rmtree(out, ignore_errors=True)
        results = autoclip.make_clips(video, out, n=1, min_len=5, max_len=30, background=video,
                                      crop="split")
        assert results and results[0][0].stat().st_size > 10_000, "no clip was made"
        print("clip OK:", results[0][0], "-", results[0][1]["title"])
    print("SELFTEST PASSED")


def main():
    if "--selftest" in sys.argv:
        args = sys.argv[sys.argv.index("--selftest") + 1:]
        try:
            selftest(args[0] if args else None)
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            os._exit(1)
        sys.stdout.flush()
        os._exit(0)
    demo = start_server()
    if os.environ.get("AUTOCLIP_NO_BROWSER"):
        demo.block_thread()
        return
    try:  # a real app window
        import webview
        webview.create_window(APP_NAME, demo.local_url, width=1280, height=900, min_size=(900, 650))
        webview.start()
    except Exception as e:  # no window support: fall back to the browser
        print("App window unavailable, opening browser:", e)
        import webbrowser
        webbrowser.open(demo.local_url)
        demo.block_thread()
    os._exit(0)  # closing the window quits the app


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
