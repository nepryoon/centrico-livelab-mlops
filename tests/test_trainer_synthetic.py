import json
import os
import subprocess
import sys
import tempfile


def test_trainer_synthetic_produces_artifacts():
    with tempfile.TemporaryDirectory() as td:
        cmd = [
            sys.executable,
            "services/trainer/app/train.py",
            "--synthetic",
            "--n-samples",
            "400",
            "--artifact-dir",
            td,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + "\n" + r.stderr

        metrics_path = os.path.join(td, "metrics.json")
        meta_path = os.path.join(td, "metadata.json")
        model_path = os.path.join(td, "model.joblib")

        assert os.path.exists(metrics_path)
        assert os.path.exists(meta_path)
        assert os.path.exists(model_path)

        with open(metrics_path) as f:
            m = json.load(f)

        # Quality gate baseline for synthetic data
        assert m["f1"] >= 0.60
