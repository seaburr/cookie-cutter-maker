# Cookie Cutter Maker (PNG/SVG -> STL) + Local UI (Docker)

This repo generates cookie cutter STL files from:
- **an outline PNG** (offline/local; no OpenAI cost), and optionally
- **a text prompt** (outline PNG via OpenAI Images API if you set `OPENAI_API_KEY`).

It includes:
- a Python pipeline (trace + STL generation),
- a **FastAPI** service wrapping the pipeline,
- a simple **local web UI** for end-to-end use,
- Docker build/run.

## Quick start (Docker)

```bash
docker compose up --build
```

Open:
- UI: http://localhost:8000
- API docs: http://localhost:8000/docs

Generated files land in `./output/<job_id>/`.

## Run tests

```bash
pip install -r requirements.txt
pytest
```

## License

MIT License © seaburr

## Offline flow (recommended)

1. Create or download a **simple black shape on white background** PNG outline.
2. Upload it in the UI.
3. Adjust sliders (wall, flange size, height).
4. Download STL.

No OpenAI calls.

## Prompt flow (optional)

If you want prompt -> outline generation:
1. Set `OPENAI_API_KEY` in your environment (or docker-compose.yml)
2. Use the Prompt tab in the UI or `POST /pipeline/from-prompt`

## CLI

PNG input:

```bash
python -m cutter_pipeline.cli --png examples/pajama_outline.png --outdir output --name pajama
```

## Test / smoke test

```bash
python -m cutter_pipeline.cli --png examples/pajama_outline.png --outdir output --name smoke_test
test -f output/smoke_test.stl
```

## Notes

- Many slicers show a closed-solid-with-void as "solid" unless you use section/cut view.
- The STL topology matches your “circle reference” style: constant ID, OD larger only in flange, slicer-friendly.
