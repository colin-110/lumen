# Contributing to Lumen

First off, thank you for considering contributing to Lumen! It's people like you that make open source such a great community.

## Development Workflow

1. **Fork & Clone**: Fork the repository and clone it locally.
2. **Setup**: Run the `setup.ps1` script to initialize your `.env` files.
3. **Install Dependencies**: 
   - Backend: `cd backend && poetry install`
   - Frontend: `cd frontend && npm install`
4. **Pre-commit Hooks**: We use `pre-commit` to enforce code quality. Run `pre-commit install` in the root directory.
5. **Branching**: Create a new branch for your feature (`git checkout -b feature/amazing-feature`).
6. **Testing**: Ensure all tests pass (`pytest` in backend).
7. **Commit & Push**: Push your changes and open a Pull Request.

## Code Standards

- **Python**: We strictly use `ruff` for linting and formatting. All backend code must be typed.
- **TypeScript**: We use `eslint` and Prettier. Strict TypeScript mode is enabled.
- **Commit Messages**: Please use Conventional Commits (e.g., `feat: added semantic cache`, `fix: resolving memory leak in qdrant`).

## Getting Help
If you need help, feel free to open an issue or start a discussion on GitHub.
