# Agentic Workflows

A collection of skills and tools for working with AI coding agents (pi /
Claude). Each subdirectory is self-contained — own docs, own scripts.

## Contents

| Directory | What it is |
|-----------|------------|
| [`ai-judge/`](ai-judge/) | LLM-as-a-judge for voice-AI call transcripts: a deterministic pre-pass that catches "false success" defects by cross-referencing agent speech against the system action log, plus an LLM judge that scores the call against a rubric with verbatim-quoted evidence. |
| [`resume-tailoring/`](resume-tailoring/) | Workflow for tailoring a master `.docx` resume to a specific job posting or recruiter message. Edits the Word XML in place so fonts, styles, numbering, and hyperlinks survive; compression is subtractive (cut oldest roles first, never the most recent). |
| [`writing-skills/`](writing-skills/) | Guidance for authoring, testing, and deploying `SKILL.md` files — TDD applied to process documentation (write a pressure scenario, watch an agent fail without the skill, write the skill, verify compliance). |
| [`code-simplicity-reviewer/`](code-simplicity-reviewer/) | A skill that reviews code through a minimalism/YAGNI lens: flags unnecessary complexity, redundant code, and premature abstractions. |

## Documentation

Each component carries its own deep docs — start there:

- **ai-judge** → [`ai-judge/README.md`](ai-judge/README.md) — input transcript
  format, prerequisites, quick start, judge flags, pre-pass checks, output schema
- **resume-tailoring** → [`resume-tailoring/README.md`](resume-tailoring/README.md)
  — directory layout, requirements, quick start, resume-format assumptions
- **writing-skills** → [`writing-skills/SKILL.md`](writing-skills/SKILL.md)
- **code-simplicity-reviewer** → [`code-simplicity-reviewer/SKILL.md`](code-simplicity-reviewer/SKILL.md)

## Privacy

This is a public repo. Personal and interview-derived assets are **never
versioned** — they stay local via `.gitignore`:

- `*.docx` / `*.pdf` (resume masters, LinkedIn exports)
- `findings/` / `judgments/` (local AI-judge transcript analyses)

A clone contains only code, docs, and skills.

## License

GNU General Public License v2 — see [`LICENSE`](LICENSE).