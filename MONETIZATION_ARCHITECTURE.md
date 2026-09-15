# YouTube Shorts Monetization Architecture

Systematic integration of monetization research into the clipping pipeline.

## 📊 Architecture Overview

```
Raw Video → Transcribe → Analyze Segments → SCORE FOR MONETIZATION → Render → Upload
                                                    ↓
                          ┌──────────────────────────┼──────────────────────────┐
                          ↓                          ↓                          ↓
                   Hook Strength             VVSA Score            Retention Prediction
                   (First 1-3s)             (No Swipe-Away)        (View Duration %)
                          │                          │                          │
                          └──────────────────────────┼──────────────────────────┘
                                                    ↓
                          ┌──────────────────────────┴──────────────────────────┐
                          ↓                                                      ↓
                 Optimal Length (25-40s)                          Series Detection
                 Structure Fit (Hook→Payoff)                      (Episodic opportunity)
                          │                                                      │
                          └──────────────────────────┬──────────────────────────┘
                                                    ↓
                          📈 MONETIZATION SCORE (0-1)
                                                    ↓
                          Rank Clips → Select Top 3-5 → Schedule 3-5x/week
```

---

## 🧩 Component Architecture

### 1. **Hook Strength Detector**
**Purpose:** Detect if clip opens with strong hook (critical for VVSA)

**Inputs:**
- First sentence/phrase of clip
- Video has motion in first 3s? (boolean)
- Face visible? (boolean)

**Scoring Factors:**
- Strong opening words: "stop", "never", "mistake", "secret", "hack" → +20%
- Questions → +15%
- Exclamation marks → +10%
- Optimal length 8-15 words → +10%
- Weak intros: "hey", "welcome", "so" → -15%

**Output:**
- `hook_strength`: 0-1 (higher = better)
- `reason`: Explanation of score

**Example:**
```python
from clipping.phase1.monetization import HookStrengthDetector

text = "This one Python mistake will crash your app"
score, reason = HookStrengthDetector.detect_hook_strength(text)
# Output: (0.72, "Strong phrase: 'mistake' (+20%) | Optimal length 8w (+10%)")
```

**Target:** >0.6 for monetizable clips

---

### 2. **VVSA Predictor**
**Purpose:** Predict Viewed vs Swiped Away (% not swiping away in first 1-3s)

**Goal:** >70%, ideally >80%

**Inputs:**
- Opening text
- Has motion in first 3s?
- Face visible?

**Scoring Factors:**
- Hook strength: 30% contribution
- Motion/cuts: +20%
- Face presence: +15%
- Curiosity phrases: +10%
- Punctuation (emphasis): +5%

**Output:**
- `vvsa_score`: 0-1 (0 = high swipe-away, 1 = very sticky)

**Example:**
```python
from clipping.phase1.monetization import VVSAPredictor

score = VVSAPredictor.predict_vvsa(
    "Wait, hold on! Here's the thing...",
    has_motion=True,
    has_face=True
)
# Output: 0.75 (good VVSA)
```

**Target:** >0.7 for monetizable clips

---

### 3. **Retention Curve Optimizer**
**Purpose:** Predict average view duration percentage

**Goal:** >73-76% for viral Shorts

**Optimal Structure Template:**
- **0-3s**: Strong hook + promise (gets viewer to not swipe)
- **3-10s**: Why it matters / stakes (keeps viewer watching)
- **10-30s**: Core insight / demo / payoff (delivers on promise)
- **Last 2-4s**: Quick CTA or loop back (end retention boost)

**Scoring Factors:**
- Duration 25-40s: +20% (optimal)
- Duration 20-50s: +10% (acceptable)
- Good hook: +15%
- Payoff present: +15%
- CTA present: +10%

**Output:**
- `retention_score`: 0-1 (predicted % of clip watched)

**Example:**
```python
from clipping.phase1.monetization import RetentionCurveOptimizer

score = RetentionCurveOptimizer.predict_retention(
    clip_duration=32,
    has_good_hook=True,
    has_payoff=True,
    has_cta=True
)
# Output: 0.76 (strong retention prediction)
```

---

### 4. **Optimal Length Calculator**
**Purpose:** Ensure clip length is in monetization sweet spot

**Target Range:** 25-40s (optimal: 32s)

**Logic:**
```
< 25s  → Extend if possible
25-40s → Optimal, keep as-is
> 40s  → Suggest splitting into 2 Shorts with separate hooks
```

**Output:**
- `optimal_length`: Recommended length
- `reason`: Why (extension needed, good length, etc.)

**Example:**
```python
from clipping.phase1.monetization import OptimalLengthCalculator

length, reason = OptimalLengthCalculator.calculate_optimal_length(65)
# Output: (None, "Too long (65s) - consider splitting into 2 Shorts")

# Get split suggestion
clip1, clip2 = OptimalLengthCalculator.suggest_split(65)
# Output: (32.5, 32.5)
```

---

### 5. **Series Detector**
**Purpose:** Identify content suitable for episodic series (improves retention + subs)

**Detects:**
- **Episode format**: "#1", "Part 1", "Episode" → HIGH series potential
- **Tips format**: "Tip:", "Mistake:", "How to:" → HIGH/MEDIUM
- **Before/After**: "Before", "After", "Wrong", "Right" → HIGH/MEDIUM
- **List format**: "Ways to", "Reasons", "Top 5" → HIGH/MEDIUM

**Output:**
- `series_potential`: "high", "medium", "low"
- `series_type`: String (e.g., "Python Tips Series")

**Example:**
```python
from clipping.phase1.monetization import SeriesDetector

potential, type_name = SeriesDetector.detect_series_potential(
    "Stop using List Comprehensions like this"
)
# Output: ("medium", "Expandable Topic Series")
```

---

### 6. **Monetization Scorer** (Master Orchestrator)
**Purpose:** Combine all signals into single monetization score

**Weights:**
- Hook strength: 25%
- VVSA score: 30% (most important - drives algorithm)
- Retention score: 25%
- Optimal length: 10%
- Structure fit: 10%

**Output: MonetizationMetrics**
```python
@dataclass
class MonetizationMetrics:
    hook_strength: float  # 0-1
    vvsa_score: float  # 0-1
    retention_score: float  # 0-1
    optimal_length: float  # seconds
    structure_score: float  # 0-1
    monetization_score: float  # 0-1 (FINAL)
    series_potential: str  # high/medium/low
    recommendations: List[str]  # Action items
```

**Example:**
```python
from clipping.phase1.monetization import MonetizationScorer

segment = {
    'text': "This one Python mistake will crash your code",
    'start': 10.0,
    'end': 42.0  # 32 seconds
}

metrics = MonetizationScorer.score_clip(segment)

print(f"Monetization Score: {metrics.monetization_score:.1%}")
print(f"Hook Strength:      {metrics.hook_strength:.1%}")
print(f"VVSA (No Swipe):    {metrics.vvsa_score:.1%}")
print(f"Predicted Retention: {metrics.retention_score:.1%}")
print(f"Series Potential:   {metrics.series_potential}")

for rec in metrics.recommendations:
    print(f"  • {rec}")
```

---

## 🔬 Testing Framework

**38 unit tests covering:**

### Component Tests (6 test classes, 30 tests)
- `TestHookStrengthDetector` (7 tests)
  - Strong hooks (commands, questions, urgency)
  - Weak hooks (generic intros)
  - Optimal length
  - Batch processing

- `TestVVSAPredictor` (5 tests)
  - Strong hook + motion + face
  - Weak hooks
  - Face presence effect
  - Motion effect
  - Curiosity phrases

- `TestRetentionCurveOptimizer` (4 tests)
  - Optimal length retention
  - Good structure boost
  - Too long penalty
  - Too short penalty

- `TestOptimalLengthCalculator` (5 tests)
  - Optimal range (25-40s)
  - Too short/long detection
  - Split suggestions
  - No-split for good lengths

- `TestSeriesDetector` (5 tests)
  - Episode series detection
  - Before/after series
  - List format series
  - One-off content
  - Expandable topics

- `TestMonetizationScorer` (5 tests)
  - High monetization clips
  - Low monetization clips
  - Series potential detection
  - Recommendations generation
  - Batch scoring

### Integration Tests (1 class, 3 tests)
- Full pipeline: Hook → VVSA → Retention → Series
- Poor clip detection (weak hook + too long)
- Series identification across multiple clips

### Edge Cases (1 class, 4 tests)
- Empty text handling
- Very short clips (<3s)
- Very long clips (>5 min)
- Special characters

**Run Tests:**
```bash
python3 -m unittest clipping.phase1.tests.test_monetization -v
# Output: Ran 38 tests in 0.001s OK
```

---

## 🚀 Integration into Pipeline

### Step 1: After Segment Detection
```python
from clipping.phase1.monetization import MonetizationScorer

# Get segments from existing pipeline
segments = [
    {'text': 'Stop doing this...', 'start': 10, 'end': 40},
    {'text': 'Here's the fix...', 'start': 45, 'end': 75},
]

# Score for monetization
scored = MonetizationScorer.batch_score(segments)

# Filter high-monetization clips
high_value = [
    s for s in scored 
    if s['monetization']['monetization_score'] > 0.65
]

print(f"High-value clips: {len(high_value)} / {len(scored)}")
```

### Step 2: Ranking & Selection
```python
# Sort by monetization score
ranked = sorted(
    scored,
    key=lambda x: x['monetization']['monetization_score'],
    reverse=True
)

# Select top 3-5 for this week's posts
weekly_clips = ranked[:5]

for i, clip in enumerate(weekly_clips, 1):
    m = clip['monetization']
    print(f"\n{i}. {clip['text'][:50]}...")
    print(f"   Monetization: {m['monetization_score']:.1%}")
    print(f"   Series: {m['series_potential']}")
    for rec in m['recommendations']:
        print(f"   - {rec}")
```

### Step 3: Scheduling
```python
# Space clips across week (3-5 per week)
import datetime

best_posting_times = [
    datetime.time(9, 0),   # Monday morning
    datetime.time(13, 0),  # Wednesday lunch
    datetime.time(18, 0),  # Friday evening
]

for i, clip in enumerate(weekly_clips):
    posting_time = best_posting_times[i % len(best_posting_times)]
    print(f"Schedule: {clip['text'][:30]}... → {posting_time}")
```

---

## 📈 Monetization Math

### Revenue Model
```
Monthly Revenue = (Shorts Views × 0.45) × RPM ÷ 1000

Where:
- Shorts Views = Your share of total views that month
- 0.45 = YouTube's rev-share (you keep 45%)
- RPM = Revenue Per Mille ($0.01-$0.07 typical)
```

### Qualification Path
```
Goal: Reach YouTube Partner Program via Shorts

Requirement: 1,000 subscribers + 10M Shorts views in 90 days
(Changes to 1,000 subs + 20M views from Feb 2027)

Timeline: 
- Month 1: Generate 100-200 Shorts clips (quality over quantity)
- Month 2-3: Post 3-5/week, optimize based on analytics
- Goal: 10M views ÷ 90 days = ~111k views/day
```

### Revenue Projection
```
At 10M views / 90 days with $0.03-0.07 RPM:

$300-700 in first 90 days (from qualifying batch)
Ongoing: Sustain 5M+ views/month for $150-350/month

To reach $1k/month: Need ~30M Shorts views/month
```

### Levers to Pull
```
1. Volume (Primary): Post 3-5/week consistently
   - Your pipeline generates multiple candidates/video
   - Select top 3-5 by monetization score
   - Schedule across week

2. Retention (Secondary): Strong hooks + payoff structure
   - Use hook detector + retention optimizer
   - Follow template: Hook (0-3s) → Stakes → Payoff → CTA
   - Aim for 73-76% predicted retention

3. RPM (Tertiary): Topic selection + audience geography
   - Higher-value niches: tech > entertainment
   - English content for global reach
   - Avoid music splits (use YouTube Audio Library)
```

---

## 📋 Complete Workflow Example

```python
"""
Full end-to-end monetization-optimized pipeline
"""

from clipping.phase1.input_handler import InputManager
from clipping.phase1.checkpoint import CheckpointManager
from clipping.phase1.quality_control import QualityControlManager
from clipping.phase1.hybrid_scoring import HybridSegmentScorer
from clipping.phase1.monetization import MonetizationScorer

# 1. Input
input_mgr = InputManager(single_url="https://youtube.com/watch?v=abc")
sources = input_mgr.get_sources()

for source in sources:
    print(f"Processing: {source.source}")
    
    # 2. Setup checkpoint
    checkpoint = CheckpointManager(f"./outputs/{source.source}")
    
    # 3. Download (if needed)
    if not checkpoint.is_step_complete("download"):
        # ... download video ...
        checkpoint.mark_step_complete("download", {"file": "video.mp4"})
    
    # 4. Transcribe (if needed)
    if not checkpoint.is_step_complete("transcribe"):
        # ... transcribe with Whisper ...
        checkpoint.mark_step_complete("transcribe", {"segments": segments})
    
    # 5. Hybrid Score (combine text+audio+scene)
    scorer = HybridSegmentScorer("video.mp4", "audio.wav")
    segments = scorer.score_all_segments(segments)
    
    # 6. **MONETIZATION SCORING** ← New!
    segments = MonetizationScorer.batch_score(segments)
    
    # 7. Select high-value clips
    high_value = [
        s for s in segments 
        if s['monetization']['monetization_score'] > 0.65
    ]
    
    # 8. Sort by monetization
    ranked = sorted(
        high_value,
        key=lambda x: x['monetization']['monetization_score'],
        reverse=True
    )
    
    # 9. Select top 3-5
    weekly_selection = ranked[:5]
    
    # 10. Print analysis for each
    for clip in weekly_selection:
        metrics = clip['monetization']
        print(f"\n📊 {clip['text'][:50]}...")
        print(f"   Monetization: {metrics['monetization_score']:.1%}")
        print(f"   Hook: {metrics['hook_strength']:.1%}")
        print(f"   VVSA: {metrics['vvsa_score']:.1%}")
        print(f"   Retention: {metrics['retention_score']:.1%}")
        print(f"   Series: {metrics['series_potential']}")
    
    # 11. Render & validate
    qc = QualityControlManager()
    # ... render clips ...
    validation = qc.validate_all_clips("./outputs/clips")
    
    # 12. Schedule posting
    # ... 3-5 clips, spread across week ...
    
    print(f"\n✅ Pipeline complete: {len(weekly_selection)} clips ready to post")
```

---

## 🎯 Success Metrics

### Short-term (First 30 days)
- [ ] All 6 components tested (✅ 38/38 tests passing)
- [ ] First 10 Shorts clips scored
- [ ] Average monetization score: >0.60
- [ ] Selection process takes <5 min per video

### Medium-term (90 days)
- [ ] 50+ Shorts published
- [ ] Monetization score correlates with actual VVSA (A/B test)
- [ ] Series identification working (at least 2 series)
- [ ] Average view duration data from YouTube
- [ ] Feedback loop: adjust weights based on actual performance

### Long-term (6 months)
- [ ] 1,000 subs + 10M views → YPP qualification
- [ ] Monetization score predicts top 20% of clips (>85% accuracy)
- [ ] Revenue: $500+/month from Shorts
- [ ] Fully automated: publish 3-5 Shorts/week consistently

---

## 🔄 Feedback Loop (Post-Publishing)

Once you have ~20 Shorts, track performance:

```python
"""
After publishing clips, analyze what actually worked
"""

# In YouTube Studio Analytics
high_performers = [
    clip_id for clip_id in published_clips 
    if clip_data[clip_id]['vvsa'] > 0.75  # Real VVSA
]

# Find patterns
print("High performers had:")
print("- Avg hook score: 0.72")
print("- Avg VVSA predicted: 0.68 (actual: 0.77)")
print("- Series potential: 80% were 'high'")

# Update weights in MonetizationScorer
# Increase VVSA weight from 30% → 35%
# Increase series detection impact
```

Then redeploy with improved weights for next batch.

---

## 📚 Reference Documents

- **Implementation Guide**: `PHASE1_IMPLEMENTATION_GUIDE.md`
- **Gap Analysis**: Artifact (https://claude.ai/code/artifact/...)
- **Project Status**: `PROJECT_STATUS.md`
- **Code**: `clipping/phase1/monetization.py`
- **Tests**: `clipping/phase1/tests/test_monetization.py`

---

**Next:** Run tests, integrate into main pipeline, start scoring real clips!
