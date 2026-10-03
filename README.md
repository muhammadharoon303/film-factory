# Film Factory - automated daily AI short film -> YouTube (free, cloud-only)

Runs on GitHub Actions (public repo = free, 4 vCPU/16 GB, 6 h per job). Your devices are only needed once, for setup.

## Setup (about 20 minutes)
1. Create a **public** GitHub repo and push this folder to it.
2. Run `scripts/get_youtube_token.py` once (see the docstring - remember to publish the OAuth app to "In production").
3. Repo -> Settings -> Secrets and variables -> Actions -> add `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
   Optional but recommended: `GROQ_API_KEY` (free tier, much faster writing) and `HF_TOKEN` (free, avoids download throttling).
4. Repo -> Settings -> Actions -> General -> Workflow permissions -> **Read and write**.
5. Actions tab -> *film-factory* -> **Run workflow** with force = 1 to test the first film.
6. Edit `config.yaml` any time: genre, language, channel name, interval, max duration, voices, publish time.

## How it behaves
* Cron wakes every 3 h; `--check` costs seconds. A film is produced only if the current schedule slot has none.
* Failed attempts are logged and retried on the next tick (max `max_attempts_per_slot`), then skipped; the next slot starts clean.
* Log: `data/VIDEO_LOG.md` (human) and `data/state.json` (machine), committed by the bot. Failed runs keep final.mp4 as an artifact for 3 days.

## Known limits (be aware)
* "Film" = AI illustrated shots with camera motion + voices + subtitles + music. Free CPU runners cannot do real text-to-video.
* New API projects: videos uploaded by an unaudited project are locked **private** until you pass Google's API compliance audit.
* YouTube may treat fully automated, repetitive content as "inauthentic/mass-produced" (monetization risk). Vary genres/themes.
* Daily quota 10,000 units; an upload costs about 1,600.
* GitHub disables scheduled workflows after 60 days without repo activity; the bot's log commits normally keep it alive.
* Check licenses: Piper voice MODEL_CARDs, SD 1.5 (OpenRAIL-M), Qwen2.5-7B (Apache-2.0), Llama (Groq).
* For CJK/Arabic subtitles, add a Noto font package to the workflow apt step and set `render.subtitle_font`.
