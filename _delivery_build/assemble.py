# -*- coding: utf-8 -*-
"""组装交付包:从原项目复制资产到 _delivery_build/基于Text2SQL的电商智能数据分析Agent/
原项目只读,不做任何修改/移动/删除。"""
import shutil
from pathlib import Path

ROOT = Path(r"F:\基于 Text2SQL 的电商智能数据分析 Agent")
PKG = ROOT / "_delivery_build" / "基于Text2SQL的电商智能数据分析Agent"

IGNORE_TOP = {".git", ".venv", ".pytest_cache", "__pycache__", ".workbuddy-ai",
              "_delivery_build", "_task36", ".zcodeignore", "tools"}


def cp(src: Path, dst: Path):
    if not src.exists():
        raise FileNotFoundError(f"MISSING: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def ignore_py(p, names):
    return [n for n in names if n in {"__pycache__", ".pytest_cache", ".venv", "node_modules"}
            or n.endswith(".pyc")]


def main():
    if PKG.exists():
        shutil.rmtree(PKG)
    PKG.mkdir(parents=True)
    R, P = ROOT, PKG

    # ---------- 01_项目文档与说明 ----------
    D = P / "01_项目文档与说明"
    for f in ["PRD.md", "UI-UX.md", "database-schema.md", "architecture-options.md",
              "tech-research.md", "project-parameters.md"]:
        cp(R / "docs" / f, D / "01_项目设计" / f)
    for f in ["backend-architecture.md", "langgraph-agent.md", "schema-linking.md",
              "fewshot-retrieval.md", "sql-generator.md", "sql-executor.md",
              "sql-repair.md", "agent-trace.md", "llm-integration.md"]:
        cp(R / "docs" / f, D / "02_系统架构" / f)
    for f in ["API.md", "DEPLOYMENT.md", "OPERATIONS.md"]:
        cp(R / "docs" / f, D / "03_API与部署" / f)
    for f in ["TEST_REPORT.md"]:
        cp(R / "docs" / f, D / "04_测试与验收" / f)
    for f in ["FINAL_ACCEPTANCE_REPORT.md", "FINAL_REQUIREMENTS_CHECKLIST.md",
              "FINAL_DELIVERY_GAP_CHECK.md"]:
        cp(R / "reports" / f, D / "04_测试与验收" / f)
    cp(R / "docs" / "phase4-task10-acceptance.md", D / "04_测试与验收" / "phase4-task10-acceptance.md")
    for f in ["AI_COLLABORATION.md", "project-understanding.md", "development-baseline.md"]:
        cp(R / "docs" / f, D / "05_AI协作与实施" / f)

    # ---------- 02_数据与评测 ----------
    D = P / "02_数据与评测"
    cp(R / "db" / "ecommerce.db", D / "01_电商数据库" / "ecommerce.db")
    cp(R / "docs" / "database-schema.md", D / "01_电商数据库" / "数据库设计说明.md")
    for f in ["ecommerce_eval_v1.json", "README.md", "error_taxonomy_v2.json"]:
        cp(R / "data" / "eval" / f, D / "02_Benchmark" / f)
    for f in ["evaluation-plan.md", "evaluation-matrix.md", "evaluation-dataset-spec.md",
              "evaluation-batch-1-review.md", "evaluation-batch-2-review.md",
              "evaluation-batch-3-review.md", "evaluation-batch-4-review.md"]:
        cp(R / "docs" / f, D / "02_Benchmark" / "评测方法与复核" / f)
    cp(R / "data" / "prompts" / "sql_generator_v1.3.txt", D / "03_Gold与Prompt" / "sql_generator_v1.3.txt")
    cp(R / "data" / "fewshot" / "ecommerce_examples.json", D / "03_Gold与Prompt" / "ecommerce_examples.json")
    EV = D / "04_正式评测结果"
    cp(R / "reports" / "eval" / "clean_baseline_v1_1", EV / "clean_baseline_v1_1")
    cp(R / "reports" / "FINAL_EXPERIMENT_MATRIX.md", EV / "FINAL_EXPERIMENT_MATRIX.md")
    cp(R / "reports" / "FINAL_BAD_CASE_CATALOG.md", EV / "FINAL_BAD_CASE_CATALOG.md")
    E3 = EV / "E3_实验冻结"
    cp(R / "reports" / "eval" / "E3_FINAL_FREEZE.md", E3 / "E3_FINAL_FREEZE.md")
    cp(R / "reports" / "eval" / "task22_freeeze_hash_baseline.json", E3 / "task22_freeeze_hash_baseline.json")
    for d in ["task17_e3_fanout_validator", "task18_e3_detector_correlation",
              "task19_e3_fanout_audit", "task20_e3_hint_intervention",
              "task21_e3_hint_intervention"]:
        cp(R / "reports" / "eval" / d, E3 / d)
    cp(R / "reports" / "eval" / "task23_final_acceptance", EV / "E2E_验证" / "task23_final_acceptance")
    RB = EV / "发布基线冻结"
    for f in ["RELEASE_BASELINE_20260920.md", "RELEASE_BASELINE_20260920.json",
              "RELEASE_BASELINE_MANIFEST.md", "RELEASE_BASELINE_MANIFEST.json",
              "CANDIDATE_A_PROMOTION_MANIFEST.md", "CANDIDATE_A_PROMOTION_MANIFEST.json",
              "CANDIDATE_A_PROMOTION_REVIEW.md", "CANDIDATE_A_PROMOTION_REVIEW.json"]:
        cp(R / "reports" / f, RB / f)
    H = D / "05_历史实验"
    for d in ["baseline_v1", "e1_semantics_v1", "e2_fewshot_v1", "e4_output_contract",
              "e5_metric_semantics", "e6_nested_aggregation", "e7_case_boundary",
              "stability_v1"]:
        cp(R / "reports" / "eval" / d, H / "专项实验" / d)
    cp(R / "reports" / "eval" / "task16", H / "专项实验" / "task16_fewshot候选")
    for f in (R / "reports" / "eval").glob("eval_2026*.*"):
        cp(f, H / "评测运行记录" / f.name)
    for f in ["bad_case_analysis_v1.md", "bad_case_analysis_v2.md",
              "stable_bad_cases_v1.md", "legacy_experiments_notice.md"]:
        cp(R / "reports" / "eval" / f, H / f)
    cp(R / "data" / "eval" / "bad_cases", H / "评测产物与草稿" / "bad_cases")
    cp(R / "data" / "eval" / "drafts", H / "评测产物与草稿" / "drafts")
    for f in ["error_taxonomy_v1.json", "ecommerce_multiturn_v1.json"]:
        cp(R / "data" / "eval" / f, H / "旧版本数据" / f)
    for f in ["sql_generator_v1.txt", "sql_generator_v1.1.txt"]:
        cp(R / "data" / "prompts" / f, H / "旧版本数据" / f)
    cp(R / "data" / "fewshot" / "ecommerce_examples_fewshot_v1.json",
       H / "旧版本数据" / "ecommerce_examples_fewshot_v1.json")

    # ---------- 03_答辩与演示 ----------
    D = P / "03_答辩与演示"
    cp(R / "reports" / "task26_ppt" / "goal.json", D / "PPT源文件" / "goal.json")
    cp(R / "reports" / "task26_ppt" / "ppt", D / "PPT源文件" / "ppt")
    cp(R / "reports" / "PPT_CONTENT.md", D / "PPT文字记录.md")
    cp(R / "reports" / "DEMO_SCRIPT.md", D / "Demo演示脚本.md")
    cp(R / "reports" / "DEFENSE_QA.md", D / "答辩QA预案.md")
    cp(R / "reports" / "DEFENSE_CHECKLIST.md", D / "答辩检查清单.md")
    cp(R / "reports" / "ppt_assets", D / "演示截图")

    # ---------- 04_项目源码(完整快照) ----------
    D = P / "04_项目源码"

    def ignore_snap(dirpath, names):
        ig = []
        for n in names:
            if n in {".git", ".venv", ".pytest_cache", "__pycache__", "node_modules",
                     ".workbuddy-ai", "_delivery_build", "_task36", ".zcodeignore"}:
                ig.append(n)
            elif n.endswith(".log") or n == ".env" or n == "app.db":
                ig.append(n)
        return ig

    shutil.copytree(R, D, ignore=ignore_snap, dirs_exist_ok=True)

    # ---------- 05_部署运行版 ----------
    D = P / "05_部署运行版"
    (D / "backend").mkdir(parents=True, exist_ok=True)
    shutil.copy2(R / "backend" / "__init__.py", D / "backend" / "__init__.py")
    shutil.copytree(R / "backend" / "app", D / "backend" / "app", ignore=ignore_py)
    shutil.copytree(R / "frontend", D / "frontend",
                    ignore=lambda p, n: [x for x in n if x in {"node_modules", "dist"}])
    (D / "data" / "eval").mkdir(parents=True)
    for f in ["ecommerce_eval_v1.json", "README.md", "error_taxonomy_v2.json"]:
        shutil.copy2(R / "data" / "eval" / f, D / "data" / "eval" / f)
    (D / "data" / "fewshot").mkdir(parents=True)
    shutil.copy2(R / "data" / "fewshot" / "ecommerce_examples.json", D / "data" / "fewshot" / "ecommerce_examples.json")
    (D / "data" / "prompts").mkdir(parents=True)
    shutil.copy2(R / "data" / "prompts" / "sql_generator_v1.3.txt", D / "data" / "prompts" / "sql_generator_v1.3.txt")
    (D / "db").mkdir(parents=True)
    shutil.copy2(R / "db" / "ecommerce.db", D / "db" / "ecommerce.db")
    shutil.copytree(R / "evaluation", D / "evaluation", ignore=ignore_py)
    (D / "scripts").mkdir(parents=True)
    for f in ["check_env.py", "generate_data.py", "init_db.py", "init_auth_db.py",
              "run_eval.py", "validate_eval_dataset.py", "validate_eval_batch.py",
              "validate_fewshot_dataset.py", "check_benchmark_leakage.py"]:
        shutil.copy2(R / "scripts" / f, D / "scripts" / f)
    for f in ["requirements.txt", "requirements-lock.txt", ".env.example", "README.md"]:
        shutil.copy2(R / f, D / f)

    # ---------- 06_历史归档 ----------
    D = P / "06_历史归档"
    HE = D / "历史评测实验"
    for d in ["task36_real_e2e", "task38_phase1", "task38_phase2", "task39"]:
        cp(R / "reports" / "eval" / d, HE / d)
    cp(R / "reports" / "e2e", HE / "e2e")
    HT = D / "历史任务报告"
    task_files = ["task24_documentation_completion.md", "task26_ppt_completion.md",
                  "task27_defense_materials_completion.md", "task28_final_delivery.md",
                  "REPOSITORY_RECOVERY_PHASE_2C.md", "REPOSITORY_RECOVERY_PHASE_2E.md",
                  "WORKBUDDY_HANDOVER_REPORT.md",
                  "task36_provider_and_e2e_benchmark.md", "task36_provider_and_e2e_benchmark.json",
                  "task36_provider_failure_audit.md", "task36_real_e2e_result.md",
                  "task36_real_e2e_result.json", "task37_sql_scope_validation.md",
                  "task37_sql_scope_validation.json", "task38_entity_constraint.md",
                  "task38_entity_constraint.json", "task39_local_llm_e2e.md",
                  "task39_local_llm_e2e.json", "task39_local_llm_e2e_smoke.json",
                  "task39_local_llm_e2e_smoke_qwen3vl.json", "task39_local_screen_ctx8192.json",
                  "task39_real_e2e_performance_gate.md", "task39_real_e2e_performance_gate.json",
                  "task44_sqlgen_semantic_rules.md", "task44_sqlgen_semantic_rules.json",
                  "task45_semantic_contract_validation.md", "task46_e9_e11.md",
                  "task47_e11_trigger_validation.md", "task48_e11_scope_fix.md",
                  "task49_e11_full_trigger_revalidation.md",
                  "task36_provider_and_e2e_benchmark.json"]
    for f in dict.fromkeys(task_files):
        cp(R / "reports" / f, HT / f)
    OP = D / "旧版PPT"
    cp(R / "reports" / "_archive_pptx", OP / "_archive_pptx")
    for f in ["goal.fill-plan.json", "goal.part-01.fill-plan.json", "goal.part-02.fill-plan.json",
              "goal.part-03.fill-plan.json", "goal.part-01.json", "goal.part-02.json",
              "goal.part-03.json"]:
        cp(R / "reports" / "task26_ppt" / f, OP / "源工程构建中间件" / f)
    cp(R / "reports" / "task26_ppt" / "qa2", OP / "QA渲染记录" / "qa2")
    cp(R / "reports" / "task26_ppt" / "qa3", OP / "QA渲染记录" / "qa3")
    LK = D / "废弃_泄漏版本"
    LK.mkdir(parents=True, exist_ok=True)
    for f in ["ecommerce_examples_v1_leaky.json", "ecommerce_examples_v2_leaky.json"]:
        cp(R / "data" / "fewshot" / f, LK / f)
    cp(R / "_task36", D / "未采用资料_task36")

    print("ASSEMBLE DONE")
    print("PKG =", PKG)


if __name__ == "__main__":
    main()
