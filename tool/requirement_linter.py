"""Requirement Linter / Quality Analyzer

Usage (example):
    python requirement_linter.py requirements.txt --format markdown

Input:
    A text file with one requirement per paragraph (blank line separates),
    or a CSV with a column named '需求描述' / 'Requirement'.

Output:
    Prints a table / JSON with per-requirement metrics and an overall summary.

Metrics Implemented:
    - length_chars: 字符数
    - sentence_count: 句子数
    - avg_sentence_len: 平均句长
    - vague_terms: 模糊词列表
    - vague_density: 模糊词/总词数
    - has_numeric_criteria: 是否包含数字/阈值/时间 (判据)
    - conjunction_complexity: 复合连接词个数 (且/并且/如果/否则 等)
    - atomicity_flag: 是否疑似非原子 (复合连接>2)
    - undefined_abbr: 未在术语词典中的大写缩写集合
    - trace_id_present: 是否包含 REQ-* 或 ID 格式
    - quality_score: 综合评分 (0-100)

Scoring (可调整):
    start 100
    - len(vague_terms)*1.5
    - (not has_numeric_criteria)*15
    - (conjunction_complexity>2)*8
    - (vague_density>0.01)*(vague_density*200)
    - (not trace_id_present)*5
    + (has_risk_token)*5
    + (has_boundary_token)*5

Author: Auto-generated scaffold.
"""
from __future__ import annotations
import re
import json
import argparse
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Iterable, Optional

VAGUE_WORDS = [
    "快速","及时","适当","合理","高效","稳定","良好","较好","尽快","优先","适宜",
    "可靠","安全性高","智能","灵活","可扩展","易用","健壮","优化","完善"
]
# 术语词典 (示例) - 可外部传入
KNOWN_TERMS = {"SOC","CAN","PWM","ADC","CRC","OBC","BMS","CCU","EVCC"}
RISK_TOKENS = ["风险","假设","限制","前提"]
BOUNDARY_TOKENS = ["边界","极限","阈值","上限","下限"]
TRACE_PATTERN = re.compile(r"\b(REQ-[A-Za-z0-9_-]+)\b")
ABBR_PATTERN = re.compile(r"\b([A-Z]{2,})\b")
SENTENCE_SPLIT = re.compile(r"[。.!?！？]")
NUMERIC_PATTERN = re.compile(r"(>=|<=|==|>|<|≈|±|\b\d+ms\b|\b\d+\.\d+|\b\d+%)")
CONJ_PATTERN = re.compile(r"(如果|且|并且|以及|或者|否则|同时)")

@dataclass
class RequirementMetrics:
    req_index: int
    raw: str
    length_chars: int
    sentence_count: int
    avg_sentence_len: float
    vague_terms: List[str]
    vague_density: float
    has_numeric_criteria: bool
    conjunction_complexity: int
    atomicity_flag: bool
    undefined_abbr: List[str]
    trace_id_present: bool
    has_risk_token: bool
    has_boundary_token: bool
    quality_score: float


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fa5]", text)

def calc_quality_score(m: RequirementMetrics) -> float:
    score = 100.0
    score -= len(m.vague_terms) * 1.5
    if not m.has_numeric_criteria:
        score -= 15
    if m.conjunction_complexity > 2:
        score -= 8
    if m.vague_density > 0.01:
        score -= m.vague_density * 200
    if not m.trace_id_present:
        score -= 5
    if m.has_risk_token:
        score += 5
    if m.has_boundary_token:
        score += 5
    return max(0.0, min(100.0, score))

def analyze_requirement(text: str, idx: int) -> RequirementMetrics:
    t = text.strip()
    tokens = tokenize(t)
    length_chars = len(t)
    # sentence split
    sentences = [s for s in SENTENCE_SPLIT.split(t) if s.strip()]
    sentence_count = max(1, len(sentences))
    avg_sentence_len = length_chars / sentence_count
    # vague
    vague_terms = [w for w in VAGUE_WORDS if w in t]
    vague_density = len(vague_terms) / max(1, len(tokens))
    has_numeric = bool(NUMERIC_PATTERN.search(t))
    conj = CONJ_PATTERN.findall(t)
    conj_complexity = len(conj)
    atomicity_flag = conj_complexity > 2
    # abbreviations
    abbrs = set(ABBR_PATTERN.findall(t))
    undefined = sorted([a for a in abbrs if a not in KNOWN_TERMS and not a.startswith('REQ')])
    trace_id_present = bool(TRACE_PATTERN.search(t))
    has_risk_token = any(r in t for r in RISK_TOKENS)
    has_boundary_token = any(b in t for b in BOUNDARY_TOKENS)
    metrics = RequirementMetrics(
        req_index=idx,
        raw=t,
        length_chars=length_chars,
        sentence_count=sentence_count,
        avg_sentence_len=avg_sentence_len,
        vague_terms=vague_terms,
        vague_density=vague_density,
        has_numeric_criteria=has_numeric,
        conjunction_complexity=conj_complexity,
        atomicity_flag=atomicity_flag,
        undefined_abbr=undefined,
        trace_id_present=trace_id_present,
        has_risk_token=has_risk_token,
        has_boundary_token=has_boundary_token,
        quality_score=0.0,
    )
    metrics.quality_score = calc_quality_score(metrics)
    return metrics


def iter_requirements_from_text(raw_text: str) -> Iterable[str]:
    parts = re.split(r"\n\s*\n+", raw_text.strip())
    for p in parts:
        cleaned = p.strip()
        if cleaned:
            yield cleaned


def load_requirements(path: str, column: Optional[str] = None) -> List[str]:
    import os
    import csv
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if path.lower().endswith('.csv'):
        with open(path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                if column and column in row:
                    rows.append(row[column])
                else:
                    # auto detect
                    for c in ('需求描述','Requirement','description','req'):
                        if c in row and row[c].strip():
                            rows.append(row[c])
                            break
            return rows
    else:
        with open(path,'r',encoding='utf-8') as f:
            return list(iter_requirements_from_text(f.read()))


def summarize(metrics: List[RequirementMetrics]) -> Dict[str, Any]:
    if not metrics:
        return {}
    avg_score = sum(m.quality_score for m in metrics)/len(metrics)
    vague_density = sum(m.vague_density for m in metrics)/len(metrics)
    atomic_ratio = sum(1 for m in metrics if m.atomicity_flag)/len(metrics)
    no_numeric_ratio = sum(1 for m in metrics if not m.has_numeric_criteria)/len(metrics)
    trace_gap = sum(1 for m in metrics if not m.trace_id_present)/len(metrics)
    return {
        'count': len(metrics),
        'avg_score': round(avg_score,2),
        'avg_vague_density': round(vague_density,4),
        'atomicity_ratio': round(atomic_ratio,3),
        'no_numeric_ratio': round(no_numeric_ratio,3),
        'trace_gap_ratio': round(trace_gap,3),
    }


def format_markdown(metrics: List[RequirementMetrics]) -> str:
    lines = ["|#|Score|Len|Sent|Vague|Num?|Trace?|Atomic?|Undefined|Excerpt|",
             "|--|--|--|--|--|--|--|--|--|--|"]
    for m in metrics:
        excerpt = (m.raw[:30] + '...') if len(m.raw) > 30 else m.raw
        lines.append(f"|{m.req_index}|{m.quality_score:.1f}|{m.length_chars}|{m.sentence_count}|{len(m.vague_terms)}|{'Y' if m.has_numeric_criteria else 'N'}|{'Y' if m.trace_id_present else 'N'}|{'Y' if m.atomicity_flag else 'N'}|{len(m.undefined_abbr)}|{excerpt}|")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Requirement Linter")
    p.add_argument('path', help='requirements text or csv file')
    p.add_argument('--column', help='CSV column name containing requirements')
    p.add_argument('--format', choices=['json','markdown'], default='markdown')
    p.add_argument('--top', type=int, default=0, help='Show top N lowest score details')
    args = p.parse_args()

    reqs = load_requirements(args.path, args.column)
    metrics = [analyze_requirement(r,i+1) for i,r in enumerate(reqs)]
    summary = summarize(metrics)

    if args.format == 'json':
        print(json.dumps({'summary':summary,'items':[asdict(m) for m in metrics]}, ensure_ascii=False, indent=2))
    else:
        print('# Summary')
        print(json.dumps(summary, ensure_ascii=False))
        print('\n# Detail')
        print(format_markdown(metrics))
    if args.top>0:
        worst = sorted(metrics, key=lambda m: m.quality_score)[:args.top]
        print('\n# Lowest Scores')
        for m in worst:
            print(f"\n## Req {m.req_index} (Score {m.quality_score:.1f})\n{m.raw}\nUndefined: {m.undefined_abbr}  Vague: {m.vague_terms}")

if __name__ == '__main__':
    main()
