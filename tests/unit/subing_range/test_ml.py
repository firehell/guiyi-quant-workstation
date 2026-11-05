import importlib.util
import unittest
import numpy as np
from scripts.research.regime_ml_core import fold_masks, product_weights, metrics


class MLCoreTests(unittest.TestCase):
    def test_validation_purges_crossing_input_window(self):
        data = dict(
            owned=np.array([1, 1, 1, 0], dtype=bool),
            eligible=np.array([1, 1, 1, 1], dtype=bool),
            day=np.array([20240101, 20240201, 20240301, 20240301]),
            start_day=np.array([20231201, 20240101, 20240201, 20240201]),
        )
        train, val = fold_masks(
            data,
            dict(
                train_through="2024-01-31",
                validation_from="2024-02-01",
                validation_through="2024-03-31",
            ),
        )
        np.testing.assert_array_equal(train, [True, False, False, False])
        np.testing.assert_array_equal(val, [False, False, True, False])

    def test_product_weights_are_equal_mass(self):
        p = np.array([1] * 100 + [2] * 10 + [3] * 2)
        w = product_weights(p)
        self.assertAlmostEqual(w[p == 1].sum(), w[p == 2].sum())
        self.assertAlmostEqual(w[p == 2].sum(), w[p == 3].sum())

    def test_metrics_do_not_bridge_segment_or_removed_rows(self):
        d = dict(
            label=np.tile([0, 1, 2], 20),
            product=np.zeros(60, dtype=int),
            segment=np.repeat([0, 1], 30),
        )
        idx = np.arange(60)
        p = np.repeat([0, 1], 30)
        m = metrics(d, idx, p)
        self.assertEqual(m["switches"], 0)
        p = np.tile([0, 1], 30)
        idx = np.arange(0, 60, 2)
        self.assertEqual(metrics(d, idx, p[idx])["switches"], 0)


@unittest.skipUnless(
    importlib.util.find_spec("torch"), "isolated ML environment required"
)
class TCNTests(unittest.TestCase):
    def test_causality_batch_and_serialization(self):
        import torch
        import io
        from scripts.research.regime_ml_train import CausalTCN, tabular

        torch.set_num_threads(2)
        torch.manual_seed(17)
        model = CausalTCN(10).eval()
        x = torch.randn(3, 96, 10)
        with torch.no_grad():
            full = model.sequence(x)
            prefix = model.sequence(x[:, :64])
            torch.testing.assert_close(full[:, :64], prefix)
            altered = x.clone()
            altered[:, 64:] = 10000
            torch.testing.assert_close(model.sequence(altered)[:, :64], prefix)
            torch.testing.assert_close(model(x[:, :64]), prefix[:, -1])
            for i in range(3):
                torch.testing.assert_close(model(x[i : i + 1, :64])[0], prefix[i, -1])
            stream = io.BytesIO()
            torch.save(model.state_dict(), stream)
            stream.seek(0)
            restored = CausalTCN(10)
            restored.load_state_dict(torch.load(stream, weights_only=True))
            restored.eval()
            torch.testing.assert_close(restored(x), model(x))
        values = np.arange(1000, dtype="float32").reshape(100, 10)
        got = tabular(values, np.array([63, 90]))
        changed = values.copy()
        changed[91:] = 1e9
        np.testing.assert_array_equal(got, tabular(changed, np.array([63, 90])))


class EvaluationRegressionTests(unittest.TestCase):
    def test_delay_cannot_cross_segment(self):
        d = dict(
            label=np.array([0, 1, 1, 1, 1, 1]),
            product=np.zeros(6, dtype=int),
            segment=np.array([1, 1, 1, 1, 2, 2]),
        )
        m = metrics(d, np.arange(6), np.array([0, 0, 0, 0, 1, 1]))
        self.assertEqual(m["trend_events"], 1)
        self.assertEqual(m["trend_missed"], 1)
        self.assertEqual(m["trend_miss_rate"], 1.0)
        self.assertIsNone(m["trend_delay_median"])

    def test_switch_rates_equal_product_weight(self):
        d = dict(
            label=np.zeros(103, dtype=int),
            product=np.array([0] * 101 + [1] * 2),
            segment=np.array([0] * 101 + [1] * 2),
        )
        prediction = np.array([0] * 102 + [1])
        self.assertEqual(
            metrics(d, np.arange(103), prediction)["switches_per_100"], 50.0
        )


class PairedDelayTests(unittest.TestCase):
    def test_dropped_baseline_event_cannot_improve_delay_gate(self):
        from scripts.research.regime_ml_core import gate

        data = dict(
            label=np.array([0, 1, 1, 1, 1, 1]),
            product=np.zeros(6, dtype=int),
            segment=np.zeros(6, dtype=int),
        )
        base = metrics(data, np.arange(6), np.array([0, 0, 1, 1, 1, 1]))
        trial = metrics(data, np.arange(6), np.zeros(6, dtype=int))
        result = gate(base, trial)
        self.assertTrue(result["baseline_detected_event_dropped"])
        self.assertFalse(result["checks"]["delay"])
        self.assertFalse(result["checks"]["misses"])


class ArtifactValidationTests(unittest.TestCase):
    def test_wrong_fold_predictions_are_rejected(self):
        from scripts.research.regime_ml_manual import validate_fold_prediction

        data = dict(
            owned=np.ones(3, dtype=bool),
            eligible=np.ones(3, dtype=bool),
            day=np.array([20240101, 20240201, 20240301]),
            start_day=np.array([20231201, 20240101, 20240201]),
        )
        fold = dict(
            train_through="2024-01-31",
            validation_from="2024-02-01",
            validation_through="2024-03-31",
        )
        validate_fold_prediction(data, fold, np.array([2]), np.array([1]))
        with self.assertRaises(ValueError):
            validate_fold_prediction(data, fold, np.array([1, 2]), np.array([1, 1]))
        with self.assertRaises(ValueError):
            validate_fold_prediction(data, fold, np.array([2]), np.array([-1]))

    def test_paired_block_bootstrap_identical_models_have_zero_delta(self):
        from scripts.research.regime_ml_uncertainty import paired_blocks

        y = np.tile([0, 1, 2], 100)
        data = dict(
            label=y,
            baseline=y,
            product=np.repeat(np.arange(10), 30),
            day=np.tile(np.repeat([20240101, 20240201, 20240301], 10), 10),
        )
        r = paired_blocks(data, np.arange(300), y, repetitions=20)
        self.assertEqual(r["point_delta"], 0.0)
        self.assertEqual(r["interval95"], [0.0, 0.0])


class TrainingIdentityTests(unittest.TestCase):
    def test_wrong_training_source_or_test_role_is_rejected(self):
        import json
        import tempfile
        from pathlib import Path
        from scripts.research.regime_ml_manual import validate_training_protocol

        manifest = dict(
            role="DEVELOPMENT_ONLY",
            sealed_test_evaluated=False,
            source_dataset_id="frozen",
        )
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for protocol in (
                dict(source="other", test_evaluated=False),
                dict(source="frozen", test_evaluated=True),
            ):
                (folder / "protocol.json").write_text(json.dumps(protocol))
                with self.assertRaises(ValueError):
                    validate_training_protocol(manifest, folder)
            (folder / "protocol.json").write_text(
                json.dumps(dict(source="frozen", test_evaluated=False))
            )
            validate_training_protocol(manifest, folder)
            with self.assertRaises(ValueError):
                validate_training_protocol(
                    dict(manifest, sealed_test_evaluated=True), folder
                )
