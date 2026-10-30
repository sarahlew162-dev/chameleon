# Project Chameleon

This repository contains a design-resizing engine for the Adobe University
Hackathon Project Chameleon challenge. It reads design-task JSON files from
`input/`, adapts each design to its target canvas, and writes resized JSON and
PNG previews to `output/`.

## What the solution does

The resizing logic is in `engine/resize.py`. It uses deterministic,
rule-based layout decisions; it does not call an AI service or require model
weights. Similar aspect ratios retain proportional sizing, while more
extreme layouts reflow elements. Wide layouts use an image-led panel with
overlaid copy; short banners use a compact layout.

The engine preserves the input elements and their content. It does not
generate or replace image pixels.

## Design goals and evaluation

The goal is to preserve the design's visual hierarchy, readability, and
important elements across canvas sizes—not merely stretch the original
coordinates. The engine keeps grouped elements together, preserves image
proportions, and changes text size and placement to fit the target while
keeping the original wording and font family.

Develop and review outputs incrementally: start with common formats and
nearby aspect ratios, then test wider, taller, and more constrained formats.
The supplied samples cover three challenge levels, but passing them does not
guarantee quality on unseen designs. Inspect every rendered PNG at its actual
size and treat results as a best-effort solution to a deliberately difficult
layout problem.

## Requirements

- Python 3.11 (the version used by the supplied Dockerfile)
- Dependencies listed in `requirements.txt`:
  - Pillow
  - `cr-renderer`, installed from the repository URL in the requirements file
- No AI model, API key, or model weights are required by this solution.

Installing `cr-renderer` from its Git repository requires Git and network
access during dependency installation. The challenge container is intended
to run offline after its image is built.

## Run locally on Windows

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m engine.main
```

The command processes every `*.json` file in `input/` and writes matching
`*_output.json` and `*_output.png` files to `output/`. The repository includes
one sample task for each challenge level. The output JSON is the resized
design; the PNG is a visual preview.

To try a different target size, copy a sample task JSON, change its
`target_canvas.width` and `target_canvas.height`, and place the task in
`input/` before running the command again. Do not overwrite the supplied
samples if you want to keep the original test cases.

## Run with Docker

Build the image from the repository root:

```powershell
docker build --platform linux/amd64 -t my-chameleon-engine .
```

Run the engine with the input and output folders mounted:

```powershell
$repo = (Get-Location).Path
docker run --rm --network none `
  --mount "type=bind,source=$repo\input,target=/app/input" `
  --mount "type=bind,source=$repo\output,target=/app/output" `
  my-chameleon-engine
```

The `--network none` option matches the challenge's offline runtime
expectation. Dependencies and any required model files must be included in
the image at build time; this solution has no model files.

## Preview and validation

Review the generated PNGs at their actual canvas dimensions, especially
small banners where text may be difficult to read. The engine's self-check
reports structural issues such as missing IDs, required fields, or
off-canvas elements. A passing self-check does not guarantee visual quality
or an official challenge score.

The renderer uses the supplied assets in `brand_kit/assets/` and fonts in
`brand_kit/fonts/`. If a preview shows labeled placeholder boxes rather than
the actual design, verify that the renderer dependencies installed
successfully. Do not evaluate layout quality from a placeholder preview.

## Hackathon submission notes

Keep the team's GitHub repository private, as requested in the hackathon
session notes. Teams seeking technical feedback can contact the Hackathon
team and should include **"Feedback"** in the email subject line. Follow the
latest organizer instructions for the submission process and deadline.

## AI and challenge-rule notes

The supplied `RULES.md` does not state a blanket prohibition on using AI for
layout decisions. It does say that:

- If a solution relies on a fine-tuned or adapted model, its weights must be
  publicly accessible so the solution can be independently reproduced.
- The engine must work offline at runtime; dependencies and model weights
  cannot be downloaded or accessed through an API during scoring.
- Generating, redrawing, or replacing image pixels is disqualifying.
- For stage-one scoring, preserve the original text and font family; changing
  font size to help text fit is allowed.

These are notes based on the rules included in this repository. Check the
latest official challenge materials for any additional requirements or
clarifications.

## Project files

- `engine/resize.py` — resizing and reflow logic
- `engine/main.py` — task loading, self-checking, rendering, and output
- `input/` — sample task JSON files
- `output/` — generated JSON and PNG previews
- `renderer/` — design-to-renderer conversion code
- `brand_kit/` — supplied image assets and fonts
- `chameleon_design_schema_v0.9.json` — design JSON schema
- `RULES.md` and `FAQ.md` — challenge rules and clarifications
