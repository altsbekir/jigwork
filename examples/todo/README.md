# Example: a small todo app

Four tasks that build a command-line todo list in Python, with tests: a data model, loading and
saving a file, list operations, and the command-line interface. The architecture and the task
list are already written, so the run measures how well the model carries out tasks.

```fish
jigw init --type python ~/Projects/todo
cp examples/todo/docs/ARCHITECTURE.md examples/todo/docs/TASKS.md ~/Projects/todo/docs/
cd ~/Projects/todo
git add -A; and git commit -m "todo example tasks"
jigw run
```

Results on the reference machine: [docs/bench-results.md](../../docs/bench-results.md).
