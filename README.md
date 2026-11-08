# Grounded Learning Wiki

An extension to Karpathy's LLM Wiki pattern. Before it answers, the wiki checks whether it understood
the question. It records what it lacks and goes looking for it. The model never supplies a number. And
the wiki teaches its owner as it grows.

- [`IDEA.md`](IDEA.md): the idea file. Read this first; give it to your agent.
- [`skill/grounded-learning-wiki/`](skill/grounded-learning-wiki/): a Claude Code skill (`SKILL.md`)
  and the checker `glw.py`. The checker uses only the standard library and needs Python 3.11 or later.
  To install, copy the folder into `~/.claude/skills/`.
- [`example/`](example/): a small sourdough wiki. Its source texts are illustrative only.
- [`tests/`](tests/): `python -m unittest -q` from inside `tests/`.

Try it on the example:

```bash
python skill/grounded-learning-wiki/glw.py check --root example --strict
```

```bash
python skill/grounded-learning-wiki/glw.py resolve --root example -- "What is the ash content of T60 flour?"
```

The second command answers `needs_clarification`. It offers T55, T65 or T80, because T60 is not in
the wiki, and it does not quote a neighbouring flour's figure.

MIT licence, see [LICENSE](LICENSE).
