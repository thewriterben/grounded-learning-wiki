#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""glw.py - checks for a Grounded Learning Wiki (an extension of the LLM Wiki pattern).

    glw.py check [--root DIR] [--strict]          raw/ lock, citations, quotes, numbers, one-way rules
    glw.py lock [--root DIR] [--accept-changes]    record raw/ file hashes in glw.lock
    glw.py resolve [--root DIR] [--record-gap] QUESTION
    glw.py gaps [--root DIR]                       gaps, and which are due for a search
    glw.py learn-status [--root DIR] [--strict]    log days with no daily guide or session page
    glw.py proposals [--root DIR]                  pending proposals, repeats of rejected ones

Standard library only, Python 3.11+. Exit status: 0 clean, 1 failures, 2 usage or config error.
Everything read from the wiki is data; this script never executes or fetches anything.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path

DEFAULTS = {
    "paths": {"raw": "raw", "wiki": "wiki", "learning": "wiki/learning",
              "gaps": "wiki/gaps", "proposals": "wiki/proposals", "lock": "glw.lock"},
    "verify": {"external_prefixes": ["doi:", "arxiv:", "isbn:", "https://", "http://"],
               "navigation_pages": ["index.md", "log.md"]},
    "resolve": {"synonyms": {}, "stopwords_extra": []},
    "seek": {"policy": "queue", "research_after_days": 7, "stale_after_days": 180},
}

STOPWORDS = set("""a an and are as at be by can could do does for from had has have how i if in into is it
its me my of on or our should so than that the their them then there these this those to was we were what
when where which who why will with would you your about tell difference between much many long mean means explain define""".split())

FOOTDEF = re.compile(r"^\[\^([^\]\s]+)\]:\s*(\S+)\s*(.*)$")
FOOTREF = re.compile(r"\[\^([^\]\s]+)\](?!:)")
QUOTE = re.compile(r"[\"“](.+?)[\"”]")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
MDLINK = re.compile(r"\]\(([^)\s]+)\)")
# A number: a sign (- + or U+2212), thousands separators, decimals, e-notation, and a unit glued on
# (40km, 0.92R, 7.1σ). Not the digits of a name: TRAPPIST-1 and Kepler-452b (letter-hyphen before),
# v2 (letter before). The wiki line and the quote go through the same pattern, so they are read alike.
NUMBER = re.compile(
    r"(?:(?<![\w.])(?P<sign>[-+−]))?(?<![\w.])(?<![A-Za-z]-)"
    r"(?P<int>\d{1,3}(?:,\d{3})+(?!\d)|\d+)(?P<frac>\.\d+)?"
    r"(?:[eE](?P<exp>[-+−]?\d+))?(?P<unit>[^\W\d_]*)(?!\w)")
MIN_QUOTE_WORDS = 3
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
TOKEN = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------- config and files

def load_config(root: Path) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    path = root / "glw.toml"
    if path.is_file():
        try:
            user = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            sys.exit(f"glw.toml: {exc}")
        for section, values in user.items():
            if isinstance(values, dict):
                cfg.setdefault(section, {}).update(values)
    return cfg


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def unquote(value: str) -> str:
    """Strip one pair of matching outer quotes only, so 'Read "a" as "b"' keeps its inner quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def frontmatter(text: str) -> tuple[dict, int]:
    """Minimal YAML subset: `key: value` and `key: [a, b]`. Returns (meta, first body line index)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta: dict = {}
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return meta, i + 1
        if ":" not in line or line[:1] in (" ", "\t", "#"):
            continue
        key, value = line.split(":", 1)
        value = value.split(" #", 1)[0].strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [unquote(v.strip()) for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = unquote(value)
    return {}, 0


def norm(text: str) -> str:
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return " ".join(text.split())


def md_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.md") if p.is_file()) if base.is_dir() else []


def inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


class Wiki:
    def __init__(self, root: Path):
        self.root = root
        self.cfg = load_config(root)
        p = self.cfg["paths"]
        self.raw, self.wiki = root / p["raw"], root / p["wiki"]
        self.learning, self.gaps, self.proposals = root / p["learning"], root / p["gaps"], root / p["proposals"]
        self.lock = root / p["lock"]
        if not self.wiki.is_dir():
            sys.exit(f"no wiki directory at {self.wiki}")
        self.pages = md_files(self.wiki)
        self.by_name: dict[str, list[Path]] = {}
        for page in self.pages:
            rel = page.relative_to(self.wiki).with_suffix("").as_posix().lower()
            for key in {page.stem.lower(), rel}:
                self.by_name.setdefault(key, []).append(page)

    def resolve_link(self, target: str) -> Path | None:
        hits = self.by_name.get(target.strip().lower().removesuffix(".md"))
        return hits[0] if hits else None

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def is_navigation(self, page: Path) -> bool:
        return page.parent == self.wiki and page.name in self.cfg["verify"]["navigation_pages"]

    def is_derived_area(self, page: Path) -> bool:
        return any(inside(page, d) for d in (self.learning, self.gaps, self.proposals))


# ---------------------------------------------------------------- check

def numbers_in(line: str, idents: frozenset[str] = frozenset()) -> list[str]:
    """Numbers on a line, normalised: '-' for either minus, no thousands separators, unit dropped.
    `idents` are identifiers from page names (1e, 452b): written without a hyphen they are not numbers."""
    line = FOOTREF.sub(" ", line)
    line = WIKILINK.sub(" ", line)
    line = MDLINK.sub("] ", line)
    line = re.sub(r"`[^`]*`", " ", line)
    line = DATE.sub(" ", line)
    line = re.sub(r"^\s*(?:#+|\d+\.|[-*+]|>)\s+", " ", line)
    out = []
    for m in NUMBER.finditer(line):
        if (m["int"] + (m["frac"] or "") + m["unit"]).lower() in idents:
            continue
        value = ("-" if m["sign"] in ("-", "−") else "") + m["int"].replace(",", "") + (m["frac"] or "")
        if m["exp"]:
            value += "e" + m["exp"].replace("−", "-").lstrip("+")
        out.append(value)
    return out


def number_in_quote(number: str, quote: str, idents: frozenset[str] = frozenset()) -> bool:
    return number in numbers_in(quote, idents)


# ---------------------------------------------------------------- raw/ lock

def raw_hashes(w: Wiki) -> dict[str, str]:
    """sha256 of every file under raw/, line endings normalised so a Windows checkout hashes the same."""
    out = {}
    if w.raw.is_dir():
        for path in sorted(w.raw.rglob("*")):
            if path.is_file() and path.resolve() != w.lock.resolve():
                out[w.rel(path)] = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return out


def read_lock(w: Wiki) -> dict[str, str] | None:
    if not w.lock.is_file():
        return None
    try:
        data = json.loads(read(w.lock))
    except json.JSONDecodeError as exc:
        sys.exit(f"{w.lock.name}: {exc}")
    if not isinstance(data, dict):
        sys.exit(f"{w.lock.name}: expected a JSON object of path -> sha256")
    return data


def cmd_lock(w: Wiki, accept: bool) -> int:
    old = read_lock(w) or {}
    current = raw_hashes(w)
    added = [p for p in current if p not in old]
    changed = [p for p in old if p in current and current[p] != old[p]]
    removed = [p for p in old if p not in current]
    for p in changed:
        print(f"CHANGED {p}")
    for p in removed:
        print(f"REMOVED {p}")
    if (changed or removed) and not accept:
        print("refused: raw/ is immutable. If you, the owner, made these edits on purpose, "
              "run again with --accept-changes.")
        return 1
    new = {p: old[p] for p in old if p in current}
    new.update({p: current[p] for p in added})
    if accept:
        new.update({p: current[p] for p in changed})
    w.lock.write_text(json.dumps(dict(sorted(new.items())), indent=2) + "\n", encoding="utf-8")
    for p in added:
        print(f"ADDED   {p}")
    print(f"{w.lock.name}: {len(new)} file(s), {len(added)} added, "
          f"{len(changed) if accept else 0} accepted, {len(removed) if accept else 0} dropped")
    return 0


def check_lock(w: Wiki, strict: bool, errors: list[str], warnings: list[str]) -> None:
    locked = read_lock(w)
    name = w.lock.name
    if locked is None:
        warnings.append(f"no {name}: edits to raw/ cannot be detected; run glw.py lock")
        return
    current = raw_hashes(w)
    for path, digest in locked.items():
        if path not in current:
            errors.append(f"{path}: in {name} but missing (sources are never removed)")
        elif current[path] != digest:
            errors.append(f"{path}: changed since it was locked (sources are immutable; "
                          "only the owner may accept this with glw.py lock --accept-changes)")
    for path in current:
        if path not in locked:
            (errors if strict else warnings).append(f"{path}: new source not in {name}; run glw.py lock")


def cmd_check(w: Wiki, strict: bool) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    prefixes = tuple(w.cfg["verify"]["external_prefixes"])
    raw_cache: dict[Path, str] = {}
    entities = load_entities(w)
    idents = frozenset(t for e in entities for n in e["names"] for t in n if has_digit(t))
    names_of = {e["page"]: e["names"] for e in entities}
    held_cache: dict[Path, set[str]] = {}

    def numbers_on(page: Path) -> set[str]:
        if page not in held_cache:
            text = read(page)
            _, s = frontmatter(text)
            held_cache[page] = {x for ln in text.split("\n")[s:] for x in numbers_in(ln, idents)}
        return held_cache[page]

    def names_in(quote: str, names: list[list[str]]) -> bool:
        have = set(tokens(quote))
        return any(set(n) <= have for n in names)

    check_lock(w, strict, errors, warnings)

    for page in w.pages:
        text = read(page)
        _, start = frontmatter(text)
        lines = text.split("\n")
        rel = w.rel(page)
        in_learning = inside(page, w.learning)
        nav = w.is_navigation(page)
        own_names = names_of.get(rel, [])

        # footnote definitions: id -> {quote, kind (raw | external | wiki | bad), path}
        defs: dict[str, dict] = {}
        for n, line in enumerate(lines[start:], start + 1):
            m = FOOTDEF.match(line)
            if not m:
                continue
            fid, target, rest = m.groups()
            qm = QUOTE.search(rest)
            quote = norm(qm.group(1)) if qm else None
            where = f"{rel}:{n}"
            if quote is not None and len(quote.split()) < MIN_QUOTE_WORDS:
                errors.append(f"{where}: [^{fid}] quote is too short to tie a value to its subject "
                              f"(at least {MIN_QUOTE_WORDS} words)")
            path = None
            if target.startswith(prefixes):
                kind = "external"
                warnings.append(f"{where}: external citation [^{fid}] cannot be checked locally")
            else:
                path = (w.root / target.split("#", 1)[0]).resolve()
                if inside(path, w.raw):
                    kind = "raw"
                    if not path.is_file():
                        errors.append(f"{where}: [^{fid}] cites {target}, which does not exist")
                    elif quote is None:
                        errors.append(f"{where}: [^{fid}] cites {target} without a quote")
                    else:
                        if path not in raw_cache:
                            raw_cache[path] = norm(read(path))
                        if quote not in raw_cache[path]:
                            errors.append(f"{where}: [^{fid}] quote is not in {target} word for word")
                elif inside(path, w.wiki):
                    kind = "wiki"
                    if not in_learning:
                        errors.append(f"{where}: [^{fid}] cites a wiki page ({target}); "
                                      "wiki pages cite raw sources only (one-way rule 1)")
                    elif not path.is_file():
                        errors.append(f"{where}: [^{fid}] cites {target}, which does not exist")
                else:
                    kind = "bad"
                    errors.append(f"{where}: [^{fid}] cites {target}, which is neither under raw/ "
                                  "nor an accepted external form")
            defs[fid] = {"quote": quote, "kind": kind, "path": path}
            # A quote that names another page's subject and not this page's: the value may be the
            # neighbour's (TRAPPIST-1f's radius on the TRAPPIST-1e page).
            if quote and own_names and kind in ("raw", "external") and not names_in(quote, own_names):
                others = [e["title"] for e in entities if e["page"] != rel and names_in(quote, e["names"])]
                if others:
                    warnings.append(f"{where}: [^{fid}] quote names {', '.join(others)} but not this "
                                    "page's subject; check the value belongs here")

        used: set[str] = set()
        for n, line in enumerate(lines[start:], start + 1):
            where = f"{rel}:{n}"
            if FOOTDEF.match(line):
                continue
            refs = FOOTREF.findall(line)
            used.update(refs)
            for fid in refs:
                if fid not in defs:
                    errors.append(f"{where}: [^{fid}] has no definition")

            # one-way rule 2: nothing outside learning/ links into it
            if not in_learning and not nav:
                for target in WIKILINK.findall(line):
                    hit = w.resolve_link(target)
                    if hit and inside(hit, w.learning):
                        errors.append(f"{where}: links to learning page [[{target}]] "
                                      "(learning pages are never sources, one-way rule 2)")
                for target in MDLINK.findall(line):
                    if not target.startswith(prefixes):
                        hit = (page.parent / target.split("#", 1)[0]).resolve()
                        if inside(hit, w.learning):
                            errors.append(f"{where}: links to learning page {target} (one-way rule 2)")
            for target in WIKILINK.findall(line):
                if w.resolve_link(target) is None:
                    warnings.append(f"{where}: dangling link [[{target}]]")

            # numbers
            if nav or line.lstrip().startswith("#"):
                continue
            nums = numbers_in(line, idents)
            if not nums:
                continue
            cited = [defs[f] for f in refs if f in defs]
            quotes = [d["quote"] for d in cited if d["kind"] in ("raw", "external") and d["quote"]]
            if quotes:
                for num in nums:
                    if not any(number_in_quote(num, q, idents) for q in quotes):
                        errors.append(f"{where}: {num} is not in any quote this line cites "
                                      "(the model never produces a number)")
            elif in_learning:
                # A learning page re-explains: each number must be on a wiki page the line points to.
                targets = [hit for t in WIKILINK.findall(line)
                           if (hit := w.resolve_link(t)) and not inside(hit, w.learning)]
                targets += [d["path"] for d in cited if d["kind"] == "wiki" and d["path"].is_file()
                            and not inside(d["path"], w.learning)]
                if targets:
                    held = set().union(*(numbers_on(t) for t in targets))
                    for num in nums:
                        if num not in held:
                            errors.append(f"{where}: {num} is not on the page this line links "
                                          f"({', '.join(sorted({t.stem for t in targets}))})")
                else:
                    (errors if strict else warnings).append(
                        f"{where}: number(s) {', '.join(nums)} with no link to the wiki page that holds them")
            elif refs:
                if any(d["kind"] == "external" for d in cited):
                    warnings.append(f"{where}: number(s) {', '.join(nums)} rest on an external citation "
                                    "with no quote")
                # citations of wiki pages or bad targets are already errors above
            elif not w.is_derived_area(page):
                (errors if strict else warnings).append(f"{where}: uncited number(s) {', '.join(nums)}")

        for fid in defs:
            if fid not in used:
                warnings.append(f"{rel}: footnote [^{fid}] is defined but never used")

    for msg in warnings:
        print(f"WARN  {msg}")
    for msg in errors:
        print(f"ERROR {msg}")
    print(f"checked {len(w.pages)} pages: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


# ---------------------------------------------------------------- resolve

def osa(a: str, b: str, cap: int) -> int:
    """Optimal string alignment distance (adjacent swap = 1 edit), early exit above cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def edit_budget(word: str) -> int:
    # Short words are left alone: at 4 letters, one edit turns ordinary words into each other (feed/fed).
    return 0 if len(word) < 5 else 1 if len(word) < 8 else 2


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def apply_synonyms(text: str, synonyms: dict) -> str:
    text = " " + " ".join(tokens(text)) + " "
    for src in sorted(synonyms, key=len, reverse=True):
        key = " " + " ".join(tokens(src)) + " "
        text = text.replace(key, " " + " ".join(tokens(synonyms[src])) + " ")
    return text.strip()


def has_digit(word: str) -> bool:
    return any(c.isdigit() for c in word)


def digit_neighbours(word: str, vocab: Counter) -> list[str]:
    """Identifiers that differ in one part: same letters, other digits (t60 -> t55, t65), or same
    digits, other letters (1g -> 1e, 1f)."""
    def shape(w: str) -> str:
        return re.sub(r"[a-z]", "a", re.sub(r"\d", "0", w))

    letters, digits = re.sub(r"\d", "", word), re.sub(r"\D", "", word)
    out = []
    for v in vocab:
        if v == word or not has_digit(v) or abs(len(v) - len(word)) > 1:
            continue
        v_letters, v_digits = re.sub(r"\d", "", v), re.sub(r"\D", "", v)
        if v_letters == letters or (v_digits == digits and letters and shape(v) == shape(word)):
            out.append(v)
    return sorted(out)


def load_entities(w: Wiki) -> list[dict]:
    entities = []
    for page in w.pages:
        if w.is_navigation(page) or w.is_derived_area(page):
            continue
        meta, _ = frontmatter(read(page))
        title = meta.get("title") or page.stem.replace("-", " ")
        aliases = meta.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        names = []
        for name in [title, *aliases]:
            words = [t for t in tokens(name) if t not in STOPWORDS]
            if words:
                names.append(words)
        versions = meta.get("versions") or []
        if isinstance(versions, str):
            versions = [versions]
        entities.append({"page": w.rel(page), "title": title, "names": names,
                         "versioned": str(meta.get("versioned", "")).lower() == "true",
                         "versions": [" ".join(tokens(v)) for v in versions if tokens(v)]})
    return entities


def cmd_resolve(w: Wiki, question: str, record_gap: bool) -> int:
    rcfg = w.cfg["resolve"]
    stop = STOPWORDS | {s.lower() for s in rcfg.get("stopwords_extra", [])}
    vocab: Counter = Counter()
    for path in md_files(w.raw) + [p for p in w.pages if not (w.is_derived_area(p) or w.is_navigation(p))]:
        vocab.update(tokens(read(path)))
    entities = load_entities(w)
    for e in entities:
        for name in e["names"]:
            vocab.update(name)

    text = apply_synonyms(question, rcfg.get("synonyms", {}))
    words = [t for t in text.split() if t not in stop]
    result: dict = {"question": question, "corrections": [], "ask": [], "unknown_terms": [],
                    "entity": None, "offered": []}
    fixed: list[str] = []
    for word in words:
        if word in vocab:
            fixed.append(word)
            continue
        if has_digit(word):
            near = digit_neighbours(word, vocab)
            result["unknown_terms"].append(word)
            if near:
                result["ask"].append(f"'{word}' is not in the wiki. Did you mean {' or '.join(near)}?")
            fixed.append(word)
            continue
        budget = edit_budget(word)
        best: list[tuple[int, str]] = []
        if budget:
            for cand in vocab:
                if has_digit(cand):
                    continue
                d = osa(word, cand, budget)
                if d <= budget:
                    best.append((d, cand))
        if best:
            dmin = min(d for d, _ in best)
            top = sorted((c for d, c in best if d == dmin), key=lambda c: -vocab[c])
            if len(top) == 1 or vocab[top[0]] >= 3 * vocab[top[1]]:
                result["corrections"].append({"from": word, "to": top[0]})
                fixed.append(top[0])
            else:
                result["ask"].append(f"'{word}' could be {' or '.join(top[:3])}. Which did you mean?")
                result["unknown_terms"].append(word)
                fixed.append(word)
        else:
            result["unknown_terms"].append(word)
            fixed.append(word)

    have = set(fixed)
    padded = " " + " ".join(fixed) + " "
    full, partial = [], []
    for e in entities:
        matched = [frozenset(n) for n in e["names"] if set(n) <= have]
        if matched:
            full.append((max(matched, key=len), e))
        elif any(set(n) & have for n in e["names"]):
            partial.append(e)
    # A match whose words are all inside a larger match is dropped ("loaf" inside "house loaf").
    # Matches on the same words are a real ambiguity; matches on different words are a question
    # about several subjects ("T55 or T65 flour") and all of them are returned.
    full = [(m, e) for m, e in full if not any(m < other for other, _ in full)]
    groups: dict[frozenset, list[dict]] = {}
    for m, e in full:
        groups.setdefault(m, []).append(e)
    chosen: list[dict] = []
    for same in groups.values():
        if len(same) > 1:
            result["ask"].append("Which do you mean: " + ", ".join(e["title"] for e in same) + "?")
        else:
            chosen.append(same[0])
    result["entities"] = [e["page"] for e in chosen]
    if len(chosen) == 1:
        result["entity"] = chosen[0]["page"]
    for e in chosen:
        if not e["versioned"]:
            continue
        if e["versions"]:
            named = any(f" {v} " in padded for v in e["versions"])
            options = " or ".join(e["versions"])
        else:  # no list given: any identifier with a digit outside the subject's own name counts
            named = any(has_digit(t) for t in have - set(sum(e["names"], [])))
            options = "which one"
        if not named:
            result["ask"].append(f"The answer for '{e['title']}' depends on its version: {options}?")
    # No page is named in full: never answer from a neighbour. Offer the pages that share a word,
    # or call it a gap.
    if not full and partial:
        result["offered"] = [e["title"] for e in partial]
        if not result["ask"]:
            result["ask"].append("That is not in the wiki as asked. Closest: "
                                 + ", ".join(result["offered"]) + ".")

    if result["ask"]:
        result["status"] = "needs_clarification"
    elif not chosen:
        result["status"] = "gap"
        if not result["unknown_terms"]:
            result["reason"] = "no page is about this"
    else:
        # Unknown words next to a known subject are reported, not treated as a gap: whether the
        # subject's page holds the asked fact is for the agent to read (and file as a gap if not).
        result["status"] = "resolved"

    if result["status"] == "gap" and record_gap:
        result["gap_page"] = write_gap(w, question, fixed)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def write_gap(w: Wiki, question: str, words: list[str]) -> str:
    slug = "-".join(sorted(set(words)))[:60].strip("-") or "gap"
    path = w.gaps / f"{slug}.md"
    if not path.exists():
        w.gaps.mkdir(parents=True, exist_ok=True)
        today = dt.date.today().isoformat()
        path.write_text(
            "---\n"
            f"title: {question.strip().rstrip('?')}\n"
            "status: open\n"
            f"question: {question.strip()}\n"
            f"asked: {today}\n"
            "last_searched:\n"
            f"policy: {w.cfg['seek']['policy']}\n"
            "---\n\n## Candidates\n\n- (none yet)\n", encoding="utf-8")
    return w.rel(path)


# ---------------------------------------------------------------- gaps, learn-status, proposals

def parse_date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def cmd_gaps(w: Wiki) -> int:
    after = int(w.cfg["seek"]["research_after_days"])
    today = dt.date.today()
    rows = md_files(w.gaps)
    print(f"seek policy: {w.cfg['seek']['policy']}; re-search after {after} days")
    for path in rows:
        meta, _ = frontmatter(read(path))
        status = meta.get("status", "open")
        last = parse_date(meta.get("last_searched", ""))
        due = status in ("open", "candidates") and (last is None or (today - last).days >= after)
        print(f"{'DUE ' if due else '    '}{status:<10} {w.rel(path)}  {meta.get('title', '')}")
    print(f"{len(rows)} gap(s)")
    return 0


def cmd_learn_status(w: Wiki, strict: bool) -> int:
    log = w.wiki / "log.md"
    if not log.is_file():
        print("no wiki/log.md")
        return 0
    days = sorted(set(re.findall(r"^## \[(\d{4}-\d{2}-\d{2})\]", read(log), re.M)))
    covered: set[str] = set()
    for path in md_files(w.learning / "daily") + md_files(w.learning / "sessions"):
        meta, _ = frontmatter(read(path))
        covered.update(DATE.findall(path.stem))
        for key in ("covers", "covers_log"):
            value = meta.get(key, [])
            covered.update(DATE.findall(" ".join(value) if isinstance(value, list) else str(value)))
    missing = [d for d in days if d not in covered]
    for d in missing:
        print(f"MISSING learning page for {d}")
    print(f"{len(days)} logged day(s), {len(missing)} without a daily guide or session summary")
    return 1 if strict and missing else 0


def cmd_proposals(w: Wiki) -> int:
    rows = []
    for path in md_files(w.proposals):
        meta, _ = frontmatter(read(path))
        rows.append((path, meta.get("status", "proposed"), meta.get("key", ""), meta.get("title", "")))
    rejected = {k for _, s, k, _ in rows if s == "rejected" and k}
    pending = 0
    for path, status, key, title in rows:
        if status != "proposed":
            continue
        pending += 1
        flag = "REPEAT" if key in rejected else "      "
        print(f"{flag} {w.rel(path)}  {key}  {title}")
    print(f"{pending} pending, {len(rejected)} rejected key(s) on file")
    return 1 if any(s == "proposed" and k in rejected for _, s, k, _ in rows) else 0


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    # Questions and quotes carry non-ASCII (U+2212, typographic quotes, non-breaking hyphens);
    # a cp1252 Windows console would otherwise crash on print.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="glw.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "resolve", "gaps", "learn-status", "proposals", "lock"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", default=".", help="wiki root (holds glw.toml, raw/, wiki/)")
        if name in ("check", "learn-status"):
            sp.add_argument("--strict", action="store_true")
        if name == "resolve":
            sp.add_argument("--record-gap", action="store_true")
            sp.add_argument("question", nargs="+")
        if name == "lock":
            sp.add_argument("--accept-changes", action="store_true",
                            help="record changed or removed raw/ files (the owner's call, never the agent's)")
    args = ap.parse_args(argv)
    w = Wiki(Path(args.root))
    if args.cmd == "lock":
        return cmd_lock(w, args.accept_changes)
    if args.cmd == "check":
        return cmd_check(w, args.strict)
    if args.cmd == "resolve":
        return cmd_resolve(w, " ".join(args.question), args.record_gap)
    if args.cmd == "gaps":
        return cmd_gaps(w)
    if args.cmd == "learn-status":
        return cmd_learn_status(w, args.strict)
    return cmd_proposals(w)


if __name__ == "__main__":
    sys.exit(main())
