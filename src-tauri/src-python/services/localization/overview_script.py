"""Overview narration with timing cues, sized to the overview video.

The overview is a route animation: the intro, then the route reaching waypoint
1, 2, 3, ... and a wrap-up. Narration that only covers the first part leaves
the rest of the video silent. This builds a complete script where every
waypoint (or nearby group of waypoints) gets a passage sized to the seconds
the route spends there, tagged with {n} cues (see subtitle.strip_cues and
spatial_renderer/overview.py) so the video and the voice land together.

The LLM (Ollama/Gemma by default) only writes the short per-place passages;
the timeline, budgets, tags and validation are plain code, so a weak or
failing model degrades to a fact-based sentence instead of breaking timing.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from services.logger.logger import setup_logger

logger = setup_logger("OverviewScript")

# Spoken Japanese speed of the project's TTS, in characters per second.
# Re-measured per cue segment on a real rendered overview (22 segments, cue
# to cue): ~5.26 at 1x speed - the prior 4.2 badly underestimated it, so
# every way/describe line was written short of its own seconds-budget and
# then read even faster than that undersized text implied, which is what
# left the walk chasing the voice on tight legs. A little under the
# measurement on purpose - a passage that runs short is covered by the
# route/hold, one that runs long pushes the next cue late.
DEFAULT_CHARS_PER_SECOND = 5.0
# A passage needs at least this many seconds of route to be worth speaking
# (about 33 characters): arrivals that follow so quickly that the passage
# would be shorter are folded into it — those places are described together
# and only the first gets a tag pinned.
MIN_PASSAGE_SECONDS = 6.0
# A passage starts a little before the route arrives, so the name is heard
# as the card comes up rather than after it.
LEAD_SECONDS = 0.5
_MIN_PASSAGE_CHARS = 14
# The last numbered stop's passage never runs longer than this: what follows
# it on the route (the trip back) gets its own passage instead of one place
# being talked about for the whole return leg.
MAX_LAST_STOP_SECONDS = 8.0
# Spoken between {start} and the first {n}: the route sets off and the first
# stop is a few seconds away. Without it {start} and {1} would sit on the same
# instant and waypoint 1 could not be reached when its line is spoken.
SET_OFF_TEXT = "さあ、町へ出発しましょう。"
MIN_SET_OFF_SECONDS = 2.5

# Whether the overview describes each stop. On (tuning.DEFAULT_OVERVIEW_DESCRIBE_STOPS):
# every numbered stop gets its own short description pulled from its
# attractionNarration/arrivingNarration (see _facts), not just a name where
# its pin appears - a stop is otherwise a silent pause between "heading to
# X" and "leaving X", with nothing said about X itself at the map-overview
# level (its OWN narration, played later by its leg/attraction clip, is a
# separate pass over the same place). settings.overview_describe_stops
# overrides per project.


def describes_stops(project: dict) -> bool:
    from services import tuning

    return bool(project.get("settings", {}).get(
        "overview_describe_stops", tuning.DEFAULT_OVERVIEW_DESCRIBE_STOPS
    ))


Generate = Callable[[str, int], Optional[str]]  # (prompt, max_chars) -> text


def visible_waypoints(project: dict) -> List[dict]:
    """The waypoints that get a numbered pin, in route order: everything but
    the start pin (index 0), stop-bys, waypoints skipped in video export
    (drawn as a stop-by dot), and the final destination pin. Their position
    + 1 is the {n} an overview cue uses."""
    waypoints = project.get("waypoints", [])
    return [
        w for i, w in enumerate(waypoints)
        if i != 0 and i != len(waypoints) - 1
        and not w.get("isStopBy") and not w.get("skipAssetGeneration")
    ]


def _facts(waypoint: dict) -> str:
    """What is known about a place, from the project's own narration."""
    parts = [(waypoint.get("attractionNarration") or "").strip(),
             (waypoint.get("arrivingNarration") or "").strip()]
    text = re.sub(r"\{[^}]*\}", "", " ".join(p for p in parts if p))
    return text.strip()


_SENTENCE_END = re.compile(r"(?<=[。！？\n])")


def _fit_sentences(text: str, limit: int) -> str:
    """The leading whole sentences of `text` that fit in about `limit`
    characters ("" if even the first is far too long). Small models ignore a
    length limit but usually write fine sentences, so cut at a sentence end
    rather than throwing the whole answer away or chopping mid-sentence."""
    out = ""
    for sentence in (s.strip() for s in _SENTENCE_END.split(text or "")):
        if not sentence:
            continue
        if out and len(out) + len(sentence) > limit * 1.15:
            break
        if not out and len(sentence) > limit * 1.4:
            return ""
        out += sentence
    return out


# Rotated instead of a single fixed phrase, so a run with several stops
# whose own facts didn't pan out (_looks_ok rejected them) doesn't say
# "到着しました" at every one of them - picked by waypoint number, so the
# same stop always falls back to the same phrasing across reruns.
_ARRIVAL_FALLBACK_PHRASES = [
    "{label}に着きました。",
    "ここが{label}です。",
    "{label}へやってきました。",
    "続いて{label}です。",
]

# Used instead of the phrases above when the WAY line right before this stop
# already named it (check_transition requires that) - none of these restate
# the name, so the stop doesn't open with the same place named twice in a row.
_HERE_FALLBACK_PHRASES = [
    "ここでゆっくり眺めていきましょう。",
    "少し立ち止まって、周りを見渡してみましょう。",
    "ここからの眺めも、旅の思い出のひとつです。",
    "しばらく、この場所の空気を感じてみてください。",
]


def _arrival_fallback(label: str, n: int, already_named: bool = False) -> str:
    phrases = _HERE_FALLBACK_PHRASES if already_named else _ARRIVAL_FALLBACK_PHRASES
    return phrases[n % len(phrases)].format(label=label)


def _template(labels: List[str], kind: str = "") -> str:
    """Last-resort passage built from place names only: always short, always
    correct, never cut mid-word."""
    labels = [l for l in labels if l]
    if kind == "return":
        return "旅の締めくくりに、出発地へと戻っていきます。"
    if not labels:
        return "次の場所へと進みます。"
    if len(labels) == 1:
        return f"{labels[0]}に到着します。"
    if len(labels) > 3:
        return f"{labels[0]}から{labels[-1]}まで、順に巡っていきます。"
    return "、".join(labels) + "を巡ります。"


def _looks_ok(text: str, limit: int, min_chars: int = _MIN_PASSAGE_CHARS, over: float = 1.5) -> bool:
    if not text or len(text) < min(min_chars, limit) or len(text) > limit * over:
        return False
    if re.search(r"[A-Za-z]{4,}|[#*_`{}<>\[\]]", text):  # markdown, tags, English chatter
        return False
    return bool(re.search(r"[぀-ヿ一-鿿]", text))


def plan_passages(
    project: dict, arrivals: Dict[int, float], route_end: float, intro_end: float,
    chars_per_second: float = DEFAULT_CHARS_PER_SECOND,
) -> List[dict]:
    """Splits the route timeline into passages. Each is
    {"numbers": [n, ...], "labels": [...], "facts": str, "chars": budget,
     "start": seconds}. The passage for a group starts at its first arrival
    (minus LEAD_SECONDS) and lasts until the next group's start (or the
    route's end)."""
    places = visible_waypoints(project)
    numbered = [(i + 1, places[i]) for i in range(len(places)) if (i + 1) in arrivals]
    groups: List[List[Tuple[int, dict]]] = []
    for n, w in numbered:
        if groups:
            group_start = arrivals[groups[-1][0][0]] - LEAD_SECONDS
            if (arrivals[n] - LEAD_SECONDS) - group_start < MIN_PASSAGE_SECONDS:
                groups[-1].append((n, w))
                continue
        groups.append([(n, w)])
    passages = []
    return_start = None
    for gi, group in enumerate(groups):
        start = max(intro_end, arrivals[group[0][0]] - LEAD_SECONDS)
        if gi + 1 < len(groups):
            end = arrivals[groups[gi + 1][0][0]] - LEAD_SECONDS
        else:
            end = min(route_end, start + MAX_LAST_STOP_SECONDS)
            return_start = end
        passages.append({
            "numbers": [n for n, _ in group],
            "labels": [w.get("label") or w.get("name") or "" for _, w in group],
            "facts": " ".join(_facts(w) for _, w in group),
            "facts_each": [_facts(w) for _, w in group],
            "start": start,
            "chars": max(_MIN_PASSAGE_CHARS, int((end - start) * chars_per_second)),
        })
    # The trip back: whatever the route still has to do after the last
    # numbered stop (stop-bys, the ferry, the walk to the finish). Told from
    # the final destination's own narration; no cue number (nothing to pin).
    waypoints = project.get("waypoints", [])
    if return_start is not None and route_end - return_start >= 4.0 and waypoints:
        final = waypoints[-1]
        passages.append({
            "numbers": [],
            "labels": [final.get("label") or final.get("name") or "出発地"],
            "facts": _facts(final),
            "start": return_start,
            "chars": max(_MIN_PASSAGE_CHARS, int((route_end - return_start) * chars_per_second)),
            "kind": "return",
        })
    return passages


def _prompt(passage: dict, previous: str) -> str:
    places = "、".join(passage["labels"])
    scene = (
        "巡り終えて、出発地へ戻っていく旅の締めくくりの場面のナレーションを書きます。"
        if passage.get("kind") == "return"
        else "地図上でルートが次の場所に到着する場面のナレーションを書きます。"
    )
    return (
        f"あなたは旅番組のナレーターです。{scene}\n"
        f"■ 場所: {places}\n■ 参考情報: {passage['facts'][:600]}\n"
        + (f"■ 直前のナレーション: {previous}\n" if previous else "")
        + f"■ 条件: 日本語の話し言葉。{passage['chars']}文字以内。参考情報にない事実は書かない。"
          "場所の名前を必ず含める。記号・括弧・番号・英語は使わず、本文のみを出力。"
    )


def build_script(
    project: dict,
    arrivals: Dict[int, float],
    route_end: float,
    intro_end: float,
    generate: Generate,
    intro_text: Optional[str] = None,
    closing_text: str = "今日の旅は、ここまでです。",
    chars_per_second: float = DEFAULT_CHARS_PER_SECOND,
) -> Tuple[str, List[dict]]:
    """Returns (script with cue tags, per-passage report). `generate(prompt,
    max_chars)` returns model text or None; anything it returns that fails
    validation is replaced by the place's own first sentence."""
    intro = (intro_text if intro_text is not None else project.get("overview_narration", ""))
    intro = re.sub(r"\{[^}]*\}", "", intro or "").strip()
    passages = plan_passages(project, arrivals, route_end, intro_end, chars_per_second)

    parts = [intro]
    report = []
    previous = ""
    # Time between the route setting off (intro_end) and the first numbered
    # arrival: long enough -> speak a short set-off line there, after {start}.
    first_arrival = min((n_t for n_t in arrivals.values()), default=None)
    set_off = bool(
        first_arrival is not None and passages
        and first_arrival - intro_end >= MIN_SET_OFF_SECONDS
    )
    for i, p in enumerate(passages):
        text = None
        try:
            text = generate(_prompt(p, previous), p["chars"])
        except Exception as exc:  # the model must never break timing
            logger.warning("Passage %s: generator failed (%s).", p["numbers"], exc)
        raw = text
        text = _fit_sentences(re.sub(r"[ \t\u3000]+", "", (text or "")).strip(), p["chars"])
        text = re.sub(r"\s+", "", text)
        used = "model"
        if not _looks_ok(text, p["chars"]):
            text = _template(p["labels"], p.get("kind", ""))
            used = "template"
        tags = "".join("{%d}" % n for n in p["numbers"][:1])  # only the first of a group is pinned
        # {start} sits right before the first passage: the route starts moving here.
        if i == 0:
            head = "{start}" + (SET_OFF_TEXT if set_off else "")
        else:
            head = ""
        parts.append(head + tags + text)
        report.append({**p, "text": text, "used": used, "spoken_chars": len(text), "raw": raw})
        previous = text
    parts.append(closing_text)
    return "".join(parts), report


# --- Tour-guide script: stop, describe, then tell the way ----------------------
#
# The walker stops at each numbered waypoint while the voice describes it ({n}
# to {go}, see localization/cues.py), then walks on while the voice tells the
# way to the next one - direction, time, mode, what it passes - from the route
# brief (localization/route_brief.py). The model only words the facts; every
# piece is checked and falls back to plain text built from the facts.

INTRO_CHARS = 90
DESCRIBE_CHARS = 80
TRANSITION_CHARS = 50

# The overview's length comes first; the script is sized to it. Default: 20s
# plus 7s per stop, kept within 60-120s (settings.overview_target_seconds
# overrides). The voice is then within AUDIO_MATCH_TOLERANCE_SECONDS of it.
TARGET_MIN_SECONDS = 60.0
TARGET_MAX_SECONDS = 120.0
TARGET_BASE_SECONDS = 20.0
TARGET_SECONDS_PER_STOP = 7.0
# Shares of the target: the intro plays over the intro card; a way line is
# never shorter than its minimum (the walker cannot outrun it by more than
# overview_timing.MAX_WALK_SPEEDUP) nor longer than its maximum (a leg is at
# most overview_max_leg_seconds on screen); the stops share what is left.
INTRO_SECONDS = 6.0
WAY_MIN_SECONDS = 3.5
WAY_MAX_SECONDS = 8.0
WAY_SHARE = 0.35
DESCRIBE_MIN_SECONDS = 3.5
DESCRIBE_MAX_SECONDS = 15.0
# Passing a stop takes the walker at least this long (the renderer never walks
# a leg faster, tuning.OVERVIEW_MIN_LEG_SECONDS), so a way line past several
# stops is at least this long per leg.
WAY_SECONDS_PER_LEG = 2.0
# A highlight's description: one short sentence/clause, not two or three -
# every numbered stop needs a share of the 60-90s target (see plan_budget),
# so a long per-stop description was crowding several stops out of the
# budget entirely (unable to fit their own {n} cue's trip+description
# within target at all - see plan's greedy stops.add loop). Short keeps
# every stop affordable; DESCRIBE_MAX_SECONDS still lets a stop with real
# spare time left over say more.
DESCRIBE_TARGET_SECONDS = 4.0
_MIN_WAY_CHARS = 6

# A sentence claiming a time or distance: the way lines tell those (from the
# route itself), so a description keeps out of it.
_ROUTE_CLAIM = re.compile(r"[0-9０-９]+\s*(分|時間|km|キロ|メートル|ｍ|m(?![a-z]))|歩くこと|歩いて")
# A description talks about the place the walker is standing at, not about
# heading there ("さあ、次は…へ", "今回の目的地は…").
_MOVING_ON = re.compile(r"次は|次に|今回の目的地|へと?向か|を目指|へと?進|に向けて")
_DIRECTION_WORD = re.compile(r"(北東|北西|南東|南西|北|南|東|西)(?=へ|の方|に向|に進)")
_NUMBER = re.compile(r"[0-9０-９]+(?:\.[0-9]+)?")


def _fill_sentences(text: str, limit: int) -> str:
    """The leading whole sentences of `text` that come closest to `limit`
    characters: a description built from facts should last its time (a stop
    that freezes for 9s wants ~9s of voice), not stop at the first sentence."""
    out = ""
    for sentence in (s.strip() for s in _SENTENCE_END.split(text or "")):
        if not sentence:
            continue
        if out and abs(len(out) + len(sentence) - limit) >= abs(len(out) - limit):
            break
        out += sentence
    return out


def _clean(text: Optional[str], limit: int) -> str:
    text = _fit_sentences(re.sub(r"[ \t　]+", "", (text or "")).strip(), limit)
    return re.sub(r"\s+", "", text)


def _names_in(text: str, label: str) -> bool:
    from services.localization.overview_cues import name_variants

    return any(v in text for v in name_variants(label))


# A bracket-quoted term right before a copula/arrival phrase ("『X』です。",
# "『X』に到着しました。", "『X』へやってきました。") - the project's own
# narration text consistently uses 『』 exactly to introduce THIS waypoint's
# name this way (every sample in this project does), so this matches the
# naming clause without needing the quoted text to literally equal `label` -
# the fact text often names the same place slightly differently than the
# waypoint's own label ("友ヶ島 小展望台" the label vs "『小展望台』" in its own
# narration, "阿字ヶ峰行者堂" vs "『阿字ヶ峰 役行者堂』") so a literal/substring
# match against label missed most of these.
_NAME_QUOTE_OPENING = re.compile(r"[『「][^』」]{1,20}[』」]\s*(です|でした|に(到着|着き|やって来)|へ(着き|やって来))")


def _drop_named_opening(text: str, label: str) -> str:
    """Drops a leading sentence that names `label` (e.g. "『X』です。",
    "神功皇后ゆかりの『X』です。", "『X』に到着しました。" - the name doesn't
    have to be the first word, "modifier + name + copula" is exactly as
    repetitive). Used on a stop's own fact-derived fallback when the way line
    right before it already named the place, so the description doesn't say
    the same name a second time right away. Only drops when a later sentence
    is left to say instead - a single-sentence fact stays as-is rather than
    leaving nothing."""
    from services.localization.overview_cues import name_variants

    sentences = [s for s in _SENTENCE_END.split(text or "") if s.strip()]
    if len(sentences) < 2:
        return text  # nothing left to say if the only sentence is dropped
    first = sentences[0].strip()
    if _NAME_QUOTE_OPENING.search(first):
        return "".join(sentences[1:])
    bare = re.sub(r"[『』「」]", "", first)
    for variant in sorted(name_variants(label), key=len, reverse=True):
        if variant in bare:
            return "".join(sentences[1:])
    return text


def check_transition(text: str, journey: dict, limit: int = TRANSITION_CHARS) -> bool:
    """Whether a model's way-telling line only says what the journey's facts
    say: the destination is named, a direction (if any) is the real one, every
    number is one of its times or distances, and a boat trip is mentioned."""
    if not _looks_ok(text, limit, _MIN_WAY_CHARS, 1.2) or not _names_in(text, journey["to"]):
        return False
    if any(word != journey["heading"] for word in _DIRECTION_WORD.findall(text)):
        return False
    names = [journey["from"], journey["to"], *journey.get("via", []), *journey.get("passes", [])]
    bare = text
    for name in sorted(names, key=len, reverse=True):
        bare = bare.replace(name, "")  # "13号線" in a name is not a claim
    minutes = [journey["minutes"], *(p["minutes"] for p in journey["pieces"])]
    allowed = set(minutes) | {m // 60 for m in minutes} | {m % 60 for m in minutes}
    allowed |= {round(journey["km"], 1)} | {round(p["km"], 1) for p in journey["pieces"]}
    for raw in _NUMBER.findall(bare):
        value = float(raw.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
        if not any(abs(value - a) <= max(1.0, 0.2 * a) for a in allowed):
            return False
    if any(p["mode"] == "ferry" for p in journey["pieces"]) and not re.search(r"船|フェリー|渡", text):
        return False
    return True


def _pieces_text(journey: dict) -> str:
    names = {"walking": "徒歩", "ferry": "船", "car": "車", "driving": "車", "airplane": "飛行機"}
    return "、".join(f"{names.get(p['mode'], p['mode'])}{p['minutes']}分" for p in journey["pieces"])


# A model's way0 (the transition right after the opening greeting) routinely
# re-greets/re-welcomes despite _transition_prompt's first=True instruction
# not to - this catches it so `ask()` falls back to the safe template text
# instead of shipping a script with the welcome line said twice in a row.
_GREETING = re.compile(r"こんにちは|ようこそ|はじめまして|皆さん|旅へ出|旅に出かけ")

# _transition_prompt / _describe_prompt both ask the model not to write this,
# but small local models routinely ignore a single negative instruction (see
# _GREETING above) - checked here too so a slip falls back to
# _arrival_fallback's rotation instead of shipping the phrase anyway.
_ARRIVED_PHRASE = re.compile(r"到着しました")


def _transition_prompt(journey: dict, previous: str, limit: int, first: bool = False) -> str:
    lines = [
        f"■ 出発: {journey['from']}",
        f"■ 到着: {journey['to']}" + ("（出発地へ戻る）" if journey["is_return"] else ""),
        f"■ 移動: {_pieces_text(journey)}",
        f"■ 方角: {journey['heading']}",
    ]
    if journey.get("via"):
        lines.append(f"■ 立ち寄る場所: {'、'.join(journey['via'])}")
    # Each via_batches name's own short fact (route_brief._short_fact, from
    # its attractionNarration), when it has one - given to the model too,
    # not just the template fallback (_transition_prompt's caller), so a
    # model-written line can also say what one of these actually IS instead
    # of just listing names it has no context for.
    via_facts = {n: f for _, names, facts in journey.get("via_batches", []) for n, f in zip(names, facts or [])}
    seen = list(journey.get("passes", [])) + [n for _, names, *_ in journey.get("via_batches", []) for n in names]
    if seen:
        described = "、".join(f"{n}（{via_facts[n]}）" if via_facts.get(n) else n for n in seen)
        lines.append(f"■ 途中に見える場所: {described}")
    if journey["winding"]:
        lines.append("■ 道: 曲がりくねった道")
    return (
        "あなたは旅番組のナレーターです。地図の上をルートが次の場所へ進む場面で、"
        "観光ガイドのように道順を案内するナレーションを書きます。\n"
        + "\n".join(lines) + "\n"
        + (f"■ 直前のナレーション: {previous}\n" if previous else "")
        + f"■ 条件: 日本語の話し言葉で1〜2文、{limit}文字以内。上の情報にない地名・数字・方角は書かない。"
          "到着地の名前を必ず含める。記号・括弧・番号・英語は使わず、本文のみを出力。"
          "「到着しました」は使わず、別の言い回しにする。"
        # This is the FIRST transition, right after the opening greeting
        # (■ 直前のナレーション above IS that greeting) — without this the
        # model routinely re-greets/re-welcomes here too, duplicating the
        # intro word-for-word right at the top of the script.
        + ("挨拶・歓迎の言葉（「こんにちは」「ようこそ」など）は直前のナレーションで済んでいるので、"
           "ここでは繰り返さず、道案内から始める。" if first else "")
    )


def _describe_prompt(label: str, facts: str, previous: str, limit: int) -> str:
    # The way line right before this (■ 直前のナレーション) is required to
    # already name the destination (check_transition) - if it did, telling
    # the model to ALSO name it here just produces "...XXXへ。XXXです。" back
    # to back, so the naming instruction only fires when it's actually needed.
    already_named = bool(previous) and _names_in(previous, label)
    name_rule = (
        "直前のナレーションですでに場所の名前を伝えているので、ここでは名前を繰り返さず"
        "「ここは」「この場所には」などで始めてよい。"
        if already_named else
        "場所の名前を必ず含める。"
    )
    return (
        "あなたは旅番組のナレーターです。旅人が場所に到着し、立ち止まってその場所を紹介する場面のナレーションを書きます。\n"
        f"■ 場所: {label}\n■ 参考情報: {facts[:600]}\n"
        + (f"■ 直前のナレーション: {previous}\n" if previous else "")
        + f"■ 条件: 日本語の話し言葉で2〜3文、{limit}文字以内。参考情報にない事実は書かない。"
          f"{name_rule}道順や移動の話はしない。記号・括弧・番号・英語は使わず、本文のみを出力。"
          "「到着しました」は使わず、別の言い回しで場所を紹介する。"
    )


def _intro_prompt(brief: dict, stops: List[str], limit: int) -> str:
    return (
        "あなたは旅番組のナレーターです。地図でこれから巡るルート全体を見せる、旅のオープニングのナレーションを書きます。\n"
        f"■ 出発地: {brief['start']}\n■ 巡る場所: {'、'.join(stops)}\n"
        f"■ 条件: 日本語の話し言葉で2文、{limit}文字以内。歓迎の挨拶から始める。"
        "上の情報にない地名・数字は書かない。記号・括弧・英語は使わず、本文のみを出力。"
    )


def in_overview_range(seconds: float, tolerance: float = 3.0) -> bool:
    """Whether an overview of `seconds` is within TARGET_MIN..TARGET_MAX_SECONDS
    (give or take the tolerance the video absorbs)."""
    return TARGET_MIN_SECONDS - tolerance <= seconds <= TARGET_MAX_SECONDS + tolerance


def overview_target_seconds(project: dict, stops: int) -> float:
    """How long the overview should be: settings.overview_target_seconds, else
    TARGET_BASE_SECONDS + TARGET_SECONDS_PER_STOP per numbered stop, kept
    within TARGET_MIN_SECONDS..TARGET_MAX_SECONDS."""
    chosen = project.get("settings", {}).get("overview_target_seconds")
    if chosen:
        return float(chosen)
    return min(TARGET_MAX_SECONDS, max(TARGET_MIN_SECONDS, TARGET_BASE_SECONDS + TARGET_SECONDS_PER_STOP * stops))


def closing_seconds(project: dict) -> float:
    """The shortest the overview's ending can be (overview_timing.fit_ending
    shrinks it to fit the voice, down to this): the closing line lasts at
    least this long, so the video can end with it."""
    from services import tuning
    from services.vdoprocessing.spatial_renderer.overview_timing import (
        MIN_END_PAUSE_SECONDS, MIN_SUMMARY_HOLD_SECONDS, ending_seconds,
    )

    settings = project.get("settings", {})
    waypoints = project.get("waypoints", [])
    freeze = lambda w: float((w or {}).get("freeze_seconds", 3.0))  # noqa: E731 - the renderer's default
    return ending_seconds(
        recap_hold=freeze(waypoints[-1] if waypoints else None),
        summary_fade=float(settings.get("summary_fade", 0.5)),
        summary_hold=MIN_SUMMARY_HOLD_SECONDS,
        highlight_hold=tuning.ENDING_HIGHLIGHT_PIP_HOLD_SECONDS,
        pause=MIN_END_PAUSE_SECONDS,
        highlight=bool(settings.get("enable_ending_highlight", True)),
    )


def _way_seconds(trip: dict) -> float:
    """A way line's natural length: longer for a longer trip, plus every
    second the map is frozen on the way (stop-by batches) - the voice keeps
    telling the way through them."""
    import math

    travel = min(WAY_MAX_SECONDS, WAY_MIN_SECONDS + math.sqrt(max(trip["km"], 0.0)))
    travel = max(travel, WAY_SECONDS_PER_LEG * trip.get("legs", 1))
    return travel + trip.get("via_hold", 0.0)


def plan_budget(project: dict, brief: dict) -> dict:
    """Which numbered stops the walker stops at, and seconds (then characters,
    at the TTS speed) for every piece, so the voice lasts the overview's target.

    Every numbered stop stops and is described (`overviewHighlight: false`
    opts a place out); a stop hosting a stop-by batch is described for
    exactly the freeze its batch needs (the map freezes there anyway), every
    other stop gets DESCRIBE_TARGET_SECONDS. Time left over (or short) within
    `target` lengthens (or, if still short of `target`, further lengthens)
    the descriptions, then the way lines - `target` no longer decides which
    stops are described, only how their shared time is spent.
    {"target", "cps", "intro", "closing", "stops", "trips", "ways",
    "describe": {n: s}, "estimated", "fits"}."""
    from services.localization.route_brief import journeys

    settings = project.get("settings", {})
    # DEFAULT_CHARS_PER_SECOND was measured at the TTS's natural pace; the
    # voice speaks faster by its speed setting (tuning.TTS_SPEED, or the
    # project's settings.tts.speed).
    from services import tuning

    speed = float((settings.get("tts") or {}).get("speed", tuning.TTS_SPEED))
    cps = float(settings.get("overview_chars_per_second", DEFAULT_CHARS_PER_SECOND * speed))
    places = {n: w for n, w in enumerate(visible_waypoints(project), start=1)}
    target = overview_target_seconds(project, len(places))
    closing = closing_seconds(project)
    describing = describes_stops(project)
    hosts = {l["to_number"]: l["hold_at_to"] for l in brief["legs"]
             if l["to_number"] is not None and l.get("hold_at_to")}
    forced = {n for n, w in places.items() if w.get("overviewHighlight") is True}
    banned = {n for n, w in places.items() if w.get("overviewHighlight") is False} - set(hosts)

    def plan(stops: set) -> Tuple[List[dict], List[float], Dict[int, float], float]:
        trips = journeys(brief, stops)
        ways = [_way_seconds(t) for t in trips]
        describe = {n: (hosts[n] if n in hosts else (DESCRIBE_TARGET_SECONDS if describing else 0.0)) for n in stops}
        return trips, ways, describe, INTRO_SECONDS + sum(ways) + sum(describe.values()) + closing

    # Every numbered stop gets described (an explicit overviewHighlight:false
    # still opts a place out) - previously only as many as fit within `target`
    # were picked, ranked by _highlight_score, and the rest were only ever
    # named in passing on the way; a route with more stops than the 60-120s
    # budget could fit simply never described most of them at all. `target`
    # still drives how spare time is spent below (longer descriptions/ways),
    # it just no longer decides WHICH stops are described.
    stops = (set(places) | set(hosts) | forced) - banned
    trips, ways, describe, estimated = plan(stops)

    # Time left over: longer descriptions (not a batch host's - its freeze is
    # fixed), then longer way lines.
    spare = target - estimated
    flexible = [n for n in stops if n not in hosts] if describing else []
    if spare > 0 and flexible:
        each = min(spare / len(flexible), DESCRIBE_MAX_SECONDS - DESCRIBE_TARGET_SECONDS)
        for n in flexible:
            describe[n] += each
        spare -= each * len(flexible)
    if spare > 0 and ways:
        room = [WAY_MAX_SECONDS + t.get("via_hold", 0.0) - w for t, w in zip(trips, ways)]
        total_room = sum(r for r in room if r > 0)
        if total_room > 0:
            use = min(spare, total_room)
            ways = [w + (use * r / total_room if r > 0 else 0.0) for w, r in zip(ways, room)]
            spare -= use
    if spare > 0:
        # Still short of 60-120s (few stops, little to say): the overview's
        # length is the rule, so the descriptions (else the way lines) take it.
        if flexible:
            for n in flexible:
                describe[n] += spare / len(flexible)
        elif ways:
            ways = [w + spare / len(ways) for w in ways]
        spare = 0.0 if (flexible or ways) else spare
    estimated = target - spare if spare >= 0 and estimated <= target else estimated
    return {
        "target": target,
        "cps": cps,
        "intro": INTRO_SECONDS,
        "closing": closing,
        "stops": sorted(stops),
        "trips": trips,
        "ways": ways,
        "describe": describe,
        "estimated": estimated,
        # the overview stays within 60-120s (the video then follows the
        # voice to within AUDIO_MATCH_TOLERANCE_SECONDS)
        "fits": in_overview_range(estimated),
    }


def _opener(text: str) -> str:
    """The short lead word a line starts with ("さあ", "次は", "続いて"), or ""
    when it starts straight away (a place name is not a lead word): two lines
    in a row with the same lead sound like a template, so the second is not taken."""
    lead = re.split(r"[、。！？]", text, maxsplit=1)[0]
    return lead if len(lead) <= 4 else ""


def build_tour_script(
    project: dict,
    routing_cache: Optional[dict],
    generate: Optional[Generate] = None,
    intro_text: Optional[str] = None,
    closing_text: str = "今日の旅は、ここまでです。",
) -> Tuple[str, List[dict]]:
    """(script with {start} / {n} / {go} / {end} tags, per-piece report).

    The intro plays over the waiting map; {start} sets the walker off while the
    way to the first stop is told; at each stop {n} the walker stops while it is
    described, and {go} sends it on while the way to the next is told; {end}
    comes after the way back, and the closing line plays over the ending. Every
    piece is sized by `plan_budget` so the voice lasts the overview's target
    length. Without `generate` (or when its text fails the checks) every piece
    is built from the facts."""
    from services.localization.route_brief import build_brief, journeys, transition_text

    brief = build_brief(project, routing_cache)
    budget = plan_budget(project, brief)
    trips = budget["trips"]
    cps = budget["cps"]
    chars = lambda seconds: max(1, int(round(seconds * cps)))  # noqa: E731
    places = {n: w for n, w in enumerate(visible_waypoints(project), start=1)}
    report: List[dict] = []

    def ask(kind: str, prompt: str, limit: int, ok, fallback: str) -> str:
        raw = None
        if generate is not None:
            try:
                raw = generate(prompt, limit)
            except Exception as exc:  # the model must never break the script
                logger.warning("Overview %s: generator failed (%s).", kind, exc)
        text = _clean(raw, limit)
        fresh = not report or not _opener(text) or _opener(text) != _opener(report[-1]["text"])
        used = "model" if raw is not None and fresh and ok(text) else "template"
        if used == "template":
            text = fallback
        report.append({"kind": kind, "text": text, "used": used, "raw": raw, "budget_chars": limit})
        return text

    stop_names = [t["to"] for t in trips if t["to_number"] is not None]
    place_count = len(places)  # every place on the route, stopped at or passed
    intro_chars = chars(budget["intro"])
    if intro_text is not None:
        intro = re.sub(r"\{[^}]*\}", "", intro_text).strip()
    else:
        fallback = f"ようこそ。{brief['start']}から、{place_count}か所を巡る旅に出かけましょう。"
        intro = ask("intro", _intro_prompt(brief, stop_names, intro_chars), intro_chars,
                    lambda t: _looks_ok(t, intro_chars, over=1.2), fallback)

    parts = [intro, "{start}"]
    previous = intro
    for i, trip in enumerate(trips):
        way_chars = chars(budget["ways"][i])
        told = transition_text(trip, way_chars)
        if i == 0 and told.startswith("次は"):
            told = "まずは" + told[len("次は"):]  # setting off: nothing came before
        # The map freezes on the way to show stop-by cards: tell what they are
        # while they are up, so the voice does not run ahead of the walker.
        for host, names, facts in trip.get("via_batches", []):
            # Every stop-by in the group named, never truncated to the
            # first 3: a waypoint dropped here was never named ANYWHERE in
            # the script (it has no {n} cue of its own - this mention is
            # its only chance). Same reasoning as route_brief.transition_
            # texts's via/passes uncapping.
            #
            # Each one gets ITS OWN short fact folded in as "{fact}の{name}"
            # when it wrote one (route_brief._short_fact is built exactly for
            # this - see its own docstring), not just the first with the rest
            # reduced to bare names - a bare list is easy to tune out, and a
            # stop-by that wrote real content deserves the same "here's what
            # this actually is" treatment as any other, not just whichever
            # happened to come first in the batch.
            phrases = [
                f"{fact}の{name}" if fact else name
                for name, fact in zip(names, facts or [""] * len(names))
            ]
            line = f"{host}のあたりでは、{'や'.join(phrases)}が見えてきます。"
            # The map holds on this batch's cards until this line is spoken
            # (see cues.py's {goPreN}) - every via_batches host, not just
            # the one before stop 1.
            if trip.get("to_number") is not None:
                line += "{goPre%d}" % trip["to_number"]
            # Always inserted, even past the way segment's own character
            # budget (unlike before) - a name silently dropped for staying
            # under budget defeats guaranteeing every waypoint gets named;
            # plan_budget's overall target absorbs the odd longer line via
            # its own spare-time redistribution (see plan_budget's "spare"
            # handling) rather than this dropping content outright.
            head, dot, rest_told = told.partition("。")
            told = head + dot + line + rest_told if rest_told else told + line
        way = ask(
            f"way{i}", _transition_prompt(trip, previous, way_chars, first=(i == 0)), way_chars,
            lambda t, trip=trip, first=(i == 0), limit=way_chars: (
                check_transition(t, trip, limit)
                and not _ARRIVED_PHRASE.search(t)
                and not (first and t.startswith(("次は", "次に", "続いて")))
                # The intro (■ 直前のナレーション) already greeted the
                # listener — reject a way0 that greets again, rather than
                # ship a script that opens with the same "welcome" line
                # twice in a row (see _transition_prompt's first=True note).
                and not (first and _GREETING.search(t))
                # The model was GIVEN these stop-by names+facts (■ 途中に見
                # える場所, above) but is free-form otherwise, and routinely
                # drops some or all of them — require EVERY one to guarantee
                # the coverage promise ("every waypoint gets named") holds
                # regardless of whether the model's own text or the `told`
                # fallback (which the via_batches loop above always names
                # every one of them into) ends up used. Also every "via"
                # (a numbered waypoint skipped over, not its own stop) —
                # same guarantee, same reasoning.
                and all(
                    _names_in(t, n)
                    for _, names, *_ in trip.get("via_batches", []) for n in names
                )
                and all(_names_in(t, n) for n in trip.get("via", []))
            ),
            told,
        )
        parts.append(way)
        previous = way
        n = trip["to_number"]
        if n is None:
            continue
        label = trip["to"]
        if not describes_stops(project):
            # A stop that hosts stop-by cards freezes the map: say what is
            # around it (never the stop's own description or name again).
            names = trip.get("batch") or []
            text = f"{'や'.join(names[:3])}も、この近くにあります。" if names and budget["describe"].get(n) else ""
            report.append({"kind": f"stop{n}", "text": text, "used": "template", "raw": None,
                           "budget_chars": chars(budget["describe"].get(n, 0.0))})
            parts.append("{%d}%s{go}" % (n, text))
            previous = text or previous
            continue
        describe_chars = chars(budget["describe"][n])
        facts = _facts(places.get(n, {}))
        # The way line just before this (`previous`) is required to already
        # name `label` (check_transition) - when it did, the description
        # shouldn't open by naming it again (see _describe_prompt / _drop_
        # named_opening docstrings for the "...XXXへ。XXXです。" pattern this avoids).
        already_named = _names_in(previous, label)
        about = "".join(
            sentence for sentence in _SENTENCE_END.split(facts)
            if not _ROUTE_CLAIM.search(sentence) and not _MOVING_ON.search(sentence)
        ).strip()
        if already_named:
            about = _drop_named_opening(about, label)
        fallback = _fill_sentences(about, describe_chars) if about else ""
        if not _looks_ok(fallback, describe_chars, over=1.6):
            fallback = _arrival_fallback(label, n, already_named)
        describe = ask(
            f"stop{n}", _describe_prompt(label, facts, previous, describe_chars), describe_chars,
            lambda t, label=label, already_named=already_named: (
                _looks_ok(t, describe_chars, over=1.2) and (already_named or _names_in(t, label))
                and not _ROUTE_CLAIM.search(t) and not _MOVING_ON.search(t)
                and not _ARRIVED_PHRASE.search(t)
            ),
            fallback,
        )
        parts.append("{%d}%s{go}" % (n, describe))
        previous = describe

    # The closing line plays over the ending, so it lasts at least as long as
    # the ending can shrink to: the shortest of these that does (else the longest).
    closing_chars = chars(budget["closing"])
    km = round(brief["total_km"]) if brief["total_km"] >= 1 else brief["total_km"]
    endings = [
        closing_text,
        f"{place_count}か所を巡る、およそ{km}キロの旅でした。{{distance}}{closing_text}",
        f"{brief['start']}を出発し、{place_count}か所を巡る、およそ{km}キロの旅でした。{{distance}}{closing_text}",
    ]
    closing = next((e for e in endings if len(e) >= closing_chars), endings[-1])
    report.append({"kind": "closing", "text": closing, "used": "template", "raw": None,
                   "budget_chars": closing_chars})
    parts.append("{end}" + closing)
    return "".join(parts), report


def ollama_generate(model: str = "gemma2:2b") -> Generate:
    """A `generate` backed by a local Ollama model."""
    import ollama

    def _generate(prompt: str, max_chars: int) -> Optional[str]:
        response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
        return response["message"]["content"]

    return _generate
