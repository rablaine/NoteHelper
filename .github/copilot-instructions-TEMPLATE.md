# Copilot Instructions

## Project Overview

**Project Name:** [Your project name]

**Description:** [Brief description of what this project does and its main purpose]

**Target Users:** [Who will use this application]

## Technology Stack

**Language(s):** [e.g., Python 3.11, TypeScript, C#]

**Framework(s):** [e.g., React, ASP.NET Core, Django, Express]

**Database:** [e.g., PostgreSQL, MongoDB, SQLite]

**Key Libraries/Packages:**
- [Library 1 - purpose]
- [Library 2 - purpose]
- [Library 3 - purpose]

**Build/Package Tools:** [e.g., npm, pip, dotnet, Maven]

## Project Structure

```
[Describe your folder structure, e.g.:]
/src
  /components    - Reusable UI components
  /services      - Business logic and API calls
  /utils         - Helper functions
  /models        - Data models and types
/tests           - Unit and integration tests
/docs            - Additional documentation
```

## Coding Standards & Best Practices

### Code Style
- [e.g., Use PEP 8 for Python, ESLint Airbnb config for JavaScript]
- [e.g., Prefer functional components with hooks over class components]
- [e.g., Use async/await instead of .then() for promises]

### Naming Conventions
- **Files:** [e.g., kebab-case for components, camelCase for utilities]
- **Variables:** [e.g., camelCase for local variables, UPPER_CASE for constants]
- **Functions:** [e.g., camelCase, use verb prefixes like get, set, handle, on]
- **Classes:** [e.g., PascalCase]
- **Interfaces/Types:** [e.g., PascalCase, prefix with 'I' or not]

### Code Organization
- [e.g., One component per file]
- [e.g., Group related functions in service classes]
- [e.g., Keep functions under 50 lines when possible]
- [e.g., Extract magic numbers into named constants]

### Error Handling
- [e.g., Use try-catch blocks for async operations]
- [e.g., Log errors with context information]
- [e.g., Return meaningful error messages to users]

### Testing
- [e.g., Write unit tests for all business logic]
- [e.g., Use Jest for JavaScript testing]
- [e.g., Aim for 80% code coverage]
- [e.g., Mock external dependencies in tests]

## Architecture Patterns

**Design Pattern(s):** [e.g., MVC, MVVM, Repository Pattern, Clean Architecture]

**State Management:** [e.g., Redux, Context API, Zustand]

**API Design:** [e.g., RESTful, GraphQL, gRPC]

## Dependencies & Environment

**Required Environment Variables:**
```
[List required env vars, e.g.:]
DATABASE_URL=
API_KEY=
PORT=
```

**Prerequisites:**
- [e.g., Node.js 18+]
- [e.g., Python 3.11+]
- [e.g., Docker]

## Development Workflow

**Setup:**
```bash
[Commands to set up the project, e.g.:]
npm install
cp .env.example .env
npm run db:migrate
```

**Running Locally:**
```bash
[Commands to run the project, e.g.:]
npm run dev
```

**Building:**
```bash
[Commands to build, e.g.:]
npm run build
```

**Testing:**
```bash
[Commands to test, e.g.:]
npm test
npm run test:coverage
```

## Documentation Standards

- [e.g., Use JSDoc comments for all exported functions]
- [e.g., Include README.md in each major module]
- [e.g., Document complex algorithms with inline comments]
- [e.g., Keep API documentation up to date in /docs/api]

## Security Considerations

- [e.g., Never commit secrets or API keys]
- [e.g., Sanitize all user inputs]
- [e.g., Use parameterized queries to prevent SQL injection]
- [e.g., Implement rate limiting on public endpoints]

## Performance Guidelines

- [e.g., Lazy load components when possible]
- [e.g., Optimize database queries with proper indexes]
- [e.g., Cache frequently accessed data]
- [e.g., Minimize bundle size]

## Git & Version Control

**Branching Strategy:** [e.g., Git Flow, trunk-based development]

**Commit Message Format:** [e.g., Conventional Commits - feat:, fix:, docs:, etc.]

**Pull Request Requirements:**
- [e.g., All tests must pass]
- [e.g., Code review required]
- [e.g., No merge conflicts]

## Additional Notes

[Any other project-specific guidelines, quirks, or important information that Copilot should know]

---

**Last Updated:** [Date]
