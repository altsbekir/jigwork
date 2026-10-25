# jigwork user guide

Türkçe: [docs/tr/rehber.md](../tr/rehber.md)

## What jigwork does
A small model that runs on your own computer can write good code, but only in small, clearly
described steps. Given a large, vague job, it gets lost. jigwork lets such a model work on a
real project anyway:

- You (or a larger model) split the work into **small tasks**, each with a short list of
  conditions that tell when the task is done.
- jigwork gives the tasks to a coding **agent** (a program that lets the model read and edit
  files; jigwork uses Qwen Code) one at a time, each in a fresh session.
- The agent cannot run commands and cannot write outside the project. jigwork runs your lint
  and tests itself, in an isolated **sandbox**.
- If a check fails, the model gets the error and a few chances to fix it. What passes is
  committed to git; what does not is saved, and the work tree is put back.

So every step is checked, and every step can be undone.

## Contents
1. [Requirements](#1-requirements)
2. [Install](#2-install)
3. [First-time setup](#3-first-time-setup)
4. [Creating a project](#4-creating-a-project)
5. [Writing tasks](#5-writing-tasks)
6. [Running tasks](#6-running-tasks)
7. [Working with the agent directly](#7-working-with-the-agent-directly)
8. [The model server](#8-the-model-server)
9. [Settings](#9-settings)
10. [What is protected, and what is not](#10-what-is-protected-and-what-is-not)
11. [Troubleshooting](#11-troubleshooting)

## 1. Requirements
- **Linux.** macOS is planned; on Windows, use WSL2.
- **Python 3.11 or newer**, **git**, and **bubblewrap** (the `bwrap` command, which jigwork uses
  for the sandbox). On Arch: `sudo pacman -S bubblewrap`. On Debian/Ubuntu:
  `sudo apt install bubblewrap python3-venv`; Ubuntu 24.04 and later also block bubblewrap by
  default (AppArmor); `jigw doctor` shows it, and
  `sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0` lifts it.
- **Qwen Code**, the agent: `npm install -g @qwen-code/qwen-code`. jigwork was tested with
  version 0.26.0; `jigw doctor` checks the version you have.
- **A model server**: a program that runs the model and answers requests over an
  OpenAI-compatible API. jigwork comes with ready settings for llama.cpp running
  Qwen3.6-35B-A3B on an 8 GB GPU and can build and run it for you (section 8). Any other such
  server also works: Ollama, LM Studio, or one on another machine.

## 2. Install
jigwork is installed from its source with [uv](https://docs.astral.sh/uv/):

```fish
git clone https://github.com/altsbekir/jigwork.git ~/src/jigwork
uv tool install --editable ~/src/jigwork
jigw --version
```

`--editable` makes the installed `jigw` command run the code in that folder, so a `git pull`
there is all an update takes. If your shell does not find `jigw`, add uv's command folder to
your PATH (fish: `fish_add_path ~/.local/bin`) and open a new terminal.

The command is `jigw`; `jigwork` is the same command under its full name.

**Optional:** tab completion for fish. It is generated from the commands, so run this again
after an update:

```fish
jigw completion fish > ~/.config/fish/completions/jigw.fish
```

**Language:** jigwork speaks English and Turkish. It follows your system language; to choose
one yourself: `jigw lang en`, `jigw lang tr`, or `jigw lang auto` to follow the system again.

## 3. First-time setup
Run these once:

```fish
jigw setup
jigw doctor
```

**`jigw setup`** writes the settings that lock the agent down into Qwen Code's settings file,
`~/.qwen/settings.json`: the tools that run commands are removed, writes are kept inside the
project, the files jigwork depends on are protected, and Qwen Code is pointed at your model
server with the right context size and sampling. Your existing settings are kept and the old
file is backed up first (`settings.json.backup-<date>`).

**`jigw doctor`** checks your machine: hardware, installed tools, the model server and the
agent settings. Then it tests the protections for real: it runs Qwen Code with your settings
against a fake model that tries every known way out, and runs the sandbox against your real
home folder. It changes nothing on your system. Every line should show ✔; for anything else it
says what to do.

If jigwork should also run the model server for you, see section 8 (`jigw server setup`).

## 4. Creating a project
```fish
jigw init --type python ~/Projects/todo
```

Types: `python`, `c-cpp`, `generic` (the default: no checks until you add some).

- If the folder is **empty or does not exist**, jigwork creates the project, makes it a git
  repository and commits the first version.
- If the folder **already has files**, jigwork only adds what is missing. It never overwrites a
  file and does not commit; look at the changes with `git status` and commit them yourself. If
  you already have an `AGENTS.md`, jigwork leaves it alone and shows the lines you may want to
  add to it.

What you get:

| Path | What it is for |
|---|---|
| `AGENTS.md` | Rules the agent reads in every session. Keep it short. |
| `docs/ARCHITECTURE.md` | What the program does, its folder layout and main decisions. **Fill this in first**: the agent reads it before creating files. |
| `docs/TASKS.md` | The task list (section 5). |
| `docs/STATUS.md` | A log with one row per finished task. jigwork writes it. |
| `.jigwork/config.toml` | How this project is checked: lint, tests, limits (section 9). |
| `.jigwork/work/` | Logs, saved patches. Not committed. |
| `.qwen/` | Qwen Code's files for this project, such as the coding conventions ("skills") it is given. |

Writing the architecture and the task list is planning work; a larger model (or you) does it
well. The local model's job is to carry out the tasks.

## 5. Writing tasks
A task in `docs/TASKS.md` looks like this:

```markdown
## T1: Parse a todo line
status: pending
type: code
files: src/todo/model.py, tests/test_model.py
task: Write parse_line(text) that turns "[x] buy milk" into Todo(done=True, title="buy milk").
acceptance:
- "[ ] a" gives done=False, title="a"
- "[x] a" gives done=True
- any other format raises ValueError
- tests for all three cases exist and pass
```

| Field | What to write |
|---|---|
| `## T1: ...` | A number and a short title. Tasks run in this order. |
| `status` | Write `pending`. jigwork changes it to `done` or `failed`; you can set `skip`. |
| `type` | `code`, `test` or `docs`. It decides which coding conventions go into the prompt. |
| `files` | The files the agent should read or change. Files that do not exist yet are fine: the agent is told to create them. |
| `task` | What to do, in a few sentences. |
| `acceptance` | When the task counts as done: concrete points that can be checked. |

**Keep tasks small:** one job each, ideally one to three files, testable on its own. A task
that fails again and again is almost always too big or too vague; split it, or make the
acceptance points more precise.

Check the file before running it:

```fish
jigw tasks lint
```

It reports mistakes such as a missing acceptance list, an unknown status or a duplicate number.

## 6. Running tasks
```fish
jigw run           # work through all pending tasks, in order
jigw run --one     # only the next one
jigw status        # show the task list
jigw status --stats  # per task: agent sessions, time, tokens, speed
jigw check         # run the checks against the current code, without the agent
```

jigwork refuses to start while you have uncommitted changes. That way every task starts from a
clean commit and can be undone with git.

**What happens for each task:**
1. A fresh agent session gets only this task: its text, its files, its acceptance points, the
   rules for how to work, and the coding conventions for its type. The progress shows on screen.
2. When the session ends, jigwork checks that the agent did not touch git's own settings, and
   puts back any protected file it changed.
3. Simple formatting problems are fixed automatically (for Python: `ruff format`), then the
   checks run in the sandbox. The first failing check stops the rest.
4. **If a check fails,** its output goes back to the agent as a fix attempt. By default a task
   gets three attempts in total.
5. **If the checks pass,** the task is marked `done`, a row is added to `docs/STATUS.md`, and
   everything is committed.
6. **If all attempts fail,** the agent's last version is saved as a patch in `.jigwork/work/`,
   the files go back to how they were, the task is marked `failed` and the run stops. Tasks
   after it wait, because they usually build on it. Make the task smaller or clearer and set it
   back to `status: pending`, or set `status: skip` to go on without it.

**"Human review".** A small model sometimes makes failing checks pass by changing the test
instead of the code. When a fix attempt changed only test files, or a test lost test cases or
assertions, the task is still accepted, but jigwork warns, writes `human review` into
`docs/STATUS.md` and the commit message, and `jigw status` shows `⚑ human review` next to it.
Look at the commit (`git show`) and check that the tests still test what the task asks.

**When the agent needs a command.** The agent cannot install packages or run migrations. When a
task needs that, the run stops and shows the command. That command runs **with your rights and
outside the sandbox**, so read it before running it. Run it yourself, then continue
(a server jigwork started stays up meanwhile):

```fish
jigw resume
```

For a missing Python package, the better way is to add it to `dependencies` in
`pyproject.toml`: jigwork installs it into the test environment itself.

**Measuring.** `jigw bench` runs a task set several times, each time on a fresh project, and
writes a table with medians and ranges (one run says little: the model's answers vary). It
uses your model server and takes as long as the runs do:

```fish
jigw bench examples/todo --repeat 3
```

## 7. Working with the agent directly
```fish
jigw chat
```

starts Qwen Code in the current project for an ordinary conversation, with the same
restrictions as `jigw run`. It refuses to start in your home folder, outside a git repository,
or with Qwen Code's "approve everything" mode (`--yolo`), and asks first if there are
uncommitted changes. When you quit, it checks git's settings and offers to undo any change. Any
arguments are passed on to Qwen Code, for example `jigw chat -c` to continue the last session.

## 8. The model server
jigwork needs a running model server, but it does not matter who starts it: you, a desktop
shortcut, another tool, or jigwork itself. jigwork follows these rules:

- **A server that is already running** is used and never stopped by jigwork.
- **If no server is running** and jigwork manages one (see below), `jigw run` and `jigw chat`
  start it, wait for the model to load, and stop it again when they finish. A run that stops
  to wait for you (a command to run, then `jigw resume`) leaves it up; `jigw resume` starts it
  only if the agent has to work again. To keep it running always, set `stop_when_done = false`
  (section 9).
- **If the server stops in the middle of a task** (you close it, it crashes), the attempt does
  not count against the task. What the agent had written so far is saved as a patch and undone,
  and jigwork waits up to five minutes. It never starts a server that someone stopped. If the
  server comes back, the attempt starts again; if not, the run stops and you continue later with
  `jigw resume`.
- **If the server runs with different settings** than the agent expects (a smaller context, for
  example), jigwork says so before the run starts.

**Letting jigwork manage llama.cpp.** jigwork can build llama.cpp and run it as a background
service of your user account (a systemd user service):

```fish
git clone https://github.com/ggml-org/llama.cpp ~/llama.cpp   # once
jigw server build     # update ~/llama.cpp (git pull) and build it with CUDA
jigw server setup     # create the service with settings for your model and GPU
jigw server start | stop | status | logs   # start it, stop it, see its state, follow its log
```

`jigw server build` needs the CUDA toolkit (`nvcc`; on Arch: `sudo pacman -S cuda`).

The ready-made settings (a "profile") are for Qwen3.6-35B-A3B on an 8 GB GPU with 32 GB of RAM:
a 64K context, the GPU filled automatically, the model's recommended sampling. They also keep
the server's prompt cache warm between sessions, which is where the speed comes from: the first
request after the server starts takes about a minute and a half, later sessions start in about
ten seconds.

**Using another server** (Ollama, LM Studio, a remote machine): set its address in
`~/.qwen/settings.json` (`baseUrl` of the model provider) and tell jigwork not to manage
anything: `manage = "never"` in your settings (section 9).

## 9. Settings
**For one project:** `.jigwork/config.toml`. `jigw init` writes it; you will mostly change the
checks.

```toml
[prepare]
kind = "python-venv"   # a test environment outside the project with pytest, ruff and the
                       # dependencies from pyproject.toml; "none" for other projects
[autofix]
command = "ruff format --no-cache --quiet . ; ruff check --no-cache --fix --quiet . ; true"
[checks]               # run in this order; the first failure stops the rest
lint = "ruff check --no-cache ."
test = "python -m pytest -q -p no:cacheprovider"
[skills]               # coding conventions given to the agent, by task type
code = ["python-code", "python-test"]
[limits]
attempts = 3           # first attempt plus fixes
agent_wall_time = "45m"
agent_tool_calls = 80
check_timeout = 600    # seconds per check
```

A project without checks still works, but then a task is accepted on the agent's word; jigwork
warns about it.

**For your user account:** `~/.config/jigwork/config.toml`. Everything here is optional.

```toml
lang = "en"                      # what `jigw lang` writes
[server]
profile = "qwen3.6-35b-a3b/rtx4060-laptop-8gb"
llama_dir = "~/llama.cpp"
model_file = "~/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
port = 8091
manage = "auto"                  # "never": jigwork never starts or stops a server
stop_when_done = true            # stop a server jigwork started when the run ends
outage_wait = 300                # seconds to wait for a server that went away
load_wait = 600                  # seconds to wait for the model to load
```

After changing the port, the profile or the model file, run `jigw server setup` and then
`jigw setup`, so the server and the agent agree.

## 10. What is protected, and what is not
**Protected.** `jigw doctor` tests each of these on your machine:
- **The agent cannot run commands.** Every tool that could run a command is removed, not just
  forbidden in the instructions: told "you have no shell", a small model goes looking for
  another way.
- **The agent can write only inside the project**, and not to git's folder (`.git/`), its own
  settings (`.qwen/`), jigwork's files (`.jigwork/`, `AGENTS.md`, `docs/TASKS.md`,
  `docs/STATUS.md`), `pyproject.toml`, or `.env` files. A project's own Qwen Code settings
  cannot turn this off.
- **git is watched.** A single line in `.git/config` could make git run a command on your
  computer the next time you use it. jigwork checks these files after every session.
- **The checks run in a sandbox** with no network and no view of your home folder, `/tmp` or
  `/run`; git's folder, the protected files and the test environment are read-only there.
- **The agent has no web access.**

**Not protected, on purpose:**
- **Commands the agent asks you to run** run as you, with nothing in between. Read them; watch
  for misspelled package names.
- **Running your project's code yourself** means running code the model wrote, outside any
  sandbox.
- **Dependencies** in `pyproject.toml` are installed on your computer with pip. The agent cannot
  change that file; you decide what goes in it.
- **MCP servers** you add to Qwen Code are not limited by jigwork. `jigw doctor` warns if you
  have any.
- **Running `qwen` directly**, without `jigw`, keeps the settings `jigw setup` wrote, but not
  jigwork's checks of git and the protected files.

## 11. Troubleshooting
| What you see | What to do |
|---|---|
| "Security settings are missing" | Run `jigw setup`. |
| "No model server answers" | Start your server, or let jigwork manage one: `jigw server setup`. |
| The first request of a run is slow | Normal: about 1.5 minutes while the prompt cache warms up. A server left idle for hours can be slower at first. |
| A task keeps failing | Read the check output in `.jigwork/work/log/` and the patch of the last attempt. Usually the task is too big or its acceptance points are vague. |
| "The interrupted attempt's changes were saved as a patch" | The model server went away during a task; see section 8. |
| Anything about the sandbox or the agent | Run `jigw doctor`, and include its output when you ask for help. |

**Exit codes** of `jigw run` and `jigw resume`, for scripts: `0` finished (or nothing to do),
`1` a task failed or the run could not start (the message says why), `2` the agent needs you to
run a command, `3` the model server went away, `130` stopped with Ctrl-C.
