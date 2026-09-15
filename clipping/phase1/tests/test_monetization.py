"""
Unit tests for monetization module

Tests each component independently:
- HookStrengthDetector
- VVSAPredictor
- RetentionCurveOptimizer
- OptimalLengthCalculator
- SeriesDetector
- MonetizationScorer
"""

import unittest
from clipping.phase1.monetization import (
    HookStrengthDetector,
    VVSAPredictor,
    RetentionCurveOptimizer,
    OptimalLengthCalculator,
    SeriesDetector,
    MonetizationScorer
)


class TestHookStrengthDetector(unittest.TestCase):
    """Test opening hook detection."""

    def test_strong_hook_with_command(self):
        """Strong hook starts with action word."""
        text = "Stop training LLMs like this"
        score, reason = HookStrengthDetector.detect_hook_strength(text)
        self.assertGreater(score, 0.65, "Command-based hooks should score high")

    def test_strong_hook_with_question(self):
        """Questions are strong hooks."""
        text = "Why do most people get this wrong?"
        score, reason = HookStrengthDetector.detect_hook_strength(text, is_question=True)
        self.assertGreater(score, 0.65, "Questions should score high")

    def test_weak_hook_with_intro(self):
        """Weak hook with generic intro."""
        text = "Hey everyone, today we're going to talk about..."
        score, reason = HookStrengthDetector.detect_hook_strength(text)
        self.assertLess(score, 0.55, "Generic intro should score low")

    def test_strong_hook_with_urgency(self):
        """Urgency words create strong hooks."""
        text = "This one mistake kills your Python scripts"
        score, reason = HookStrengthDetector.detect_hook_strength(text)
        self.assertGreater(score, 0.65)

    def test_hook_with_exclamation(self):
        """Exclamation marks boost hook strength."""
        text = "Never do this again!"
        score, reason = HookStrengthDetector.detect_hook_strength(text)
        self.assertIn("Exclamation", reason)

    def test_optimal_hook_length(self):
        """Hook should be 8-15 words."""
        text = "This is the optimal length hook for maximum retention"
        score, reason = HookStrengthDetector.detect_hook_strength(text)
        self.assertIn("Optimal length", reason)

    def test_batch_processing(self):
        """Batch detect hook strength for multiple segments."""
        segments = [
            {"text": "Stop doing this"},
            {"text": "Hey guys welcome to my channel"},
            {"text": "What if I told you"},
        ]
        result = HookStrengthDetector.batch_detect(segments)
        self.assertEqual(len(result), 3)
        self.assertGreater(result[0]['hook_score'], result[1]['hook_score'], "Stop > Hey")
        self.assertGreater(result[2]['hook_score'], result[1]['hook_score'], "Question > Generic")


class TestVVSAPredictor(unittest.TestCase):
    """Test swipe-away resistance prediction."""

    def test_vvsa_with_strong_hook(self):
        """Strong hook reduces swipe-away."""
        text = "This one trick will blow your mind"
        score = VVSAPredictor.predict_vvsa(text, has_motion=True, has_face=True)
        self.assertGreater(score, 0.7, "Should have high VVSA with strong hook + motion + face")

    def test_vvsa_without_hook(self):
        """Weak hook increases swipe-away."""
        text = "So like um let me tell you something"
        score = VVSAPredictor.predict_vvsa(text, has_motion=False, has_face=False)
        self.assertLess(score, 0.6, "Should have low VVSA with weak hook")

    def test_vvsa_with_face(self):
        """Face presence boosts VVSA."""
        text = "Wait hold on"
        score_with_face = VVSAPredictor.predict_vvsa(text, has_face=True)
        score_without_face = VVSAPredictor.predict_vvsa(text, has_face=False)
        self.assertGreater(score_with_face, score_without_face, "Face should boost VVSA")

    def test_vvsa_with_motion(self):
        """Motion in first 3s boosts VVSA."""
        text = "Watch this"
        score_with_motion = VVSAPredictor.predict_vvsa(text, has_motion=True)
        score_without_motion = VVSAPredictor.predict_vvsa(text, has_motion=False)
        self.assertGreater(score_with_motion, score_without_motion, "Motion should boost VVSA")

    def test_vvsa_curiosity_phrases(self):
        """Curiosity phrases boost VVSA."""
        text = "But here's the thing"
        score = VVSAPredictor.predict_vvsa(text)
        self.assertGreater(score, 0.5, "Curiosity phrases should boost VVSA")

    def test_vvsa_unknown_face_is_neutral(self):
        """has_face=None (unknown) scores strictly between True and False."""
        text = "Wait hold on"
        score_true = VVSAPredictor.predict_vvsa(text, has_face=True)
        score_none = VVSAPredictor.predict_vvsa(text, has_face=None)
        score_false = VVSAPredictor.predict_vvsa(text, has_face=False)
        self.assertGreater(score_true, score_none, "Unknown should score below confirmed True")
        self.assertGreater(score_none, score_false, "Unknown should score above confirmed False")

    def test_vvsa_unknown_motion_is_neutral(self):
        """has_motion=None (unknown) scores strictly between True and False."""
        text = "Watch this"
        score_true = VVSAPredictor.predict_vvsa(text, has_motion=True)
        score_none = VVSAPredictor.predict_vvsa(text, has_motion=None)
        score_false = VVSAPredictor.predict_vvsa(text, has_motion=False)
        self.assertGreater(score_true, score_none, "Unknown should score below confirmed True")
        self.assertGreater(score_none, score_false, "Unknown should score above confirmed False")

    def test_vvsa_none_not_equal_false(self):
        """Unknown (None) must NOT be silently treated as confirmed False."""
        text = "This one trick will blow your mind"
        score_none = VVSAPredictor.predict_vvsa(text, has_face=None, has_motion=None)
        score_false = VVSAPredictor.predict_vvsa(text, has_face=False, has_motion=False)
        self.assertNotEqual(score_none, score_false, "None must score differently than False")
        self.assertGreater(score_none, score_false, "Unknown should not incur the False penalty")

    def test_vvsa_defaults_to_unknown(self):
        """Omitting has_face/has_motion entirely defaults to None (unknown), not False."""
        text = "This one trick will blow your mind"
        score_default = VVSAPredictor.predict_vvsa(text)
        score_explicit_none = VVSAPredictor.predict_vvsa(text, has_face=None, has_motion=None)
        score_false = VVSAPredictor.predict_vvsa(text, has_face=False, has_motion=False)
        self.assertEqual(score_default, score_explicit_none, "Default omission should equal explicit None")
        self.assertNotEqual(score_default, score_false, "Default must not equal confirmed False")


class TestRetentionCurveOptimizer(unittest.TestCase):
    """Test retention prediction."""

    def test_retention_optimal_length(self):
        """25-40s duration optimizes retention."""
        score_30s = RetentionCurveOptimizer.predict_retention(30, has_good_hook=True, has_payoff=True)
        score_60s = RetentionCurveOptimizer.predict_retention(60, has_good_hook=True, has_payoff=True)
        self.assertGreater(score_30s, score_60s, "30s should retain better than 60s")

    def test_retention_with_good_structure(self):
        """Good structure improves retention."""
        score_good = RetentionCurveOptimizer.predict_retention(35, has_good_hook=True, has_payoff=True, has_cta=True)
        score_bad = RetentionCurveOptimizer.predict_retention(35, has_good_hook=False, has_payoff=False, has_cta=False)
        self.assertGreater(score_good, score_bad, "Good structure should improve retention")

    def test_retention_too_long(self):
        """Long videos hurt retention."""
        score_30s = RetentionCurveOptimizer.predict_retention(30)
        score_90s = RetentionCurveOptimizer.predict_retention(90)
        self.assertGreater(score_30s, score_90s, "30s should retain better than 90s")

    def test_retention_too_short(self):
        """Very short videos also have lower retention %."""
        score_10s = RetentionCurveOptimizer.predict_retention(10)
        score_30s = RetentionCurveOptimizer.predict_retention(30)
        # Note: <15s still gets watched, but % watched is lower
        self.assertLess(score_10s, score_30s, "10s should have lower retention % than 30s")


class TestOptimalLengthCalculator(unittest.TestCase):
    """Test length optimization."""

    def test_optimal_length_range(self):
        """25-40s is optimal."""
        length, reason = OptimalLengthCalculator.calculate_optimal_length(32)
        self.assertEqual(length, 32)
        self.assertIn("Optimal", reason)

    def test_length_too_short(self):
        """Short videos need extension."""
        length, reason = OptimalLengthCalculator.calculate_optimal_length(15)
        self.assertIsNotNone(length)
        self.assertIn("short", reason.lower())

    def test_length_too_long(self):
        """Long videos need splitting."""
        reason = OptimalLengthCalculator.calculate_optimal_length(75)[1]
        self.assertIn("split", reason.lower())

    def test_suggest_split(self):
        """Can suggest how to split long videos."""
        clip1, clip2 = OptimalLengthCalculator.suggest_split(70)
        self.assertIsNotNone(clip1)
        self.assertIsNotNone(clip2)
        self.assertGreater(clip1, 0)
        self.assertGreater(clip2, 0)

    def test_suggest_split_already_good(self):
        """Don't split if already good length."""
        result = OptimalLengthCalculator.suggest_split(35)
        self.assertIsNone(result, "35s should not be split")


class TestSeriesDetector(unittest.TestCase):
    """Test series detection."""

    def test_detect_episode_series(self):
        """Detect episodic content."""
        text = "Python Tips #1: List Comprehensions"
        potential, series_type = SeriesDetector.detect_series_potential(text)
        self.assertEqual(potential, "high")

    def test_detect_before_after(self):
        """Detect before/after series."""
        text = "Before: Slow code | After: Lightning fast"
        potential, series_type = SeriesDetector.detect_series_potential(text)
        self.assertIn(potential, ["high", "medium"])

    def test_detect_list_format(self):
        """Detect list/countdown formats."""
        text = "3 Ways to Optimize Your React App"
        potential, series_type = SeriesDetector.detect_series_potential(text)
        self.assertIn(potential, ["high", "medium"])

    def test_non_series_content(self):
        """One-off content scores low."""
        text = "Random thought about databases"
        potential, _ = SeriesDetector.detect_series_potential(text)
        self.assertEqual(potential, "low")

    def test_expandable_topic(self):
        """Expandable topics score medium."""
        text = "Why Python is amazing"
        potential, _ = SeriesDetector.detect_series_potential(text)
        self.assertIn(potential, ["high", "medium"])


class TestMonetizationScorer(unittest.TestCase):
    """Test overall monetization scoring."""

    def test_high_monetization_clip(self):
        """Strong clip scores high."""
        segment = {
            'text': "Stop training LLMs like this - here's the right way",
            'start': 10.0,
            'end': 42.0  # 32s - optimal
        }
        metrics = MonetizationScorer.score_clip(segment)
        self.assertGreater(metrics.monetization_score, 0.65, "Strong clip should score high")
        self.assertGreater(metrics.hook_strength, 0.6)
        self.assertGreater(metrics.vvsa_score, 0.55, "VVSA should be above neutral")

    def test_low_monetization_clip(self):
        """Weak clip scores low."""
        segment = {
            'text': "So like uh you know just rambling here",
            'start': 0.0,
            'end': 120.0  # 120s - too long
        }
        metrics = MonetizationScorer.score_clip(segment)
        self.assertLess(metrics.monetization_score, 0.55, "Weak clip should score low")

    def test_monetization_with_series_potential(self):
        """Series potential is detected."""
        segment = {
            'text': "Python Tip #1: Use list comprehensions",
            'start': 0.0,
            'end': 30.0
        }
        metrics = MonetizationScorer.score_clip(segment)
        self.assertEqual(metrics.series_potential, "high")

    def test_recommendations_generated(self):
        """Recommendations are provided."""
        segment = {
            'text': "Hey everyone",
            'start': 0.0,
            'end': 90.0  # Too long, weak hook
        }
        metrics = MonetizationScorer.score_clip(segment)
        self.assertGreater(len(metrics.recommendations), 0)

    def test_score_clip_defaults_to_unknown(self):
        """Omitting has_face/has_motion leaves them as None (unknown) in the result."""
        segment = {'text': "Stop doing this", 'start': 0.0, 'end': 30.0}
        metrics = MonetizationScorer.score_clip(segment)
        self.assertIsNone(metrics.has_face)
        self.assertIsNone(metrics.has_motion)

    def test_score_clip_threads_through_explicit_values(self):
        """Explicit has_face/has_motion kwargs are reflected in the result, not overridden."""
        segment = {'text': "Stop doing this", 'start': 0.0, 'end': 30.0}
        metrics = MonetizationScorer.score_clip(segment, has_face=True, has_motion=False)
        self.assertTrue(metrics.has_face)
        self.assertFalse(metrics.has_motion)

    def test_score_clip_recommends_data_completeness_note_when_unknown(self):
        """The 'unavailable' note appears when face/motion data is unknown."""
        segment = {'text': "Stop doing this", 'start': 0.0, 'end': 30.0}
        metrics = MonetizationScorer.score_clip(segment)
        self.assertTrue(
            any("unavailable" in r for r in metrics.recommendations),
            "Should note that face/motion data is unavailable"
        )

    def test_score_clip_no_data_completeness_note_when_known(self):
        """The 'unavailable' note does NOT appear when both signals are provided."""
        segment = {'text': "Stop doing this", 'start': 0.0, 'end': 30.0}
        metrics = MonetizationScorer.score_clip(segment, has_face=True, has_motion=True)
        self.assertFalse(
            any("unavailable" in r for r in metrics.recommendations),
            "Should not note unavailability when both signals are known"
        )

    def test_batch_scoring(self):
        """Can score multiple segments."""
        segments = [
            {'text': "Stop doing this", 'start': 0, 'end': 30},
            {'text': "Hey guys", 'start': 0, 'end': 60},
            {'text': "Watch this", 'start': 0, 'end': 35},
        ]
        scored = MonetizationScorer.batch_score(segments)
        self.assertEqual(len(scored), 3)
        self.assertGreater(scored[0]['monetization']['monetization_score'],
                          scored[1]['monetization']['monetization_score'])


class TestIntegration(unittest.TestCase):
    """Integration tests combining multiple components."""

    def test_full_clip_analysis_pipeline(self):
        """Full pipeline: detect hook → VVSA → retention → series."""
        # Realistic YouTube Shorts clip
        segment = {
            'text': "This one Python mistake will crash your code. Here's how to fix it",
            'start': 15.0,
            'end': 47.0  # 32 seconds
        }

        # Full analysis
        metrics = MonetizationScorer.score_clip(segment)

        # Check expectations (realistic thresholds)
        self.assertGreater(metrics.hook_strength, 0.6, "Should have strong hook")
        self.assertGreater(metrics.vvsa_score, 0.55, "Should have decent VVSA")
        self.assertGreater(metrics.retention_score, 0.65, "Should predict decent retention")
        self.assertGreater(metrics.monetization_score, 0.6, "Should have good monetization potential")

    def test_poor_clip_detection(self):
        """Detect clips that won't monetize well."""
        segment = {
            'text': "Um, so like, let me think about this for a second",
            'start': 0.0,
            'end': 95.0  # Too long
        }

        metrics = MonetizationScorer.score_clip(segment)

        self.assertLess(metrics.hook_strength, 0.5, "Should detect weak hook")
        self.assertLess(metrics.vvsa_score, 0.65, "Should predict high swipe-away")
        self.assertLess(metrics.monetization_score, 0.55, "Should flag low monetization")
        self.assertIn("split", str(metrics.recommendations).lower(), "Should suggest splitting")

    def test_series_identification_integration(self):
        """Detect and recommend series."""
        segments = [
            {'text': "Python Tips #1: List Comprehensions", 'start': 0, 'end': 30},
            {'text': "Python Tips #2: Decorators", 'start': 0, 'end': 32},
            {'text': "Python Tips #3: Context Managers", 'start': 0, 'end': 28},
        ]

        scored = MonetizationScorer.batch_score(segments)

        for seg in scored:
            self.assertEqual(seg['monetization']['series_potential'], 'high')


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_empty_text(self):
        """Handle empty text."""
        score, reason = HookStrengthDetector.detect_hook_strength("")
        self.assertEqual(score, 0.0)

    def test_very_short_clip(self):
        """Handle very short clips."""
        metrics = MonetizationScorer.score_clip({
            'text': "Go",
            'start': 0,
            'end': 2
        })
        self.assertIsNotNone(metrics)

    def test_very_long_clip(self):
        """Handle very long clips."""
        metrics = MonetizationScorer.score_clip({
            'text': "This is a very long segment " * 50,
            'start': 0,
            'end': 300
        })
        self.assertIsNotNone(metrics)
        self.assertIn("split", str(metrics.recommendations).lower())

    def test_special_characters(self):
        """Handle special characters."""
        text = "Don't skip this! 🔥 #python #ai"
        score, _ = HookStrengthDetector.detect_hook_strength(text)
        self.assertGreater(score, 0.0)


def run_tests():
    """Run all tests and print summary."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestHookStrengthDetector))
    suite.addTests(loader.loadTestsFromTestCase(TestVVSAPredictor))
    suite.addTests(loader.loadTestsFromTestCase(TestRetentionCurveOptimizer))
    suite.addTests(loader.loadTestsFromTestCase(TestOptimalLengthCalculator))
    suite.addTests(loader.loadTestsFromTestCase(TestSeriesDetector))
    suite.addTests(loader.loadTestsFromTestCase(TestMonetizationScorer))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failed: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 70)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
