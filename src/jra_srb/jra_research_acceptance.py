"""概要: SQL研究受入台帳を実コードASTと現在の成果物へ読み取り照合する。
作成日: 2026-10-15
入力: 非秘密の受入台帳JSON、対象プロジェクトroot、既存manifest。
出力: 不整合、更新要確認、未受入項目、全体完了判定のdict。
実行例: uv run python scripts/run_jra_research.py acceptance-audit
注意事項: DB/HTTPへ接続せず、研究コードやモデルを実行・書込みしない。
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CASE_FIELDS = ("output_variants", "model_candidates", "purchase_policy_candidates", "fold_cases", "calibration_cases", "member_cases")
STATUSES = {"pending", "implemented_pending_acceptance", "verified", "blocked_data", "blocked_contract", "blocked_concurrent", "pending_scope_review"}


class _DefinitionError(ValueError):
    """実行せずに確定できない研究定義を示す。"""


def _evaluate(node: ast.AST, names: dict | None = None):
    """限定した定数式だけを評価し、importや任意コード実行を拒否する。"""
    scope = names or {}
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in scope:
        return scope[node.id]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        values = [_evaluate(n, scope) for n in node.elts]
        return tuple(values) if isinstance(node, ast.Tuple) else set(values) if isinstance(node, ast.Set) else values
    if isinstance(node, ast.Dict):
        return {_evaluate(k, scope): _evaluate(v, scope) for k, v in zip(node.keys, node.values, strict=True)}
    if isinstance(node, ast.BinOp):
        left, right = _evaluate(node.left, scope), _evaluate(node.right, scope)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left, right = _evaluate(node.left, scope), _evaluate(node.comparators[0], scope)
        if isinstance(node.ops[0], ast.In):
            return left in right
        if isinstance(node.ops[0], ast.NotIn):
            return left not in right
    if isinstance(node, ast.IfExp):
        return _evaluate(node.body if _evaluate(node.test, scope) else node.orelse, scope)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        allowed = {"range": range, "round": round, "tuple": tuple, "list": list, "len": len, "int": int, "max": max, "min": min}
        if node.func.id in allowed and not node.keywords:
            result = allowed[node.func.id](*[_evaluate(a, scope) for a in node.args])
            if isinstance(result, range) and len(result) > 10000:
                raise _DefinitionError("definition_too_large")
            return result
    if isinstance(node, (ast.GeneratorExp, ast.ListComp)) and len(node.generators) == 1:
        generator = node.generators[0]
        if isinstance(generator.target, ast.Name) and not generator.ifs and not generator.is_async:
            return [_evaluate(node.elt, {**scope, generator.target.id: value}) for value in _evaluate(generator.iter, scope)]
    raise _DefinitionError("unsupported_constant_expression")


class _Audit:
    """読取結果と不整合を集約し、証拠未達を成功へ昇格させない。"""

    def __init__(self, root: Path, registry: dict):
        """対象rootと台帳を保持し、読取cacheと結果一覧を初期化する。"""
        self.root, self.registry = root.resolve(), registry
        self.errors, self.updates, self.pending = [], [], []
        self.trees, self.manifests = {}, {}
        self.observed_evidence = {}

    def issue(self, code: str, path: str, *, update: bool = False, **details) -> None:
        """秘密本文を含めず、固定codeと対象path・構造化詳細を記録する。"""
        (self.updates if update else self.errors).append({"code": code, "path": path, "details": details})

    def path(self, relative: str) -> Path:
        """台帳参照をproject内へ限定し、絶対pathやsymlink逸脱を拒否する。"""
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise _DefinitionError("path_outside_project")
        resolved = (self.root / candidate).resolve()
        if not resolved.is_relative_to(self.root):
            raise _DefinitionError("path_outside_project")
        return resolved

    def tree(self, relative: str) -> ast.Module:
        """Pythonを実行せずUTF-8のASTだけを読み取る。"""
        if relative not in self.trees:
            self.trees[relative] = ast.parse(self.path(relative).read_text(encoding="utf-8-sig"))
        return self.trees[relative]

    def constant(self, relative: str, name: str):
        """モジュール定数を依存する先行定数とともに安全に再導出する。"""
        scope = {}
        for node in self.tree(relative).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                key = node.targets[0].id
                try:
                    scope[key] = _evaluate(node.value, scope)
                except (_DefinitionError, TypeError, ValueError):
                    if key == name:
                        raise _DefinitionError("unresolved_constant") from None
                if key == name:
                    return scope[key]
        raise _DefinitionError("missing_constant")

    def function(self, relative: str, name: str) -> ast.FunctionDef:
        """指定したトップレベル関数のASTを取得する。"""
        return next(node for node in self.tree(relative).body if isinstance(node, ast.FunctionDef) and node.name == name)

    def loop_values(self, relative: str, function: str, target: str):
        """関数内の指定loop変数の定数集合をコードから取得する。"""
        node = next(n for n in ast.walk(self.function(relative, function)) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == target)
        return _evaluate(node.iter)

    def expected_profiles(self) -> list[tuple]:
        """既存REGISTRYをimportせず読み、PROFILE_IDだけを定義元から解決する。"""
        profile = self.constant("src/jra_srb/jra_research_contracts.py", "PROFILE_ID")
        node = next(n for n in self.tree("src/jra_srb/jra_research_profiles.py").body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "REGISTRY")
        return list(_evaluate(node.value, {"PROFILE_ID": profile}))

    def compare(self, profile: dict, field: str, expected: set, observed: set) -> None:
        """定義集合の不足と余剰を別々に記録する。"""
        if expected != observed:
            self.issue("definition_set_mismatch", profile["profile_id"] + "/" + field,
                       missing=sorted(expected - observed, key=str), unexpected=sorted(observed - expected, key=str))

    def definition_sets(self, by_id: dict) -> None:
        """出力仮説・政策・fold・校正・memberを実ASTから再導出し照合する。"""
        ten_path, second_path = "scripts/jra_ten_trials_model.py", "scripts/jra_second_ten_model.py"
        trials, second = self.constant(ten_path, "EXPERIMENTS"), self.constant(second_path, "EXPERIMENTS")
        groups, thresholds = self.constant(ten_path, "GROUPS"), self.constant(ten_path, "THRESHOLDS")
        windows = []
        for stage, symbol in (("development", "DEV_WINDOWS"), ("exploratory_2026", "EVAL_WINDOWS"), ("sparse_september", "SUPPLEMENT")):
            for start, end in self.constant("scripts/evaluate_jra_ten_trials.py", symbol):
                windows.append((stage + "/" + start, stage, start, end))
        for profile_id, definitions in (("ten_trials_sql_v1", trials), ("second_ten_sql_v1", second)):
            profile = by_id[profile_id]
            self.compare(profile, "output_variants", set(definitions), {c["variant_id"] for c in profile["output_variants"]})
            for case in profile["output_variants"]:
                if case["variant_id"] in definitions and tuple(definitions[case["variant_id"]]) != (case.get("algorithm_id"), case.get("bet_type"), case.get("hypothesis")):
                    self.issue("experiment_definition_mismatch", profile_id + "/" + case["case_id"])
            expected = {(v, *w) for v in definitions for w in windows}
            observed = {(c.get("variant_id"), c.get("fold_id"), c.get("stage"), c.get("date_from"), c.get("date_through")) for c in profile["fold_cases"]}
            self.compare(profile, "fold_cases", expected, observed)
        profile = by_id["ten_trials_sql_v1"]
        self.compare(profile, "purchase_policy_candidates", set(itertools.product(trials, groups, thresholds)),
                     {(c.get("variant_id"), c.get("group"), c.get("threshold")) for c in profile["purchase_policy_candidates"]})
        dims = profile.get("policy_search_dimensions", {})
        if list(groups) != dims.get("groups") or list(thresholds) != dims.get("thresholds"):
            self.issue("policy_axes_mismatch", profile["profile_id"])
        policy = self.constant("scripts/evaluate_jra_second_ten.py", "POLICY")
        profile = by_id["second_ten_sql_v1"]
        self.compare(profile, "purchase_policy_candidates", {(v, policy["group"], policy["threshold"]) for v in second},
                     {(c.get("variant_id"), c.get("group"), c.get("threshold")) for c in profile["purchase_policy_candidates"]})
        scopes = {w[0] for w in windows} | {"release"}
        self.compare(profile, "calibration_cases", {"V106/" + s for s in scopes}, {c["case_id"] for c in profile["calibration_cases"]})
        loop = next(n for n in ast.walk(self.function(second_path, "fit_suite")) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "seed")
        member_ids = list(_evaluate(loop.iter))
        rng = next(n for n in ast.walk(loop) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "default_rng")
        expected_members = {(s, i, _evaluate(rng.args[0], {"seed": i})) for s in scopes for i in member_ids}
        self.compare(profile, "member_cases", expected_members, {(c.get("scope"), c.get("member_id"), c.get("seed")) for c in profile["member_cases"]})
        split = self.function(second_path, "chronological_calibration_split")
        boundary = next(n.value for n in split.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "boundary")
        recorded = profile.get("calibration_definition", {})
        if ast.dump(ast.parse(recorded.get("boundary", "None"), mode="eval").body) != ast.dump(boundary):
            self.issue("calibration_boundary_mismatch", profile["profile_id"])
        calibrate = self.function(second_path, "fit_calibrated")
        optimize = next(n for n in ast.walk(calibrate) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "minimize_scalar")
        bounds = _evaluate(next(k.value for k in optimize.keywords if k.arg == "bounds"))
        if list(bounds) != recorded.get("alpha_bounds"):
            self.issue("calibration_bounds_mismatch", profile["profile_id"])
        self.other_definition_sets(by_id, trials, second)

    def other_definition_sets(self, by_id: dict, trials: dict, second: dict) -> None:
        """残り研究族の出力・model候補・政策を実定義へ照合する。"""
        history_targets = set(self.loop_values("src/jra_srb/jra_history_model.py", "train_history_models", "target"))
        horizons = self.constant("scripts/build_jra_o1o2_asof_dataset.py", "HORIZONS")
        movement = set(self.loop_values("scripts/evaluate_jra_o1o2_movement.py", "evaluate_kind", "variant"))
        v91 = self.function("scripts/evaluate_jra_v91.py", "run")
        outputs = next(n for n in ast.walk(v91) if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple) and [getattr(x, "id", None) for x in n.target.elts] == ["name", "key"])
        v91_outputs = {_evaluate(n.elts[0]) for n in outputs.iter.elts}
        candidates = []
        for variant in self.loop_values("scripts/evaluate_jra_v91.py", "run", "variant"):
            penalties = next(n.value for n in ast.walk(v91) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "penalties")
            candidates.extend((variant, p) for p in _evaluate(penalties, {"variant": variant}))
        p = by_id["v91_compat_sql_v1"]
        self.compare(p, "model_candidates", set(candidates), {(c.get("variant"), c.get("penalty")) for c in p["model_candidates"]})
        ablation = self.function("scripts/validate_jra_o1o2_cross_pool.py", "ablation_train_only")
        ablation_node = next(n.value for n in ast.walk(ablation) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "feature_sets")
        ablation_names = {_evaluate(k) for k in ablation_node.keys}
        expected = {
            "history_sql_v1": history_targets, "recent_form_sql_v2": history_targets,
            "asof_o1o2_sql_v1": {h + "/" + m for h in horizons for m in ("O1_win", "O2_quinella")},
            "asof_odds_sql_v1": {h + "/" + m for h in horizons for m in ("win", "place")},
            "o1o2_movement_sql_v1": {k + "/" + v for k in ("win", "quinella") for v in movement},
            "cross_pool_sql_masked_v2": {"market", "basic", "cross"},
            "cross_pool_compat_sql_v1": {"market", "basic", "cross"} | ablation_names,
            "v91_compat_sql_v1": v91_outputs, "v91_score_sql_v1": v91_outputs,
            "ten_trials_score_sql_v1": set(trials), "second_ten_score_sql_v1": set(second), "analyze_predictions_v1": set(trials),
            "cross_market_disagreement_sql_v1": {"value", "information"},
            "hidden_rebound_sql_v1": {"top3_rebound"}, "hidden_rebound_external_sql_v1": {"top3_rebound_external"},
            "market_overlay_sql_v1": {"wide_overlay"}, "win_overlay_sql_v1": {"win_overlay"},
            "catboost_saved_day_sql_v1": {"saved_day_ranker"}, "cross_pool_saved_race_sql_v1": {"cross"},
        }
        for name, values in expected.items():
            self.compare(by_id[name], "output_variants", values, {c["variant_id"] for c in by_id[name]["output_variants"]})
        for profile_id in ("hidden_rebound_sql_v1", "hidden_rebound_external_sql_v1", "market_overlay_sql_v1", "win_overlay_sql_v1"):
            p = by_id[profile_id]
            if profile_id == "hidden_rebound_external_sql_v1":
                source = "scripts/evaluate_hidden_run_rebound_external.py"
                cs = [self.constant(source, "FROZEN_C")]
                ts = [self.constant(source, "FROZEN_PROBABILITY_THRESHOLD")]
            else:
                source = "scripts/evaluate_hidden_run_rebound.py" if profile_id == "hidden_rebound_sql_v1" else "scripts/evaluate_market_price_overlay.py"
                cs = self.constant(source, "CS")
                threshold_source = p["legacy_entries"][0]
                ts = self.constant(threshold_source, "PROBABILITY_THRESHOLDS" if profile_id == "hidden_rebound_sql_v1" else "OVERLAY_THRESHOLDS")
            self.compare(p, "model_candidates", set(cs), {c.get("C") for c in p["model_candidates"]})
            key = "probability_threshold" if "rebound" in profile_id else "overlay_threshold"
            self.compare(p, "purchase_policy_candidates", set(itertools.product(cs, ts)), {(c.get("C"), c.get(key)) for c in p["purchase_policy_candidates"]})
        p = by_id["cross_market_disagreement_sql_v1"]
        source = "scripts/evaluate_cross_market_disagreement.py"
        policies = {(direction, t) for direction, name in (("value", "VALUE_THRESHOLDS"), ("information", "INFORMATION_THRESHOLDS")) for t in self.constant(source, name)}
        self.compare(p, "purchase_policy_candidates", policies, {(c.get("direction"), c.get("threshold")) for c in p["purchase_policy_candidates"]})

    def sources(self) -> None:
        """固定sourceの実SHAと宣言された関数・定数symbolの実在を確認する。"""
        fingerprints = self.registry.get("source_fingerprints", {})
        if not isinstance(fingerprints, dict) or not fingerprints:
            self.issue("source_fingerprints_missing", "source_fingerprints")
            fingerprints = {}
        for relative, expected in fingerprints.items():
            try:
                actual = hashlib.sha256(self.path(relative).read_bytes()).hexdigest()
                if actual != expected:
                    self.issue("source_fingerprint_changed", relative, expected=expected, actual=actual)
            except (OSError, _DefinitionError) as error:
                self.issue("source_unreadable", relative, error_type=type(error).__name__)
        for profile in self.registry["profiles"]:
            for reference in profile.get("feature_contract", {}).get("code_symbols", []):
                try:
                    relative, symbol = reference.split("::")
                    names = {node.name for node in self.tree(relative).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                    names |= {t.id for node in self.tree(relative).body if isinstance(node, ast.Assign) for t in node.targets if isinstance(t, ast.Name)}
                    names |= {node.target.id for node in self.tree(relative).body
                              if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                              and node.value is not None}
                    if symbol not in names:
                        self.issue("symbol_missing", reference)
                    if relative not in fingerprints:
                        self.issue("symbol_source_fingerprint_missing", relative)
                except (OSError, ValueError, SyntaxError) as error:
                    self.issue("symbol_unreadable", reference, error_type=type(error).__name__)

    def evidence(self) -> None:
        """manifestの観測版と現在値を比較し、状態進行と破壊的変更を分ける。"""
        for key, item in self.registry.get("evidence", {}).items():
            try:
                path = self.path(item["path"])
                payload = path.read_bytes()
                manifest = json.loads(payload.decode("utf-8-sig"))
                config = json.loads((path.parent / "config.json").read_text(encoding="utf-8"))
                self.manifests[key] = manifest
                status = manifest.get("status")
                self.observed_evidence[key] = {"status": status, "command": manifest.get("command"), "manifest_sha256": hashlib.sha256(payload).hexdigest()}
                if manifest.get("run_id") != key or item.get("run_id") != key or manifest.get("command") != item.get("command") or config.get("profile_id") != item.get("profile_id"):
                    self.issue("evidence_identity_changed", item["path"])
                changed_hashes = [name for name, value in item.get("recorded_hashes", {}).items() if manifest.get(name) != value]
                if changed_hashes:
                    self.issue("evidence_recorded_content_changed", item["path"], fields=changed_hashes)
                actual = self.observed_evidence[key]["manifest_sha256"]
                if actual != item.get("manifest_sha256"):
                    progressed = item.get("observed_manifest_status") == "running" and status in {"running", "complete", "failed"}
                    self.issue("evidence_progress_requires_update" if progressed and not changed_hashes else "evidence_manifest_changed", item["path"], update=progressed and not changed_hashes, observed_status=item.get("observed_manifest_status"), current_status=status)
                elif item.get("observed_manifest_status") != status:
                    self.issue("evidence_observed_status_mismatch", item["path"])
                if not set(item.get("present_files", [])).issubset({p.name for p in path.parent.iterdir() if p.is_file()}):
                    self.issue("evidence_artifact_disappeared", item["path"])
                for name, expected in item.get("artifact_sha256", {}).items():
                    if Path(name).name != name or "/" in name or "\\" in name:
                        self.issue("evidence_artifact_path_invalid", item["path"], artifact=name)
                        continue
                    if hashlib.sha256((path.parent / name).read_bytes()).hexdigest() != expected:
                        self.issue("evidence_artifact_changed", item["path"], artifact=name)
                for model in manifest.get("models", {}).values():
                    model_path = path.parent / model["file"]
                    if not model_path.resolve().is_relative_to(path.parent.resolve()) or hashlib.sha256(model_path.read_bytes()).hexdigest() != model["sha256"]:
                        self.issue("evidence_model_changed", item["path"])
                if manifest.get("command") in {"history", "history-replay"} and status == "complete":
                    wrapper = json.loads((path.parent / "model_history.json").read_text(encoding="utf-8"))
                    model_hash = hashlib.sha256(json.dumps(wrapper["model"], ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
                    contract_hash = hashlib.sha256(json.dumps(wrapper["contract"], ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
                    if (model_hash != manifest.get("model_sha256")
                            or contract_hash != manifest.get("feature_contract_sha256")
                            or contract_hash != wrapper.get("contract_sha256")):
                        self.issue("evidence_model_changed", item["path"])
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.issue("evidence_unreadable", str(item.get("path", key)), error_type=type(error).__name__)

    def verification(self, item: dict, identifier: str, *, profile: dict | None = None) -> None:
        """verified宣言の証拠欠落・失敗run・単なる検査や列挙による昇格を拒否する。"""
        status = item.get("status", "pending")
        if status not in STATUSES:
            self.issue("unknown_acceptance_status", identifier, status=status)
        if status != "verified":
            self.pending.append({"kind": "profile" if profile is item else "case", "id": identifier, "status": status})
            return
        references = item.get("evidence", [])
        if not isinstance(references, list) or not references:
            self.issue("verified_evidence_missing", identifier)
            return
        for key in references:
            evidence = self.registry.get("evidence", {}).get(key)
            manifest = self.manifests.get(key)
            if not evidence or not manifest:
                self.issue("verified_evidence_unknown", identifier, evidence_id=key)
                continue
            if manifest.get("status") != "complete":
                self.issue("verified_run_not_complete", identifier, evidence_id=key, status=manifest.get("status"))
            if manifest.get("command") in {"profiles", "preflight", "coverage", "readiness", "acceptance-audit", "repair-results"}:
                self.issue("verified_evidence_not_acceptance", identifier, evidence_id=key)
            if evidence.get("evidence_status") != "verified":
                self.issue("verified_evidence_not_reviewed", identifier, evidence_id=key)
            required_artifacts = set(evidence.get("present_files", [])) - {"manifest.json"}
            if not required_artifacts or set(evidence.get("artifact_sha256", {})) != required_artifacts:
                self.issue("verified_artifact_fingerprints_missing", identifier, evidence_id=key)
            if profile and evidence.get("profile_id") not in {profile["profile_id"], *profile.get("requires_profiles", [])}:
                self.issue("verified_evidence_wrong_profile", identifier, evidence_id=key)

    def structure(self) -> dict:
        """全phase/family/profileと個別caseの一意性・受入状態を確認する。"""
        rows = self.registry.get("profiles", [])
        by_id = {r["profile_id"]: r for r in rows}
        if len(by_id) != len(rows):
            self.issue("duplicate_profile", "profiles")
        expected = self.expected_profiles()
        if set(by_id) != {r[1] for r in expected}:
            self.issue("profile_registry_mismatch", "profiles", expected=sorted(r[1] for r in expected), actual=sorted(by_id))
        for family, profile_id, entry, test, capability in expected:
            if profile_id not in by_id:
                continue
            row = by_id[profile_id]
            if row.get("family_id") != family or row.get("legacy_invocation") != entry or test not in row.get("acceptance_tests", []) or capability not in row.get("source_contract", {}).get("required_capabilities", []):
                self.issue("profile_contract_mismatch", profile_id)
        if {r.get("family_id") for r in rows} != {f"R{i:02d}" for i in range(1, 16)}:
            self.issue("family_set_mismatch", "profiles")
        phases = self.registry.get("phases", [])
        if {p.get("phase_id") for p in phases} != {"M2", "M3", "M4", "M5"} or len(phases) != 4:
            self.issue("phase_set_mismatch", "phases")
        for phase in phases:
            self.verification(phase, phase["phase_id"])
        for row in rows:
            self.verification(row, row["profile_id"], profile=row)
            for field in CASE_FIELDS:
                cases = row.get(field, [])
                if len(cases) != len({c["case_id"] for c in cases}):
                    self.issue("duplicate_case_id", row["profile_id"] + "/" + field)
                for case in cases:
                    self.verification(case, row["profile_id"] + "/" + field + "/" + case["case_id"], profile=row)
            for case in row.get("component_cases", []):
                self.verification(case, row["profile_id"] + "/component_cases/" + case["case_id"], profile=row)
            if row.get("status") == "verified":
                if row.get("missing_requirements") or any(case.get("status") != "verified" for field in CASE_FIELDS for case in row.get(field, [])):
                    self.issue("verified_profile_incomplete", row["profile_id"])
                contract, artifacts = row.get("feature_contract", {}), row.get("permitted_model_artifacts", {})
                if contract.get("status") != "verified" or not contract.get("contract_sha256") or artifacts.get("status") not in {"verified", "declared"}:
                    self.issue("verified_profile_contract_missing", row["profile_id"])
        closure = self.registry.get("call_closure_audit", {})
        if closure.get("status") != "verified":
            self.pending.append({"kind": "closure", "id": "call_closure_audit", "status": closure.get("status", "pending")})
        for item in closure.get("unclassified_candidates", []):
            if item.get("status") not in {"verified", "excluded_with_evidence"}:
                self.pending.append({"kind": "unclassified", "id": item.get("path"), "status": item.get("status", "pending")})
            elif not item.get("evidence"):
                self.issue("closure_resolution_evidence_missing", item.get("path", "unknown"))
        for gate in self.registry.get("completion_gates", []):
            self.verification(gate, gate["gate_id"])
        if not self.registry.get("completion_gates"):
            self.issue("completion_gates_missing", "completion_gates")
        return by_id


def audit_acceptance_registry(registry_path: str | Path | None = None, *, project_root: str | Path | None = None) -> dict:
    """台帳・実コード・現在artifactを照合し、未受入を含む監査結果を返す。

    Args:
        registry_path: 台帳JSON。省略時は対象rootのconfigs/research配下。
        project_root: 読取を許す案件root。省略時はこのmoduleの配置から解決する。

    Returns:
        statusはpassed/failed/needs_update。正しいpending台帳も監査自体はpassedだが、
        overall_completeは全受入・閉包・証拠が成立する場合だけtrue。
        errorsは構造/実定義/証拠破損、updates_requiredはmanifest状態進行の再確認を表す。

    Notes:
        DB/HTTP/import対象研究/学習の実行とファイル書込みを行わない。
        本監査は証跡の整合性を確認する。試験の要件充足範囲を人がレビューする責務は残る。
    """
    root = Path(project_root) if project_root is not None else ROOT
    target = Path(registry_path) if registry_path is not None else root / "configs/research/acceptance_registry.json"
    result = {"schema_version": 1, "status": "failed", "overall_complete": False, "errors": [], "updates_required": [], "pending": [], "counts": {}, "observed_evidence": {}}
    try:
        registry_payload = target.read_bytes()
        registry = json.loads(registry_payload.decode("utf-8-sig"))
        result["registry_sha256"] = hashlib.sha256(registry_payload).hexdigest()
        if not isinstance(registry, dict) or registry.get("schema_version") != 1:
            raise _DefinitionError("unsupported_registry_schema")
    except (OSError, ValueError, TypeError) as error:
        result["errors"].append({"code": "registry_unreadable", "path": str(target), "details": {"error_type": type(error).__name__}})
        return result
    audit = _Audit(root, registry)
    try:
        by_id = audit.structure()
        audit.sources()
        audit.definition_sets(by_id)
        audit.evidence()
        # verifiedの実manifest判定は、読取完了後にもう一度行う。
        audit.errors = [e for e in audit.errors if e["code"] != "verified_evidence_unknown"]
        for profile in registry["profiles"]:
            items = [profile, *(c for field in CASE_FIELDS for c in profile.get(field, [])), *profile.get("component_cases", [])]
            for item in items:
                if item.get("status") == "verified":
                    audit.verification(item, profile["profile_id"] + "/" + item.get("case_id", "profile"), profile=profile)
        for item in [*registry.get("phases", []), *registry.get("completion_gates", [])]:
            if item.get("status") == "verified":
                audit.verification(item, item.get("phase_id", item.get("gate_id", "unknown")))
    except (OSError, ValueError, KeyError, TypeError, StopIteration, SyntaxError) as error:
        audit.issue("registry_or_definition_invalid", str(target), error_type=type(error).__name__)
    complete = not audit.errors and not audit.updates and not audit.pending
    if registry.get("overall_complete") is True and not complete:
        audit.issue("overall_completion_unproven", "overall_complete")
    result.update(status="failed" if audit.errors else "needs_update" if audit.updates else "passed", overall_complete=complete,
                  errors=audit.errors, updates_required=audit.updates, pending=audit.pending, observed_evidence=audit.observed_evidence,
                  counts={"profiles": len(registry.get("profiles", [])), "verified_profiles": sum(p.get("status") == "verified" for p in registry.get("profiles", [])),
                          "pending_items": len(audit.pending), "errors": len(audit.errors), "updates_required": len(audit.updates)})
    return result
