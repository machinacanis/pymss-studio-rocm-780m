from __future__ import annotations

import os
import unittest

if __package__:
    from . import _bootstrap as _worker_test_bootstrap
else:
    import _bootstrap as _worker_test_bootstrap

import worker_vram


class VramBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        worker_vram.reset_vram_budget_for_tests()

    def test_large_config_chunk_is_capped_and_overlap_scaled(self) -> None:
        params, notes = worker_vram.fit_inference_budget(
            {"overlap_size": 441000},
            model_type="bs_roformer",
            config_chunk=882000,
            config_overlap=None,
            config_batch=1,
            chunk_cap=worker_vram.SAFE_CHUNK_SAMPLES,
        )
        self.assertEqual(params["chunk_size"], 352800)
        self.assertEqual(params["overlap_size"], 176400)
        self.assertEqual(params["stem_batch_size"], 1)
        self.assertTrue(any(note.startswith("chunk_size") for note in notes))

    def test_config_overlap_is_injected_only_when_the_chunk_is_capped(self) -> None:
        params, notes = worker_vram.fit_inference_budget(
            {},
            model_type="bs_roformer",
            config_chunk=882000,
            config_overlap=441000,
            config_batch=4,
            chunk_cap=352800,
        )
        self.assertEqual(params["chunk_size"], 352800)
        self.assertEqual(params["overlap_size"], 176400)
        self.assertEqual(params["batch_size"], 1)
        self.assertIn("batch_size 4 -> 1", notes)

    def test_small_explicit_chunk_keeps_a_valid_overlap(self) -> None:
        params, notes = worker_vram.fit_inference_budget(
            {"chunk_size": 262144, "overlap_size": 12000, "batch_size": 1},
            model_type="bs_roformer",
            config_chunk=882000,
            config_overlap=441000,
            config_batch=4,
            chunk_cap=352800,
        )
        self.assertEqual(params["chunk_size"], 262144)
        self.assertEqual(params["overlap_size"], 12000)
        self.assertEqual(params["batch_size"], 1)
        self.assertFalse(any(note.startswith("chunk_size") for note in notes))
        self.assertFalse(any(note.startswith("overlap_size") for note in notes))

    def test_explicit_overlap_is_scaled_with_the_capped_chunk(self) -> None:
        params, _notes = worker_vram.fit_inference_budget(
            {"chunk_size": 500000, "overlap_size": 400000, "batch_size": 4},
            model_type="mel_band_roformer",
            config_chunk=None,
            config_overlap=None,
            config_batch=None,
            chunk_cap=352800,
        )
        self.assertEqual(params["chunk_size"], 352800)
        self.assertEqual(params["overlap_size"], 400000 * 352800 // 500000)
        self.assertEqual(params["batch_size"], 1)

    def test_second_fit_does_not_scale_overlap_again(self) -> None:
        once, _notes = worker_vram.fit_inference_budget(
            {"overlap_size": 441000},
            model_type="bs_roformer",
            config_chunk=882000,
            config_overlap=441000,
            config_batch=2,
            chunk_cap=352800,
        )
        twice, notes = worker_vram.fit_inference_budget(
            once,
            model_type="bs_roformer",
            config_chunk=882000,
            config_overlap=441000,
            config_batch=2,
            chunk_cap=352800,
        )
        self.assertEqual(twice["chunk_size"], 352800)
        self.assertEqual(twice["overlap_size"], 176400)
        self.assertEqual(notes, [])

    def test_vr_is_not_given_an_mss_chunk(self) -> None:
        params, notes = worker_vram.fit_inference_budget(
            {"batch_size": 2, "window_size": 512},
            model_type="vr",
            config_chunk=882000,
            config_overlap=100,
            config_batch=2,
            chunk_cap=352800,
        )
        self.assertNotIn("chunk_size", params)
        self.assertEqual(params["batch_size"], 2)
        self.assertEqual(params["window_size"], 512)
        self.assertEqual(notes, [])

    def test_gpu_devices_take_the_budget_and_cpu_does_not(self) -> None:
        self.assertTrue(worker_vram.gpu_budget_applies("auto"))
        self.assertTrue(worker_vram.gpu_budget_applies("cuda"))
        self.assertTrue(worker_vram.gpu_budget_applies("cuda:0"))
        self.assertTrue(worker_vram.gpu_budget_applies("rocm"))
        self.assertFalse(worker_vram.gpu_budget_applies("cpu"))
        self.assertFalse(worker_vram.gpu_budget_applies("mps"))

    def test_memory_fraction_leaves_room_for_the_failed_spike(self) -> None:
        total = int(14.43 * 1024 ** 3)
        fraction = worker_vram.memory_fraction(total)
        reserved = fraction * total
        self.assertLess(reserved, total - int(1.63 * 1024 ** 3))
        self.assertGreater(fraction, 0.5)

    def test_guard_clamps_a_gpu_separator_and_ignores_a_stub_package(self) -> None:
        import sys
        import types
        from unittest import mock

        class Separator:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

        package = types.ModuleType("pymss")
        package.MSSeparator = Separator
        with mock.patch.dict(sys.modules, {"pymss": package}):
            worker_vram.install_separator_vram_guard()
            separator = Separator(
                model_type="bs_roformer",
                device="cuda",
                inference_params={"chunk_size": 882000, "overlap_size": 441000, "batch_size": 4},
            )
        self.assertEqual(separator.kwargs["inference_params"]["chunk_size"], 352800)
        self.assertEqual(separator.kwargs["inference_params"]["overlap_size"], 176400)
        self.assertEqual(separator.kwargs["inference_params"]["batch_size"], 1)

        stub = types.ModuleType("pymss")
        with mock.patch.dict(sys.modules, {"pymss": stub}):
            worker_vram.install_separator_vram_guard()

    def test_oom_retry_shrinks_until_the_floor(self) -> None:
        self.assertEqual(worker_vram.note_oom_retry(), 176400)
        self.assertEqual(worker_vram.note_oom_retry(), 88200)
        self.assertIsNone(worker_vram.note_oom_retry())
        self.assertTrue(worker_vram.is_cuda_oom(RuntimeError(
            "CUDA out of memory. Tried to allocate 1.63 GiB."
        )))
        self.assertFalse(worker_vram.is_cuda_oom(RuntimeError("model file missing")))

    def test_allocator_env_merges_without_duplicating_flags(self) -> None:
        previous_cuda = os.environ.get("PYTORCH_CUDA_ALLOC_CONF")
        previous_hip = os.environ.get("PYTORCH_HIP_ALLOC_CONF")
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"
        os.environ.pop("PYTORCH_HIP_ALLOC_CONF", None)
        try:
            worker_vram.configure_allocator_env()
            value = os.environ["PYTORCH_CUDA_ALLOC_CONF"]
            self.assertIn("max_split_size_mb:128", value)
            self.assertIn("expandable_segments:True", value)
            self.assertIn("garbage_collection_threshold:0.6", value)
            self.assertEqual(os.environ["PYTORCH_HIP_ALLOC_CONF"], value)
            worker_vram.configure_allocator_env()
            self.assertEqual(os.environ["PYTORCH_CUDA_ALLOC_CONF"].count("expandable_segments"), 1)
        finally:
            if previous_cuda is None:
                os.environ.pop("PYTORCH_CUDA_ALLOC_CONF", None)
            else:
                os.environ["PYTORCH_CUDA_ALLOC_CONF"] = previous_cuda
            if previous_hip is None:
                os.environ.pop("PYTORCH_HIP_ALLOC_CONF", None)
            else:
                os.environ["PYTORCH_HIP_ALLOC_CONF"] = previous_hip


if __name__ == "__main__":
    unittest.main()
