"""Harness-Bench's own scoring of one workspace, run outside its grader container: what docker/grader/
grade_entrypoint.py does (the task's hidden tests/test_outcome.py over the case manifest, the required artifacts and
the workspace change contract, through the benchmark's own harnessbench.grading), with the checkout's task folder
where the container mounts /hidden. Run by a Python the tasks are written for (3.12 or later) that has PyYAML:

    python -I grade.py manifest <workspace>                              the workspace's manifest, as JSON
    python -I grade.py score <checkout> <task id> <workspace> <before>   the result, as JSON; <before> is the
                                                                         manifest taken before the agent worked

The semantic judge (a model reading the prose artifacts, at most its `max_fallback_weight` of a task) is not run:
a case only it can award stays unawarded, and the result says so (`judge_not_run`)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    checkout = Path(argv[2] if argv[0] == "manifest" else argv[1])
    sys.path.insert(0, str(checkout / "src"))
    import yaml
    from harnessbench.grading.oracle_contract import (
        STRUCTURAL_POLICY_CASE_OWNED,
        safe_score_workspace,
        workspace_manifest,
        workspace_mutation_report,
    )
    from harnessbench.grading.outcome_cases import score_workspace_from_cases
    if argv[0] == "manifest":
        print(json.dumps(workspace_manifest(Path(argv[1]))))
        return 0
    task_dir, workspace = checkout / "tasks" / argv[2], Path(argv[3])
    before = json.loads(Path(argv[4]).read_text(encoding="utf-8"))
    task = yaml.safe_load((task_dir / "task.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((task_dir / (task.get("cases_file") or "tests/cases.yaml")).read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("hidden_oracle", task_dir / task["outcome_test"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mutation = workspace_mutation_report(before, workspace_manifest(workspace), contract=task.get("mutation_contract"),
                                         protected_paths=set(before))
    result = safe_score_workspace(
        lambda place: score_workspace_from_cases(place, manifest=manifest, evaluate_cases=module.evaluate_cases,
                                                 task_id=task["task_id"]),
        workspace=workspace, required_artifacts=task.get("required_artifacts", []), task_id=task["task_id"],
        workspace_mutation=mutation, require_task_success=True, structural_policy=STRUCTURAL_POLICY_CASE_OWNED)
    result["judge_not_run"] = bool(task.get("semantic_judge"))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
