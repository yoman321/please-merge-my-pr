# please-merge-my-pr

Rank open pull requests where someone asked you by name to review.

## Setup

```bash
uv sync
```

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
