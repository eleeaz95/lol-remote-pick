# Contributing to LoL Remote Pick 🤝

Thank you for your interest in contributing to **LoL Remote Pick**!  
Whether you want to fix a bug, add support for new League features, or improve the mobile UI, all contributions are welcome.

---

## 🛠️ Development Setup

### 1. Prerequisites
- **Python 3.10+** (or [uv package manager](https://github.com/astral-sh/uv))
- **Git**
- League of Legends client (optional for development; you can use the built-in **Mock Simulator**)

### 2. Clone the Repository
```bash
git clone https://github.com/eleeaz95/lol-remote-pick.git
cd lol-remote-pick
```

### 3. Set Up Virtual Environment & Dependencies
```bash
# Using standard Python:
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
pip install pytest pytest-asyncio pyinstaller
```

Or with `uv`:
```bash
uv sync
```

---

## 🚀 Running in Development Mode

### Running with Mock Simulation (No League Client needed)
```bash
python run.py --mock --reload --open
```
This runs the backend with auto-reload and spins up an internal Mock LCU server simulating queue states, champion selection, and timer transitions.

### Running against Live League Client
```bash
python run.py --reload --open
```

---

## 🧪 Testing

Always run the full test suite before submitting a Pull Request:

```bash
# Run tests with pytest:
pytest -v

# Or with uv:
uv run pytest
```

---

## 📝 Commit Conventions

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

- `feat: ...` — New feature or capability
- `fix: ...` — Bug fix
- `docs: ...` — Documentation changes
- `style: ...` — Formatting, CSS, or visual tweaks
- `refactor: ...` — Code restructure without behavioral change
- `test: ...` — Adding or updating test cases
- `chore: ...` — Maintenance, dependencies, build configs

---

## 📦 Submitting a Pull Request

1. Fork the repository and create a new feature branch:
   ```bash
   git checkout -b feature/my-amazing-feature
   ```
2. Make your changes and ensure all tests pass (`pytest`).
3. Commit with a descriptive message.
4. Push to your fork and open a **Pull Request** against `main`.
5. Fill out the PR template with details about what you changed and how you tested it.
