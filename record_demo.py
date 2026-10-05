"""Record the Dalil demo video with captions and an optional female voiceover.

Usage:
    uvicorn app.main:app --port 8000          # in another terminal
    python tools/record_demo.py --url http://localhost:8000 --out dalil-demo.mp4 \
        --voice voices/en-us-libritts-high.onnx --speaker 539

Needs: pip install playwright piper-tts && playwright install chromium, plus ffmpeg.
Voice: Piper TTS with the LibriTTS "high" voice (CC BY 4.0), speaker 539.
Download it from https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-us-libritts-high.tar.gz
Without --voice, the video has captions only.

If the server has NEBIUS_API_KEY set, the narration describes the live Nemotron
steps; otherwise it says the app is running in offline (rules-only) mode.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
import wave
from pathlib import Path

from playwright.async_api import async_playwright

W, H = 1280, 720
AUTHOR = "najmunnaharhira"
REPO = f"github.com/{AUTHOR}/nebius-global-ai-hackathon"

CARD_CSS = """
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#22305C;color:#F2F4FA;font-family:'Hind Siliguri','Noto Sans',system-ui,sans-serif}
.wrap{max-width:980px;padding:0 60px}
h1{font-family:'Tiro Bangla',Georgia,serif;font-weight:400;font-size:64px;margin:0 0 12px;line-height:1.1}
h2{font-family:'Tiro Bangla',Georgia,serif;font-weight:400;font-size:40px;margin:0 0 20px;line-height:1.2}
p{font-size:26px;line-height:1.5;margin:0 0 14px;opacity:.92}
.seal{width:84px;height:84px;border-radius:50%;border:3px solid #F2F4FA;display:grid;place-items:center;
font-size:44px;margin-bottom:28px;font-family:'Tiro Bangla',serif}
table{border-collapse:collapse;font-size:22px;margin-top:8px;width:100%}
td{padding:10px 14px;border-bottom:1px solid rgba(242,244,250,.25);vertical-align:top}
td:first-child{opacity:.8;width:42%}
.small{font-size:20px;opacity:.75}
.tiny{font-size:15px;opacity:.6;margin-top:26px}
"""

CAPTION_JS = """
(text) => {
  let el = document.getElementById('demo-caption');
  if (!el) {
    el = document.createElement('div');
    el.id = 'demo-caption';
    el.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:1040px;' +
      'background:rgba(28,34,48,.92);color:#fff;font:500 23px/1.4 "Hind Siliguri",system-ui,sans-serif;' +
      'padding:14px 22px;border-radius:10px;z-index:9999;text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.25)';
    document.body.appendChild(el);
  }
  el.style.display = text ? 'block' : 'none';
  el.textContent = text || '';
}
"""


def card(html: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CARD_CSS}</style></head><body><div class='wrap'>{html}</div></body></html>"


class Narrator:
    """Synthesizes each line, shows it as a caption, and logs when it was spoken."""

    def __init__(self, voice: str | None, speaker: int, workdir: Path):
        self.voice = None
        self.speaker = speaker
        self.workdir = workdir
        self.clips: list[tuple[float, Path]] = []
        self.cache: dict[str, tuple[Path | None, float]] = {}
        self.dry = False
        self.t0 = time.monotonic()
        if voice:
            from piper import PiperVoice, SynthesisConfig
            self.voice = PiperVoice.load(voice)
            self.cfg = SynthesisConfig(speaker_id=speaker, length_scale=1.0)

    def synth(self, text: str) -> tuple[Path | None, float]:
        if text in self.cache:
            return self.cache[text]
        if not self.voice:
            return None, max(3.0, len(text) / 15)
        path = self.workdir / f"line{len(self.cache):02d}.wav"
        with wave.open(str(path), "wb") as w:
            self.voice.synthesize_wav(text, w, syn_config=self.cfg)
        with wave.open(str(path)) as w:
            self.cache[text] = (path, w.getnframes() / w.getframerate())
        return self.cache[text]

    async def say(self, page, text: str, caption: str | None = "", pause: float = 0.45):
        """Speak `text`. Caption shows `text` unless `caption` is given (None hides it)."""
        path, dur = self.synth(text)  # cached: every line is synthesized before recording
        if self.dry:
            return
        shown = text if caption == "" else caption
        await page.evaluate(CAPTION_JS, shown)
        if path:
            self.clips.append((time.monotonic() - self.t0, path))
        await page.wait_for_timeout(int((dur + pause) * 1000))


async def scroll_to(page, selector, nth=0, secs=1.0):
    """Bring an element near the top of the screen, clear of the caption bar."""
    await page.evaluate(
        """([sel, n]) => { const el = document.querySelectorAll(sel)[n];
             if (el) window.scrollTo({top: el.getBoundingClientRect().top + window.scrollY - 70,
                                      behavior: 'smooth'}); }""",
        [selector, nth],
    )
    await page.wait_for_timeout(int(secs * 1000))


class FakePage:
    """Stands in for the browser during the dry run that pre-synthesizes every line."""

    def __getattr__(self, name):
        async def noop(*a, **k):
            return None
        return noop


async def scenario(page, n, live: bool, voice: str | None, url: str):
    say = n.say
    # 1. Title
    await page.set_content(card(
        "<div class='seal'>দ</div><h1>Dalil</h1>"
        "<p>Check a Bangladeshi land deed's ownership chain before you buy.</p>"
        f"<p class='small'>A solo project by {AUTHOR} · Nebius x NVIDIA Global AI Hackathon · "
        "Best Apps and Agents</p>"))
    await page.wait_for_timeout(800)
    await say(page, "Dalil: a land deed checker for Bangladesh, built as a solo project for the "
                    "Nebius and NVIDIA Global AI Hackathon.", caption=None, pause=0.8)

    # 2. Problem
    await page.set_content(card(
        "<h2>Buying land in Bangladesh is a gamble</h2>"
        "<p>Fake deeds, plots sold twice, sellers whose names don't match the record of rights, "
        "and broken ownership chains are common.</p>"
        "<p>Most buyers can't read old deeds, and a lawyer's first review is slow and costly.</p>"))
    await say(page, "In Bangladesh, buying land is a gamble. Fake deeds, plots sold twice, and broken "
                    "ownership chains are common. Most buyers can't read old deeds, and a lawyer's first "
                    "review is slow and costly. Dalil gives every buyer a fast first check.",
              caption=None, pause=0.8)

    # 3. App home
    await page.goto(url)
    await page.wait_for_selector(".sample")
    await page.wait_for_timeout(500)
    await say(page, "Add photos of the deed, the khatian, and the mutation papers, or try a sample case "
                    "built from fictional records.")
    if live:
        await say(page, "Uploaded pages are read by Nemotron 3 Nano Omni on Nebius Token Factory, "
                        "and every field stays editable.")
    else:
        await say(page, "In this recording, Dalil runs in offline mode. The rules engine works, "
                        "and the Nemotron steps are skipped.")

    # 4. Clean chain
    await page.click(".sample >> nth=0")
    await page.wait_for_selector(".verdict")
    await say(page, "First, a clean case. Two sales, both mutated. The chain is complete, "
                    "so there are no red flags.")

    # 5. Double sale
    await page.click(".sample >> nth=1")
    await page.wait_for_selector(".verdict.high")
    await say(page, "Now a risky case. The seller is offering twenty-five decimals of land.",
              caption="Now a risky case. The seller is offering 25 decimals of land.")
    await scroll_to(page, ".ledger")
    await say(page, "Dalil rebuilds the ownership chain, from the recorded owners to today's seller.")
    await scroll_to(page, ".entry.flagged", nth=0)
    await say(page, "In 2010, Jamal Hossain sold land two years before he bought it.")
    await scroll_to(page, ".entry.flagged", nth=1)
    await say(page, "In 2011, Shafiq Mia sold land, but nothing shows he ever owned it.")
    await scroll_to(page, ".entry.flagged", nth=2)
    await say(page, "In 2014, Rahim Uddin sold land he had already sold. A double sale.")
    await scroll_to(page, ".entry.flagged", nth=3)
    await say(page, "So Kamal Ahmed can't prove he owns any of the twenty-five decimals he is offering.",
              caption="So Kamal Ahmed can't prove he owns any of the 25 decimals he is offering.")
    await scroll_to(page, ".holdings")
    await say(page, "Only land backed by a valid chain is passed on. This is who really holds it.")
    await scroll_to(page, ".checklist")
    await say(page, "Then Dalil lists what to verify at the sub-registry and land office before you pay.")

    # 6. Bangla
    await page.click("[data-lang=bn]")
    await scroll_to(page, ".verdict")
    await say(page, "With one click, the report and the checklist switch to Bangla.",
              caption="এক ক্লিকে রিপোর্ট ও যাচাইয়ের তালিকা বাংলায়।")
    await scroll_to(page, ".checklist")
    await page.wait_for_timeout(1500)
    await page.click("[data-lang=en]")

    # 7. Trace
    await page.click(".trace summary")
    await scroll_to(page, ".trace")
    if live:
        await say(page, "This panel shows every step. Nemotron 3 Ultra reviewed the whole chain, "
                        "and Nemotron 3 Super wrote the checklist.")
    else:
        await say(page, "This panel shows every step. With an API key, Nemotron 3 Ultra reviews the whole "
                        "chain, and Nemotron 3 Super writes the checklist.")

    # 8. Name mismatch
    await page.evaluate("window.scrollTo({top:0})")
    await page.click(".sample >> nth=2")
    await page.wait_for_selector(".verdict.high")
    await scroll_to(page, ".entry.flagged")
    await say(page, "Here, Abdur Rahim Khan sold land recorded to Abdur Rahman Khan. "
                    "The names are close, but they may be different people.")
    await page.evaluate(CAPTION_JS, "")

    # 9. How it works
    await page.set_content(card(
        "<h2>How Dalil works</h2><table>"
        "<tr><td>Read page photos</td><td>Nemotron 3 Nano Omni</td></tr>"
        "<tr><td>Review the whole chain</td><td>Nemotron 3 Ultra</td></tr>"
        "<tr><td>Bilingual checklist</td><td>Nemotron 3 Super</td></tr>"
        "<tr><td>Core red-flag checks</td><td>Deterministic, tested rules engine</td></tr>"
        "</table><p class='small' style='margin-top:18px'>All model calls run through Nebius Token Factory.</p>"))
    await say(page, "Dalil uses Nemotron Nano for speed and Nemotron Ultra for reasoning, all through "
                    "Nebius Token Factory, with a tested rules engine underneath.", caption=None, pause=0.8)

    # 10. Close
    await page.set_content(card(
        "<div class='seal'>দ</div><h2>Dalil</h2>"
        f"<p>A solo project by {AUTHOR}</p>"
        f"<p class='small'>Open source (MIT): {REPO}</p>"
        "<p class='small'>A pre-check, not legal advice. Sample cases use fictional people and places.</p>"
        + ("<p class='tiny'>Voice: Piper TTS, LibriTTS voice (CC BY 4.0)</p>" if voice else "")))
    await say(page, "Dalil is open source. It's a pre-check, not legal advice. Thank you for watching.",
              caption=None, pause=1.5)



async def run(url: str, out: Path, voice: str | None, speaker: int):
    status = json.loads(urllib.request.urlopen(f"{url}/api/status").read())
    live = status["live"]
    tmp = Path(tempfile.mkdtemp())

    n = Narrator(voice, speaker, tmp)
    n.dry = True
    await scenario(FakePage(), n, live, voice, url)  # synthesize every line up front
    n.dry = False

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                                        record_video_size={"width": W, "height": H})
        page = await ctx.new_page()
        n.t0 = time.monotonic()  # clock starts with the recording

        await scenario(page, n, live, voice, url)

        video_path = await page.video.path()
        await ctx.close()
        await browser.close()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        shutil.copy(video_path, out.with_suffix(".webm"))
        print("ffmpeg not found; saved", out.with_suffix(".webm"))
        return

    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", video_path]
    if n.clips:
        for _, clip in n.clips:
            cmd += ["-i", str(clip)]
        parts = [f"[{i + 1}:a]adelay={int(start * 1000)}:all=1[a{i}]" for i, (start, _) in enumerate(n.clips)]
        mix = "".join(f"[a{i}]" for i in range(len(n.clips)))
        filt = ";".join(parts) + f";{mix}amix=inputs={len(n.clips)}:normalize=0,aresample=48000,loudnorm=I=-16:TP=-1.5[aout]"
        cmd += ["-filter_complex", filt, "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
            "-movflags", "+faststart", "-r", "30", "-shortest", str(out)]
    subprocess.run(cmd, check=True)
    print("saved", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--out", default="dalil-demo.mp4")
    ap.add_argument("--voice", default=None, help="path to a Piper .onnx voice")
    ap.add_argument("--speaker", type=int, default=539, help="speaker id for multi-speaker voices")
    a = ap.parse_args()
    asyncio.run(run(a.url.rstrip("/"), Path(a.out), a.voice, a.speaker))
