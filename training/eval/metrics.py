"""
评估指标：JSON 合法率、schema 合规率、action accuracy、selection precision/recall/F1。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from training.reward import (
    BaseAction,
    validate_json_format,
    validate_schema_compliance_model_a,
    validate_schema_compliance_model_b,
)


def compute_maintainer_metrics(
    predictions: List[str],
    references: Optional[List[Dict]] = None,
) -> Dict[str, float]:
    """
    计算记忆管理模型评估指标。
    - json_valid_rate: JSON 解析成功率
    - schema_compliance_rate: schema 合规率（无违规）
    - base_action_accuracy: base_action 与 reference 一致率（需 references）
    """
    n = len(predictions)
    if n == 0:
        return {"json_valid_rate": 0.0, "schema_compliance_rate": 0.0, "base_action_accuracy": 0.0}

    json_valid = 0
    schema_ok = 0
    action_match = 0
    for i, pred in enumerate(predictions):
        try:
            parsed = json.loads(pred)
            json_valid += 1
        except (json.JSONDecodeError, TypeError):
            continue
        has_violation, _ = validate_schema_compliance_model_a(parsed)
        if not has_violation:
            schema_ok += 1
        if references and i < len(references):
            ref = references[i]
            if isinstance(ref, dict) and "decisions" in ref:
                ref_actions = {d.get("base_action") for d in ref["decisions"]}
                pred_actions = {d.get("base_action") for d in parsed.get("decisions", [])}
                if ref_actions == pred_actions:
                    action_match += 1

    return {
        "json_valid_rate": json_valid / n,
        "schema_compliance_rate": schema_ok / n,
        "base_action_accuracy": action_match / n if references else 0.0,
    }


def compute_consolidator_metrics(
    predictions: List[str],
    references: Optional[List[Dict]] = None,
) -> Dict[str, float]:
    """
    计算记忆整理模型评估指标。
    - json_valid_rate: JSON 解析成功率
    - schema_compliance_rate: schema 合规率
    - selection_precision/recall/F1: 与 reference 的 selected 一致率（需 references）
    """
    n = len(predictions)
    if n == 0:
        return {
            "json_valid_rate": 0.0,
            "schema_compliance_rate": 0.0,
            "selection_precision": 0.0,
            "selection_recall": 0.0,
            "selection_f1": 0.0,
        }

    json_valid = 0
    schema_ok = 0
    precisions, recalls = [], []
    for i, pred in enumerate(predictions):
        try:
            parsed = json.loads(pred)
            json_valid += 1
        except (json.JSONDecodeError, TypeError):
            continue
        has_violation, _ = validate_schema_compliance_model_b(parsed)
        if not has_violation:
            schema_ok += 1
        if references and i < len(references):
            ref = references[i]
            if isinstance(ref, dict) and "memories" in ref:
                ref_selected = {m["mem_id"] for m in ref["memories"] if m.get("selected")}
                pred_selected = {m["mem_id"] for m in parsed.get("memories", []) if m.get("selected")}
                if pred_selected:
                    prec = len(ref_selected & pred_selected) / len(pred_selected)
                else:
                    prec = 1.0 if not ref_selected else 0.0
                if ref_selected:
                    rec = len(ref_selected & pred_selected) / len(ref_selected)
                else:
                    rec = 1.0 if not pred_selected else 0.0
                precisions.append(prec)
                recalls.append(rec)

    avg_prec = sum(precisions) / len(precisions) if precisions else 0.0
    avg_rec = sum(recalls) / len(recalls) if recalls else 0.0
    f1 = 2 * avg_prec * avg_rec / (avg_prec + avg_rec) if (avg_prec + avg_rec) > 0 else 0.0

    return {
        "json_valid_rate": json_valid / n,
        "schema_compliance_rate": schema_ok / n,
        "selection_precision": avg_prec,
        "selection_recall": avg_rec,
        "selection_f1": f1,
    }
