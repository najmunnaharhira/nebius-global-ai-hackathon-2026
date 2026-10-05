# Dalil — check a land deed's ownership chain before you buy

> Nebius x NVIDIA Global AI Hackathon · **Track: Best Apps and Agents** · Solo project by [@najmunnaharhira](https://github.com/najmunnaharhira)

Dalil is a pre-check for people buying land or a flat in Bangladesh. Upload photos of the deed (dalil), the khatian (record of rights) and mutation papers. Dalil:

1. reads each page,
2. rebuilds the ownership chain from the recorded owner to today's seller,
3. stamps every red flag beside the deed that caused it, and
4. gives you a checklist, in Bangla or English, of what to verify at the sub-registry and land office before you pay.

**Dalil is a pre-check, not legal advice.** Always confirm findings with a lawyer and the land office.

## Why

In Bangladesh, buying land is risky. Common problems include:

- fake deeds
- the same plot sold twice
- seller names that don't match the khatian
- gaps in the ownership chain

Land disputes make up a large share of the civil court backlog. Most buyers can't read old deeds, and a lawyer's first review is slow and costly. Dalil gives every buyer a fast first pass.

## What it checks

| Flag | What it means |
|---|---|
| `OVERSELL` | A deed sells more land than the seller held at that time |
| `DOUBLE_SALE` | The seller had already sold that land in an earlier deed |
| `MISSING_LINK` | Nothing shows how the seller came to own the land |
| `SALE_BEFORE_ACQUISITION` | Land was sold before the seller bought it |
| `NAME_MISMATCH` | The seller's name is close to, but not the same as, the recorded owner's |
| `NO_MUTATION` | No mutation (namjari) in the current owner's name |
| `DAG_NOT_IN_RECORD` / `MOUZA_MISMATCH` | A deed's dag or mouza doesn't match the khatian |
| `PROPOSED_OVERSELL` / `PROPOSED_UNBACKED` | The sale you're offered exceeds what the seller can prove they own |
| `AI_REVIEW` | An extra concern raised by Nemotron 3 Ultra's review of the whole case |

Only land that a valid chain actually backs is passed on to the next owner. If a deed oversells, the extra land is "unbacked" and does not count toward the buyer's holding. This is how Dalil can tell you that the person offering you 25 decimals can prove they own none of it.

## How it uses NVIDIA Nemotron and Nebius Token Factory

Every model call goes through the **Nebius Token Factory** OpenAI-compatible API (`/v1/chat/completions`). Each step is routed to the Nemotron model that fits it:

| Step | Model (Token Factory ID) | Why |
|---|---|---|
| Read page photos | `nvidia/Nemotron-3-Nano-Omni` | Multimodal and fast: one small call per page |
| Read pasted / typed text | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Cheap, quick structured extraction |
| Review the whole chain | `nvidia/Nemotron-3-Ultra-550b-a55b` | Serious reasoning over all documents at once: explains each flag and finds concerns the rules missed |
| Write the bilingual checklist | `nvidia/nemotron-3-super-120b-a12b` | Structured English + Bangla output, tailored to the case |

The design splits the work on purpose:

- A **deterministic rules engine** (`app/chain.py`) rebuilds the chain and raises the core flags, so results are predictable and tested.
- **Nemotron** does what rules can't: reading messy documents, explaining risks in plain language, spotting subtle issues and writing the checklist in two languages.
- If a model call fails, the app still returns the rules-based report and a template checklist. The "How Dalil checked this" panel shows which model handled each step and how long it took.

All model IDs can be changed through environment variables (see `.env.example`).

## Run it locally

Requirements: Python 3.11+.

```bash
git clone https://github.com/najmunnaharhira/nebius-global-ai-hackathon.git
cd nebius-global-ai-hackathon
pip install -r requirements.txt
cp .env.example .env            # then paste your Token Factory key into .env
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload
```

Open http://localhost:8000.

- Click a **sample case** to see a full report instantly.
- Or **upload page photos** of your own documents. Reading uploads needs `NEBIUS_API_KEY`.

Without a key, Dalil runs in **offline mode**: the sample cases and the rules engine work, and the Nemotron steps are skipped and marked as such.

### Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

There are 15 tests. They cover every rule, the three sample cases, model-reply parsing, the API in offline mode, and the live Ultra → Super path with Token Factory mocked.

### Docker / Nebius Serverless Endpoints

```bash
docker build -t dalil .
docker run -p 8000:8000 -e NEBIUS_API_KEY=your_key dalil
```

The same image can be deployed as a Nebius AI Cloud Serverless Endpoint (container port 8000, with `NEBIUS_API_KEY` set as a secret environment variable).

## Demo video

The demo video is recorded from the running app with `tools/record_demo.py`:

```bash
pip install playwright piper-tts && playwright install chromium
curl -L -o voice.tgz https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-us-libritts-high.tar.gz
tar xzf voice.tgz
python tools/record_demo.py --url http://localhost:8000 --voice en-us-libritts-high.onnx --speaker 539
```

The narration uses [Piper TTS](https://github.com/rhasspy/piper) with the LibriTTS voice (CC BY 4.0, speaker 539). Without `--voice`, the video has captions only.

## Project layout

```
app/
  main.py        FastAPI routes: /api/status, /api/samples, /api/extract, /api/analyze
  chain.py       deterministic chain-of-title engine and red-flag rules
  llm.py         Token Factory client and the Nemotron steps (extract, review, checklist)
  checklist.py   bilingual template checklist (fallback and draft for Nemotron Super)
  models.py      Pydantic data models
static/          single-page web app (no build step)
samples/         three synthetic cases with fictional people and places
tests/           pytest suite
tools/           demo video recorder
```

## API

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/status` | – | whether a key is set, and the model IDs in use |
| GET | `/api/samples` | – | the sample cases |
| POST | `/api/extract` | multipart `files` (JPG/PNG/WebP or .txt) | structured documents + trace |
| POST | `/api/analyze` | `{documents, proposed}` | risk, flags, timeline, holdings, checklist, summaries, trace |

## Data and privacy

- Sample cases use **fictional** people, mouzas and deed numbers.
- Uploaded files are sent to Token Factory for reading and are not stored by Dalil.
- Don't upload other people's documents without their permission.

## Limitations

- Reading old or handwritten Bangla deeds is the hardest step. Always review the extracted fields before analysis; the form is editable for this reason.
- Areas are compared in decimals (shatangsho). The extraction prompt converts katha and bigha, but check the numbers.
- Flag titles and details from the rules engine are in English. The summary and checklist switch to Bangla.
- The Bangla checklist text should be reviewed by a native speaker before wider use.

## License

[MIT](LICENSE)
