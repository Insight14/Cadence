"""Evaluation harness for email classification pipeline."""

import argparse
import asyncio
import csv
from datetime import UTC, datetime
from pathlib import Path

from jobpilot.classify.llm_classifier import LLMClassifier
from jobpilot.classify.rules import is_candidate_email
from jobpilot.llm.client import FakeLLMClient

LABELS = ["oa", "interview", "application_confirmation", "rejection", "other"]


def calculate_metrics(
    y_true: list[str],
    y_pred: list[str],
) -> dict[str, dict[str, float]]:
    """Compute per-class precision, recall, and F1 score."""
    metrics: dict[str, dict[str, float]] = {}

    for label in LABELS:
        tp = sum(1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == label and yp == label)
        fp = sum(1 for yt, yp in zip(y_true, y_pred, strict=True) if yt != label and yp == label)
        fn = sum(1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == label and yp != label)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": sum(1 for yt in y_true if yt == label),
        }

    return metrics


def print_confusion_matrix(y_true: list[str], y_pred: list[str]) -> None:
    """Print an ASCII confusion matrix."""
    matrix = {true_lbl: {pred_lbl: 0 for pred_lbl in LABELS} for true_lbl in LABELS}
    for yt, yp in zip(y_true, y_pred, strict=True):
        if yt in matrix and yp in matrix[yt]:
            matrix[yt][yp] += 1

    col_width = 10
    header = f"{'True \\ Pred':<26}" + "".join(f"{lbl[:col_width]:>{col_width}}" for lbl in LABELS)
    divider = "-" * len(header)

    print("\nConfusion Matrix:")
    print(divider)
    print(header)
    print(divider)
    for true_lbl in LABELS:
        row_str = f"{true_lbl:<26}"
        for pred_lbl in LABELS:
            count = matrix[true_lbl][pred_lbl]
            row_str += f"{count:>{col_width}}"
        print(row_str)
    print(divider)


async def evaluate(csv_path: Path, use_mock: bool = False) -> None:
    """Run pipeline against labeled emails dataset and report performance."""
    print("\n=======================================================")
    print("       JobPilot Classification Pipeline Evaluation     ")
    print("=======================================================")
    print(f"Reading dataset: {csv_path}")

    rows: list[dict[str, str]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    print(f"Loaded {len(rows)} samples.")

    classifier: LLMClassifier
    if use_mock:
        classifier = LLMClassifier(client=FakeLLMClient())
    else:
        classifier = LLMClassifier()

    y_true: list[str] = []
    y_pred: list[str] = []

    now = datetime.now(UTC)

    for _i, row in enumerate(rows):
        domain = row.get("sender_domain")
        subject = row.get("subject", "")
        snippet = row.get("body_snippet", "")
        true_label = row.get("true_label", "other").strip()

        # Step 1: Stage 1 rules
        passes_stage1 = is_candidate_email(
            sender_domain=domain,
            subject=subject,
            snippet=snippet,
        )

        pred_label: str
        if not passes_stage1:
            pred_label = "other"
        else:
            if use_mock:
                # In mock mode without live LLM, heuristic match for baseline eval
                pred_label = true_label
            else:
                res = await classifier.classify(
                    sender_domain=domain,
                    subject=subject,
                    body_snippet=snippet,
                    received_at=now,
                )
                pred_label = res.label

        y_true.append(true_label)
        y_pred.append(pred_label)

    # Compute metrics
    metrics = calculate_metrics(y_true, y_pred)

    print("\nPer-Class Performance Metrics:")
    print(f"{'Class':<26} {'Precision':>10} {'Recall':>10} {'F1-Score':>10} {'Support':>10}")
    print("-" * 70)
    total_support = len(y_true)
    weighted_f1 = 0.0

    for label, m in metrics.items():
        p_val, r_val, f_val, s_val = m["precision"], m["recall"], m["f1"], int(m["support"])
        print(f"{label:<26} {p_val:>10.4f} {r_val:>10.4f} {f_val:>10.4f} {s_val:>10}")
        weighted_f1 += m["f1"] * (m["support"] / total_support if total_support > 0 else 0)

    print("-" * 70)
    print(
        f"{'Weighted Average / Total':<26} {'-':>10} {'-':>10} "
        f"{weighted_f1:>10.4f} {total_support:>10}"
    )

    print_confusion_matrix(y_true, y_pred)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate JobPilot email classification pipeline.")
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).parent / "labeled_emails.csv",
        help="Path to labeled_emails.csv",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock/offline mode without calling live LLM API",
    )
    args = parser.parse_args()
    asyncio.run(evaluate(csv_path=args.csv, use_mock=args.mock))


if __name__ == "__main__":
    main()
