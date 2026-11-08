# Grounded Learning Wiki

*An extension to the LLM Wiki pattern: a wiki that checks a question before it answers, goes looking
for what it lacks, never lets the model make up a number, and teaches its owner as it grows.*

This is an idea file, in the spirit of Karpathy's LLM Wiki gist: a description of a pattern for an
agent to follow, plus a small checker for the rules a script can enforce. It assumes you already have
the base pattern (immutable `raw/` sources, an agent-written `wiki/`, a schema file, and the ingest /
query / lint operations). It adds five operations and three one-way rules.

## Why

The LLM Wiki works, and its known failure modes are known too: the model misreads a source and the
error persists; it answers with the nearest page when the right one does not exist; pages it wrote get
cited by pages it wrote later; gaps are noticed at lint and then forgotten; and checking claims against
sources "is still on you". The owner, meanwhile, reads answers but does not necessarily learn the field.

Every rule below comes from one of those failures, and each was worked out in a real knowledge base
before being written down here.

## The five operations

| Op | Question it answers | Who acts |
|---|---|---|
| **resolve** | Do I know what you are asking about? | Code first, then the agent asks you |
| **seek** | What don't I hold, and where might it be? | Agent, within a policy you set |
| **verify** | Does every claim, and every number, stand on a source? | Code |
| **learn (you)** | What should the owner understand from what happened? | Agent writes, you read |
| **learn (the wiki)** | What should change in how the wiki works? | Agent proposes, you approve |

### 1. resolve: ask before you seek

Before answering, read the question against what the wiki holds. Retrieval always finds a nearest
neighbour; that is exactly how a wiki answers about T60 flour with T65's figures. So:

1. **Repair spelling, and say so.** A word the wiki has never seen is read as the nearest known word,
   within an edit budget (none under 5 letters, 1 edit from 5, 2 from 8; swapped letters count as one).
   The correction is shown to you, and you confirm any that changes the meaning.
2. **Never fuzz a token with a digit in it.** `T60`, `c7`, `v2.1` are identifiers. Near ones are
   *offered* as a question ("T55 or T65? T60 is not in the wiki"), never silently substituted.
3. **Ask back when two readings tie.** If two known words are equally near and neither is much more
   common, the term is ambiguous: ask which one you meant. Do not search; a search engine would pick a
   reading for you.
4. **Choose a subject only when every one of its words matches.** Partial matches are offered, never
   chosen. A question can name several subjects ("T55 or T65?"); all are returned. Two pages matched
   by the same words are asked back.
5. **Ask for the version when the answer depends on one.** A page marked `versioned: true` (with its
   `versions: [v1, v2]` listed) is not answered until the question names one of them (or a context source supplies
   it). A number in the question is not a version.
6. **"Not listed" is never "no".** A subject or fact the wiki lacks is a **gap**, recorded for seek. A
   fact is never borrowed from a neighbouring page.

Clarification comes before seeking: a gap that waits on your answer is not searched yet.

### 2. seek: gaps become leads, under a dial you set

Each gap is a page in `wiki/gaps/` (status `open` → `candidates` → `promoted` or `closed`). The same
gap asked in different words lands on the same page. A gap is searched (the wiki's own raw sources
first, then the web) and re-searched only after a set interval. Hosts the wiki already trusts rank first.

What happens to what seek finds is a **policy**, per source tier, set in `glw.toml`:

| Policy | Found pages are... | Fits |
|---|---|---|
| `auto` | stored in `raw/` with URL, retrieval date and the question that found them, then ingested | notes, news, fast-moving topics |
| `queue` | listed on the gap page as candidates; you promote one into `raw/` | anything a number will be taken from |
| `off` | not searched; the gap is just recorded | private or sensitive areas |

Pages older than `stale_after_days` are refreshed the same way. Local files you wrote never count as
stale.

### 3. verify: the grounding contract

1. **Claims cite raw sources with a quote.** A citation is a footnote naming a file under `raw/` (or an
   external form such as `doi:`) followed by the exact words it relies on:
   `[^t65]: raw/flour-types.md "T65 flour has an ash content of 0.62 to 0.75 percent"`.
   The quote must appear in the file, word for word (whitespace aside).
2. **The model never produces a number.** Every number on a line that cites a source must appear in
   one of that line's quotes. Extract by rule first (tables, `Key: value` lines); use the model only to
   map or phrase, never to supply a value. A number with no citation at all is flagged.
3. **Agreement, supersession, conflict.** A second source with the same value is added as a second
   citation. A newer source that changes a value strikes the old line inline
   (`~~old~~ *(superseded YYYY-MM-DD, see [^new])*`) rather than deleting it. Two sources that disagree
   are both kept and the page says so, dated.

The checker enforces 1 and 2 mechanically. That turns "the checking is still on you" into a script
that runs after every edit.

### 4. learn (you): the wiki teaches its owner

`wiki/learning/` re-explains the wiki's evidence for its owner. It points back to wiki pages instead of
copying them.

- **Session summary** (`learning/sessions/`): any session that adds to `log.md` writes one page before
  it ends: what happened, why it matters, concepts touched, decisions waiting on you, read next. At
  most ~400 words.
- **Daily guide** (`learning/daily/daily-YYYY-MM-DD.md`): yesterday in one paragraph, what was built or
  learned and why, a concept of the day, numbers that changed (before → after), waiting on you,
  self-check questions, read next. It covers every day since the last guide (`covers:` in frontmatter).
  On a day with no activity it teaches the next lesson of a background track instead.
- **Curriculum** (`learning/curriculum.md`): a coverage table of concepts (F = taught in a foundation
  page, D = deepened in a daily guide with its date, B = backlog) and the background tracks.
- **Glossary**: one plain-language entry per new term, each linked to the page that holds its evidence.
- **Voice**: plain language first, then the mechanism, then the number, and every number carries a
  link to the wiki page that holds it. Say "not known" where the wiki says so.

Self-check questions can be exported as flashcards for any spaced-repetition app.

### 5. learn (the wiki): proposals behind a gate

The wiki improves its own working, but only through proposals you approve. Each is a page in
`wiki/proposals/` with a `kind`, a `key`, its evidence and a `status` (`proposed` → `approved` /
`rejected` → `applied`):

- **synonym**: you answered a clarification ("by leaven I meant levain"), so propose the synonym.
- **source-host**: you promoted three candidates from one host, so propose trusting it.
- **lesson**: you corrected an answer, so propose the rule that would have prevented it.
- **schema**: a convention keeps being broken, so propose changing the convention.

Rejected proposals stay on file, and the same key is not proposed again. What you approve and reject is
itself evidence of what matters to you, and seek uses it to rank.

## Three one-way rules

1. **Wiki pages cite raw sources, never wiki pages.** Wikilinks between pages are navigation; a
   citation (footnote) may only point at `raw/` or an external form. This stops derived pages from
   grounding each other.
2. **Learning pages derive from the wiki and are never sources for it.** No wiki page outside
   `learning/` links into it (index and log aside).
3. **Views are projections.** If you mirror the wiki into Obsidian, SiYuan or a database for reading,
   nothing is ever read back from the mirror as a value, and a citation into it is invalid.

## Layout

```
glw.toml                 policy: synonyms, versioned subjects, seek policy, intervals
raw/                     immutable sources (human-curated, or seek with policy auto)
wiki/
  index.md  log.md       as in the base pattern
  <pages>.md             frontmatter: title, aliases, versioned + versions (optional)
  gaps/<slug>.md         one per gap
  proposals/<slug>.md    one per proposal
  learning/
    curriculum.md  glossary.md
    daily/daily-YYYY-MM-DD.md
    sessions/session-YYYY-MM-DD-<slug>.md
    tracks/<track>-<n>.md
```

## What the checker does

`glw.py` (standard library, Python 3.11+):

| Command | Does |
|---|---|
| `check` | citations resolve, quotes are verbatim, cited lines carry only quoted numbers, uncited numbers flagged, the one-way rules, dangling links |
| `resolve "<question>"` | the resolve rules above; JSON out: `resolved`, `needs_clarification` or `gap`, with corrections and what to ask; `--record-gap` files the gap |
| `gaps` | gaps and which are due for a search |
| `learn-status` | days in the log with no daily guide or session summary |
| `proposals` | pending proposals, and repeats of rejected ones |

Everything else (writing pages, judging relevance, the voice of the guides) stays with the agent and
the schema.

## Evidence and limits

In the implementations this was distilled from, rule-based extraction read every table and field value
correctly in a hand-graded sample, and model extraction of prose about 70%, which is why the model is
held to quoted values. The samples were small (50 claims, 30 retrieval questions) and written by the
builders. Treat the numbers as a reason to measure your own, not as a benchmark.

The quote check catches invented and altered numbers. It does not catch a true number attached to the
wrong subject, which is the main remaining error, and it does not judge whether a source is any good.

## Credits

Builds on Andrej Karpathy's LLM Wiki idea file (April 2026). Licence: MIT.
