# jigwork

*A jig holds the workpiece and guides the tool, so even an unskilled hand makes accurate,
repeatable cuts.* jigwork does that for small local language models: it turns a model that
runs on an 8 GB laptop GPU into something that finishes real coding tasks, safely.

> **Status: pre-alpha, private.** The working prototype is in `legacy/`. The package described
> below is being built (see `docs/roadmap.md`).

## The idea
Small models are decent at short, well-defined edits and bad at long, open-ended work. So jigwork:

1. splits work into small tasks with acceptance criteria (`docs/TASKS.md` in your project),
2. gives each task to the agent in a **fresh session**, with only that task and the relevant conventions,
3. locks the agent down: no shell, no writes outside the project or to control files,
4. runs lint and tests itself, in a **sandbox with no network and no access to your home folder**,
5. feeds failures back for a bounded number of fix attempts,
6. commits what passes, saves what fails as a patch, and stops when a human is needed.

## First result
Qwen3.6-35B-A3B (Q4_K_M) on an RTX 4060 Laptop (8 GB) + 32 GB RAM, through Qwen Code:
a 4-task Python CLI app with tests, 4/4 tasks done, about 17 minutes in total.
Details: `docs/bench-results.md`.

## Planned commands
```
jigw init --type python     create or adopt a project
jigw run [--one]            work through pending tasks
jigw status | check | resume
jigw chat                   interactive agent session, same restrictions
jigw server start|stop|status|logs|setup
jigw doctor                 hardware, versions and live security self-test
jigw lang en|tr
```

Platforms: Linux first; macOS planned; Windows through WSL2 (a container isolation mode is planned).

Türkçe: `README.tr.md` (yakında).
