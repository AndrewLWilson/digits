# Contributing to Digits

Thank you for wanting to help with Digits. The project has not been released
yet and does not have a license, so contributions can only be accepted once a
license has been chosen.

## Proposing a change

1. For anything larger than a small fix, open an issue first that describes
   the problem or the workflow you want to support.
2. Keep each pull request to a single purpose. Refactoring and behavior
   changes go in separate pull requests.
3. In the pull request description, explain what users will notice and which
   approval or safety boundary, if any, the change affects.

## Keep it generic

Digits ships mechanisms, never the configuration of a particular organization.

- Company names, accounts, channels, repository lists and profiles belong in
  private bindings (`~/.config/digits/context/`, with templates in
  [examples/private-bindings/](examples/private-bindings/)), never in this
  repository.
- Examples use only `example-org`, `example.com` and `example.invalid`.
- Never commit credentials, tokens, MCP files that contain secrets, chat
  transcripts or session state.
- If your fork started out as a private harness, run the private-terms guard
  locally before you push (see [Make it yours](README.md#make-it-yours)).

## Tests

For every behavior you add or fix, add a few targeted tests, preferably in an
existing test file. Each test must fail when your change is reverted. Tests
only use temporary home directories, isolated tmux sockets and mocked
services; they never reach live services or real user configuration.

Before opening a pull request, run the checks listed under
[Verification](README.md#verification), including both guards against your
staged changes.

## Commits

Follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
with the types `feat:`, `fix:`, `docs:`, `test:`, `refactor:` and `chore:`.
Write a short subject in the imperative mood. Mark a breaking change with `!`
after the type or with a `BREAKING CHANGE:` footer.

## Code of conduct

Everyone taking part in this project is expected to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
