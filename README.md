# please-merge-my-pr

Rank open pull requests where someone asked you by name to review.

## Setup

```bash
uv sync
uv run please-merge-my-pr init
uv run please-merge-my-pr
```

The last command starts chat in a terminal. Direct commands remain available:

```bash
uv run please-merge-my-pr list
uv run please-merge-my-pr why owner/repo#123
uv run please-merge-my-pr show owner/repo#123
uv run please-merge-my-pr config show
```

GitHub reads use the environment variable named by `github.token_env`.
Model calls use the optional variable named by `model.api_key_env`.
Local state is stored below `XDG_STATE_HOME`.

Run the checks with:

```bash
uv run pytest -q -x
uv run pytest -q
uv run pytest -q tests/test_file.py::test_name
uv run mypy src
uv run ruff check .
uv run ruff format --check .
uv build
```
