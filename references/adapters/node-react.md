# Node + React Adapter

Use this adapter when project reality is a Node backend or React frontend.

## Architecture Defaults

- Prefer TypeScript when the project uses it.
- Keep API client code outside view components.
- Use existing routing, state, and styling conventions.
- Validate external input at backend boundaries.

## Validation Commands

- `npm run typecheck`
- `npm run test`
- `npm run build`

## Notes

- Do not introduce React into Vue projects.
- Do not introduce Node backend assumptions into FastAPI projects.

