# TOOLS.md - Development Environment Notes

This file captures environment-specific configuration for the skill.

## What Goes Here

- Project-specific paths and identifiers
- Preferred package managers (npm/pnpm/yarn)
- Python virtual environment paths
- Database connection strings (without credentials)
- CI/CD pipeline references
- Custom tool configurations

## Example

```markdown
### Package Managers
- Frontend: pnpm
- Backend: pip + venv

### Paths
- Project root: d:/projects/my-app
- Python venv: .venv/

### Database
- Dev: SQLite (local), PostgreSQL 16 (staging)
```

## Why Separate?

Skill references and governance files are shared. Environment-specific notes are local. Keeping them apart allows:
- Reusing the skill across projects without leaking specifics
- Updating skill internals without losing environment config
