from __future__ import annotations

import copy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import yaml

if __package__:
    from . import _bootstrap as _worker_test_bootstrap
else:
    import _bootstrap as _worker_test_bootstrap

import worker_infer
import worker_models


class InferenceParameterCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config_path = self.root / "model.yaml"
        self.config = {
            "audio": {"chunk_size": 588800},
            "inference": {"chunk_size": 882000, "num_overlap": 2, "batch_size": 1},
        }
        self.entry = types.SimpleNamespace(model_type="bs_roformer")
        self.pymss_config = types.ModuleType("pymss.config")
        self.pymss_config.load_config = lambda path: yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.pymss_config.to_plain = lambda config: config
        pymss = types.ModuleType("pymss")
        pymss.config = self.pymss_config
        modules = mock.patch.dict(sys.modules, {"pymss": pymss, "pymss.config": self.pymss_config})
        modules.start()
        self.addCleanup(modules.stop)
        self.write_config()

    def write_config(self) -> None:
        self.config_path.write_text(yaml.safe_dump(self.config), encoding="utf-8")

    def runtime_params(self, params=None, model_type="bs_roformer"):
        return worker_infer._enrich_inference_params_for_model(
            model_type=model_type,
            config_path=str(self.config_path),
            inference_params=params or {},
        )

    def test_model_defaults_prefer_inference_chunk_size(self) -> None:
        defaults = worker_models.resolve_default_inference_params(
            self.entry, self.root / "model.ckpt", self.config_path,
        )
        self.assertEqual(defaults["chunk_size"], 882000)
        self.assertEqual(defaults["num_overlap"], 2)

    def test_separator_receives_overlap_for_the_effective_chunk_size(self) -> None:
        separator_type = mock.Mock()
        resolved = {
            "model_type": "bs_roformer",
            "model_path": str(self.root / "model.ckpt"),
            "config_path": str(self.config_path),
        }
        payload = {
            "model": "bs_roformer", "download": False,
            "output": str(self.root / "output"),
            "inferenceParamsVersion": 2, "inferenceParams": {},
        }
        with (
            mock.patch.object(worker_infer, "_resolve_separator_device", return_value=("cpu", [0], "CPU")),
            mock.patch.object(worker_infer, "_studio_separator_type", return_value=separator_type),
            mock.patch.object(worker_infer, "_resolve_studio_model", return_value=resolved),
            mock.patch.object(worker_infer, "emit"),
        ):
            worker_infer._prepare_separator(
                payload=payload, task_id="separation-1", logger=mock.Mock(), progress_callback=None,
            )

        self.assertEqual(separator_type.call_args.kwargs["inference_params"], {"overlap_size": 441000})
        self.assertEqual(payload["inferenceParams"], {})

    def test_audio_chunk_size_is_used_when_inference_chunk_size_is_missing_or_null(self) -> None:
        for include_null in (False, True):
            with self.subTest(include_null=include_null):
                self.config["inference"].pop("chunk_size", None)
                if include_null:
                    self.config["inference"]["chunk_size"] = None
                self.write_config()
                defaults = worker_models.resolve_default_inference_params(
                    self.entry, self.root / "model.ckpt", self.config_path,
                )
                self.assertEqual(defaults["chunk_size"], 588800)
                self.assertEqual(self.runtime_params(), {"overlap_size": 294400})

    def test_user_chunk_size_and_overlap_count_take_precedence(self) -> None:
        for overrides, expected in (
            ({"chunk_size": 262144}, {"chunk_size": 262144, "overlap_size": 131072}),
            ({"chunk_size": 262144, "num_overlap": 8}, {"chunk_size": 262144, "overlap_size": 229376}),
            ({"num_overlap": 8}, {"overlap_size": 771750}),
            ({"num_overlap": 1}, {"overlap_size": 0}),
        ):
            with self.subTest(overrides=overrides):
                original = copy.deepcopy(overrides)
                self.assertEqual(self.runtime_params(overrides), expected)
                self.assertEqual(overrides, original)

    def test_explicit_overlap_size_is_preserved(self) -> None:
        overrides = {"chunk_size": 262144, "num_overlap": 8, "overlap_size": 12000}
        self.assertEqual(self.runtime_params(overrides), {"chunk_size": 262144, "overlap_size": 12000})

    def test_configured_overlap_size_is_left_to_the_core(self) -> None:
        self.config["inference"]["overlap_size"] = 12000
        self.write_config()
        self.assertEqual(self.runtime_params(), {})
        self.assertEqual(self.runtime_params({"num_overlap": 8}), {"overlap_size": 771750})

    def test_vr_and_apollo_do_not_receive_msst_overlap_conversion(self) -> None:
        for model_type in ("vr", "apollo"):
            with self.subTest(model_type=model_type):
                self.assertEqual(self.runtime_params({"num_overlap": 8}, model_type), {})


if __name__ == "__main__":
    unittest.main()
