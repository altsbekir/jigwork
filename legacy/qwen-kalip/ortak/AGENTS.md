# Project: {{PROJE_ADI}}

Rules for every coding agent (Qwen, Claude, GPT, ...) working in this repo.
This file is loaded into every session, so it stays short.

## Where things are
- Architecture and folder layout: docs/ARCHITECTURE.md. Read it before creating files or folders.
- docs/TASKS.md (task list) and docs/STATUS.md (progress log) are managed by the orchestrator script. Do not edit them.

## How to work
- You get ONE task at a time. Do exactly that task, nothing more.
- Read only the files the task lists, plus what they directly import.
- Make the smallest change that satisfies the acceptance criteria.
- Do not refactor, rename or reformat code the task does not mention.
- Do not add dependencies, new top-level folders or config files. If the task needs one, stop and report it.
- If the task is unclear or looks wrong, stop and report. Do not guess.
- No placeholder code. Never present a stub or a TODO as finished work.

## Safety
- Never touch .git/, .env files, keys, or anything outside this project folder.
- Never delete files. If a file should be removed, say so in your report.
- You cannot run commands. Lint, build, tests and git are run for you after you finish.
- If the task needs a command (install a package, a migration, a git operation), do not look for a workaround.
  Write the exact command under NEEDS and stop.

## Report format (your final message)
CHANGED: <files you created or edited>
DONE: <one or two sentences>
NEEDS: <exact commands the user must run, one per line, or "none">
DOUBTS: <anything uncertain, or "none">

## Stack
