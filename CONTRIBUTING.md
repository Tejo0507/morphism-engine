# Contributing to Morphism Engine

First off, thank you for considering contributing to Morphism Engine! It's people like you that make open-source a great community.

## Code of Conduct

By participating in this project, you are expected to uphold our standard community standards:
- Be respectful and welcoming to others.
- Provide constructive feedback.
- Harassment or unacceptable behavior will not be tolerated.

## How Can I Contribute?

### Reporting Bugs
If you find a bug, please open an issue in the GitHub repository. Ensure you include:
- A clear descriptive title.
- Exact steps to reproduce the issue.
- Your OS, Python version, and Morphism version.
- Any relevant logs or traceback (anonymize sensitive values).

### Suggesting Enhancements
Feature requests are always welcome! When opening a proposal:
- Use a clear and descriptive title.
- Explain *why* this feature is necessary and what problem it solves.
- Describe the proposed mathematical/architectural implementation if possible.

### Submitting Pull Requests
1. **Fork the repository** and clone it locally.
2. **Create a new branch** for your feature or bugfix (`git checkout -b feature/my-cool-feature`).
3. **Make your changes** ensuring that you strictly adhere to the project's typing and verification standards.
4. **Write tests**: We enforce a strict testing policy (this project relies heavily on formal validation with Z3). Run all tests locally with `pytest` before submitting.
5. **Commit your changes**: Write clear, concise commit messages.
6. **Push to your fork** and submit a Pull Request.

## Development Setup
```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/morphism-engine.git
cd morphism-engine

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate # or .venv\Scripts\Activate.ps1 on Windows

# Install dependencies
pip install -e ".[dev]"
```

## Security Vulnerabilities
If you discover a security vulnerability (e.g., untrusted AST execution bypassing SMT verification), please DO NOT open a public issue. Email the maintainers directly or use GitHub's private vulnerability reporting feature.

Thank you for contributing!
