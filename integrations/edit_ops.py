"""Editing commands shared by both assistants.

Turns one chat message into small, ordered operations so a single sentence can
carry several edits ("去掉第 2 段，然后只要后半段，最精彩的放最后"), and gives
both assistants the same segment numbering, time ranges, clip order, caption
overrides, "did you mean" hints and next-step suggestions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
NUM = r"(?:\d{1,2}|[一二两三四五六七八九十])"
SEG_LIST = rf"第\s*{NUM}\s*(?:段|个片段|个|条|片段|个镜头|镜头)?(?:\s*[、,，和与及跟]\s*(?:第\s*)?{NUM}\s*(?:段|个片段|个|条|片段|个镜头|镜头)?)*(?<=[段个条头])"

CLAUSE_SPLIT = re.compile(r"[；;。！!？?\n，,]+|(?:然后|并且|同时|顺便|另外|接着)")
UNDO = re.compile(r"^(?:撤销|撤回|回退|退回|还原|返回上一步|上一步|刚才那样|改回去|恢复刚才|不要这个改动|undo)")
RESET = re.compile(r"(恢复原样|全部恢复|清除限制|取消所有|重新来过|全部重置)")
PRONOUN = re.compile(r"(这一段|这段|那一段|那段|刚才那段|选中的那段|选中那段|它)")

REMOVE = re.compile(rf"(?:去掉|删掉|删除|剪掉|拿掉|不要|去除|删了|删|砍掉|扔掉)\s*(?P<segs>{SEG_LIST}|最后一段|第一段)|(?P<segs2>{SEG_LIST}|最后一段)\s*(?:不要了?|删掉|去掉|删了|砍掉)")
KEEP = re.compile(rf"(?:只要|只留|只保留|保留|留下)\s*(?P<segs>{SEG_LIST})")
CAPTION = re.compile(rf"(?P<seg>第\s*{NUM}\s*段|最后一段)的?\s*(?:字幕|标签|文字)\s*(?:改成|改为|换成|写成|写)\s*[“\"'「『]?(?P<text>[^”\"'」』，。,.!！?？\n]{{1,16}})")
ORDER = [
    (re.compile(r"(最精彩的?(?:放|留)(?:在)?最后|压轴|高潮放最后|越来越精彩|渐入高潮)"), "climax"),
    (re.compile(r"(最精彩的?(?:放|排)(?:在)?(?:最)?前面?|精彩的先放|开场就(?:放)?最精彩|按精彩程度排)"), "best_first"),
    (re.compile(r"(按时间顺序|时间顺序|按原片顺序|按顺序排)"), "time"),
]
RANGE_HALF = [
    (re.compile(r"(只要)?(后半段|后半场|下半场|后一半)"), "second"),
    (re.compile(r"(只要)?(前半段|前半场|上半场|前一半)"), "first"),
    (re.compile(r"(全场|整场|取消范围|不限范围|全部时间)"), "all"),
]
RANGE_LAST = re.compile(rf"最后\s*(?P<n>{NUM})\s*分钟")
RANGE_FIRST = re.compile(rf"(?:前|开头)\s*(?P<n>{NUM})\s*分钟")
RANGE_AFTER = re.compile(r"(?P<t>\d{1,2}[:：]\d{2}|\d{1,4}\s*秒)\s*(?:以后|之后|后面|往后|开始)")
RANGE_BEFORE = re.compile(r"(?P<t>\d{1,2}[:：]\d{2}|\d{1,4}\s*秒)\s*(?:以前|之前|前面|为止)")


def cn_int(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return int(value)
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + CN_NUM.get(value[1:], 0)
    if value.endswith("十"):
        return CN_NUM.get(value[:-1], 1) * 10
    return CN_NUM.get(value, 0)


def seg_numbers(text: str, plays: int) -> list[int]:
    if "最后一段" in text:
        return [plays] if plays else []
    if "第一段" in text and not re.search(r"\d", text):
        return [1]
    nums = [cn_int(x) for x in re.findall(NUM, text)]
    return sorted({n for n in nums if 1 <= n <= max(plays, 1)})


def _seconds(token: str) -> float:
    token = token.replace("：", ":").replace(" ", "")
    if ":" in token:
        m, s = token.split(":")
        return int(m) * 60 + int(s)
    return float(token.rstrip("秒"))


def resolve_pronoun(text: str, selected: int | None) -> str:
    """"去掉这段" → "去掉第 3 段" when the user tapped clip 3 on the page."""
    if selected and PRONOUN.search(text):
        return PRONOUN.sub(f"第{selected}段", text)
    return text


def split_clauses(text: str) -> list[str]:
    # "第1，3段" is one list, not two clauses; quoted titles keep their commas
    text = re.sub(rf"({NUM})\s*[，,]\s*(?=(?:第\s*)?{NUM}\s*(?:[、,，]|段))", r"\1、", text or "")
    protected: list[str] = []
    text = re.sub(r"[“\"「『][^”\"」』]*[”\"」』]", lambda m: protected.append(m.group(0)) or f"\x00{len(protected) - 1}\x00", text)
    parts = [re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], p).strip(" ，,、")
             for p in CLAUSE_SPLIT.split(text) if p and p.strip(" ，,、")]
    return parts or [text]


@dataclass
class Ops:
    """What one clause asks for beyond the classic single intent."""
    undo: bool = False
    reset: bool = False
    remove: list[int] = field(default_factory=list)
    keep: list[int] = field(default_factory=list)
    range: tuple[float | None, float | None] | None = None   # (start, end); (None, None) clears
    order: str | None = None
    captions: dict[int, str] = field(default_factory=dict)
    rest: str = ""                                          # text left for the classic parser

    @property
    def any(self) -> bool:
        return bool(self.undo or self.reset or self.remove or self.keep or self.range is not None or self.order or self.captions)


QUESTION = re.compile(r"(谁|吗|哪段|哪一段|多少|怎么样|如何|为什么|是不是|有没有|几个|几次|呢$)")


def parse_ops(clause: str, plays: int, duration: float) -> Ops:
    ops = Ops()
    text = clause.strip()
    if QUESTION.search(text) and not re.search(r"(去掉|删|保留|只要|改成|放最后|放前面|撤销)", text):
        ops.rest = text
        return ops
    if UNDO.search(text):
        ops.undo = True
        return ops
    if RESET.search(text):
        ops.reset = True
        text = RESET.sub("", text)
    for m in list(CAPTION.finditer(text)):
        n = seg_numbers(m.group("seg"), plays)
        if n:
            ops.captions[n[0]] = m.group("text").strip()
    text = CAPTION.sub("", text)
    for pattern, mode in ORDER:
        if pattern.search(text):
            ops.order = mode
            text = pattern.sub("", text)
            break
    # time ranges before segments: "后半段" is a range, not a clip
    for pattern, which in RANGE_HALF:
        if pattern.search(text):
            half = duration / 2 if duration else None
            ops.range = {"second": (half, None), "first": (None, half), "all": (None, None)}[which]
            text = pattern.sub("", text)
            break
    if ops.range is None and duration:
        if (m := RANGE_LAST.search(text)):
            ops.range = (max(0.0, duration - 60 * cn_int(m.group("n"))), None); text = RANGE_LAST.sub("", text)
        elif (m := RANGE_FIRST.search(text)):
            ops.range = (None, min(duration, 60 * cn_int(m.group("n")))); text = RANGE_FIRST.sub("", text)
        else:
            after, before = RANGE_AFTER.search(text), RANGE_BEFORE.search(text)
            if after or before:
                ops.range = (_seconds(after.group("t")) if after else None, _seconds(before.group("t")) if before else None)
                text = RANGE_BEFORE.sub("", RANGE_AFTER.sub("", text))
    if (m := KEEP.search(text)):
        ops.keep = seg_numbers(m.group("segs"), plays)
        text = KEEP.sub("", text)
    for m in list(REMOVE.finditer(text)):
        ops.remove += seg_numbers(m.group("segs") or m.group("segs2") or "", plays)
    text = REMOVE.sub("", text)
    ops.remove = sorted(set(ops.remove))
    rest = re.sub(r"^(?:再|也|还|就|把|帮我|请|麻烦)+", "", text.strip(" ，,、的了吧呢啊"))
    ops.rest = rest if re.search(r"[一-鿿A-Za-z0-9]{2,}", rest) else ""
    return ops


def reorder(segments: list[dict[str, Any]], mode: str | None) -> list[dict[str, Any]]:
    """Reorder plays; a slow-motion replay stays right after the play it revisits."""
    if not mode or mode == "time" or len(segments) < 2:
        return segments
    groups: list[list[dict[str, Any]]] = []
    for seg in segments:
        if seg.get("replay") and groups:
            groups[-1].append(seg)
        else:
            groups.append([seg])

    def score(g: list[dict[str, Any]]) -> float:
        lead = g[0]
        bonus = 1.0 if lead.get("outcome") == "made" else 0.0
        return bonus + float(lead.get("raw_model_score", 0) or 0)
    groups.sort(key=score, reverse=(mode == "best_first"))
    return [seg for g in groups for seg in g]


EXAMPLES = [
    "生成 20 秒投篮高光", "只要进球", "去掉第 2 段", "只保留第 1、3 段", "只要后半段", "最精彩的放最后",
    "缩短到 15 秒", "节奏快一点", "改成竖屏", "加慢动作回放", "换成热血配乐", "第 1 段字幕改成“开场三分”",
    "撤销", "分析一下这场", "这场进了几个球", "标题改成“街球之夜”",
]


def did_you_mean(text: str, k: int = 3) -> list[str]:
    def grams(s: str) -> set[str]:
        s = re.sub(r"\s+", "", s)
        return {s[i:i + 2] for i in range(len(s) - 1)} | set(s)
    g = grams(text)
    scored = sorted(((len(g & grams(e)) / (len(grams(e)) or 1), e) for e in EXAMPLES), reverse=True)
    return [e for s, e in scored[:k] if s >= 0.18]


def suggestions(plan: dict[str, Any] | None, has_made: bool, *, ai: bool = False, can_undo: bool = True) -> list[str]:
    """Next steps that fit what is on screen now."""
    if not plan or not plan.get("clips"):
        base = ["生成 20 秒投篮高光", "只要进球", "分析一下这场"]
        return base + (["哪一球最精彩？"] if ai else ["这场进了几个球"])
    plays = [c for c in plan["clips"] if not c.get("replay")]
    out = []
    if len(plays) >= 2:
        out.append(f"去掉第 {len(plays)} 段")
        out.append("最精彩的放最后")
    if has_made and not all(c.get("outcome") == "made" for c in plays):
        out.append("只要进球")
    style = plan.get("edit_style") or {}
    out.append("改成竖屏" if style.get("aspect") != "9:16" else "改回横屏")
    out.append("节奏快一点" if style.get("pace") != "tight" else "加慢动作回放")
    if can_undo:
        out.append("撤销")
    if ai:
        out.insert(0, "把没看点的镜头去掉")
    return out[:6]
