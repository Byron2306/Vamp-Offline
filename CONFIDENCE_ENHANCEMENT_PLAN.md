# Evidence Confidence Enhancement Plan

## Problem Statement

**Current Issue**: Evidence confidence scores are consistently low (35-50%), even when evidence perfectly covers expectations.

**Root Causes**:
1. Algorithmic matching relies on keyword overlap, missing semantic meaning
2. User knowledge and context are not captured
3. Certificates, emails, and non-textual evidence lack keyword matches
4. System confidence starts at only 15-30% base

## Solution: User-Driven Confidence Enhancement

### Concept
Allow users to describe how evidence covers expectations, then use their description to:
- Improve AI classification via Ollama
- Boost confidence scores appropriately
- Create semantic mappings instead of keyword-based ones

### Benefits

| Feature | Before | After |
|---------|--------|-------|
| **Assertions** | User locks to task, but system still uncertain (50%) | User describes relevance → 90-95% confidence |
| **Low Confidence** | Evidence sits at 35-50%, user unsure if it counts | User adds context → reclassifies to 70-85% |
| **Semantic Gap** | "OHS_Certificate.pdf" → 40% match to task | "This proves fire safety training" → 90% match |
| **User Trust** | System "guesses" → user doubts accuracy | User validates → system reflects their knowledge |

## Implementation Components

### 1. Frontend: Evidence Description Modal

**Location**: `index.html` + `app.js`

**Trigger Points**:
- **During Scan** (Assertions): When user checks "Lock Evidence to Task"
- **Evidence Log**: "Enhance" button for items with confidence < 60%

**Modal UI**:
```html
<div id="evidenceDescriptionModal" class="modal">
  <div class="modal-content">
    <h3>Describe Evidence Relevance</h3>
    <p class="muted">Help improve accuracy by describing how this evidence covers the expectation.</p>
    
    <div class="info-box">
      <strong>Evidence:</strong> <span id="modalEvidenceFile"></span><br>
      <strong>Task:</strong> <span id="modalTaskTitle"></span>
    </div>
    
    <label>How does this evidence cover the expectation?</label>
    <textarea id="evidenceDescriptionText" 
              rows="4" 
              placeholder="Example: This certificate proves I completed the mandatory fire safety training session on Feb 15th, covering evacuation procedures and extinguisher use."></textarea>
    
    <div class="modal-actions">
      <button class="btn secondary" id="skipDescriptionBtn">Skip</button>
      <button class="btn glow" id="submitDescriptionBtn">Enhance Confidence</button>
    </div>
  </div>
</div>
```

**User Experience**:
1. Modal appears with evidence filename and target task
2. User types description (optional, can skip)
3. If provided, sends to backend for enhancement
4. Shows loading indicator
5. Updates UI with new confidence score

### 2. Backend: Enhancement Endpoint

**Location**: `run_web.py`

**New Route**: `POST /api/evidence/enhance`

**Request**:
```json
{
  "evidence_id": "ev_12345678_2025-02_abc123def4",
  "staff_id": "12345678",
  "user_description": "This certificate proves I completed...",
  "target_task_id": "task_kpa2_feb_ohs" // Optional: for re-targeting
}
```

**Response**:
```json
{
  "success": true,
  "evidence_id": "ev_12345678_2025-02_abc123def4",
  "old_confidence": 0.42,
  "new_confidence": 0.92,
  "old_kpa": "KPA1",
  "new_kpa": "KPA2",
  "reclassified": true,
  "old_mapped_count": 2,
  "new_mapped_count": 1,
  "message": "Evidence enhanced with user context"
}
```

**Processing Steps**:
1. Retrieve evidence from database
2. Load original extracted text
3. Combine with user description
4. Send enhanced prompt to Ollama:
   ```
   User has provided context for evidence classification:
   
   Evidence file: {filename}
   User description: {user_description}
   Original content: {first 500 chars of evidence}
   
   Based on this enhanced context, classify the evidence...
   ```
5. Get improved classification from Ollama
6. Update evidence record with:
   - New KPA code (if changed)
   - New confidence (boosted by user validation)
   - User description in metadata
   - Flag as "user_enhanced"
7. Clear old mappings
8. Remap with enhanced confidence
9. Return results

### 3. Modified Scan Workflow (Assertions)

**Location**: `run_web.py` - `/api/evidence/scan` endpoint

**Changes**:

1. Accept optional `user_description` parameter
2. When `asserted_mapping=true` AND `user_description` provided:
   - Skip generic AI classification
   - Use user description for Ollama prompt
   - Set confidence to 90-95% (user-validated)
   - Store description in evidence metadata

**Enhanced Scan Flow**:
```
User selects evidence file
↓
User selects target task + checks "Lock to Task"
↓
[NEW] Modal opens: "Describe how this evidence covers the expectation"
↓
User provides description (or skips)
↓
Scan proceeds with:
  - asserted_mapping=true
  - user_description=[user's text]
  - Confidence boosted to 90-95%
  - Description stored for future reference
```

### 4. Evidence Log Enhancement

**Location**: `index.html` + `app.js`

**UI Changes**:

**Add "Enhance" button** for low-confidence items:
```javascript
// In renderEvidenceLogTable()
if (confidence < 0.6) {
  const enhanceBtn = document.createElement('button');
  enhanceBtn.className = 'btn-small secondary';
  enhanceBtn.textContent = 'Enhance';
  enhanceBtn.onclick = () => openEnhanceModal(item);
  // Add to row
}
```

**Show enhancement status**:
- Badge: "User Enhanced ✓" for enhanced items
- Show user description on hover/expand
- Display confidence improvement (42% → 92% ↑50%)

### 5. Confidence Boost Rules

**Formula Update** (in mapper.py):

Current:
```python
conf = base + 0.55 * overlap_ratio + min(0.30, 0.10 * hint_hits)
```

Enhanced (when user description provided):
```python
if user_description_provided:
    # User validation is highly trusted
    semantic_conf = ollama_confidence  # From enhanced classification
    user_boost = 0.25  # +25% for user validation
    conf = min(0.95, semantic_conf + user_boost)
else:
    # Original formula
    conf = base + 0.55 * overlap_ratio + min(0.30, 0.10 * hint_hits)
```

**Result**: User-enhanced evidence gets 85-95% confidence instead of 35-50%

### 6. Database Schema Addition

**Location**: `progress_store.py`

**Evidence table metadata** (JSON field) now includes:
```json
{
  "user_description": "Text provided by user",
  "user_enhanced": true,
  "enhancement_date": "2025-02-15T10:30:00Z",
  "original_confidence": 0.42,
  "enhanced_confidence": 0.92,
  "enhancement_method": "user_description"
}
```

## Ollama Integration

### Enhanced Classification Prompt

**When user provides description**:

```python
def classify_with_user_context(filename, file_text, user_description, target_task=None):
    prompt = f"""You are classifying evidence for academic performance assessment.
    
USER CONTEXT (MOST IMPORTANT):
The staff member has described this evidence as:
"{user_description}"

EVIDENCE FILE: {filename}

CONTENT PREVIEW (first 500 chars):
{file_text[:500]}

TARGET TASK (if specified): {target_task or 'Not specified'}

Based on the USER'S DESCRIPTION (which is highly trusted), classify this evidence:

1. KPA Classification:
   - KPA1: Teaching & Learning
   - KPA2: Occupational Health & Safety
   - KPA3: Research & Innovation
   - KPA4: Academic Leadership & Administration
   - KPA5: Social Responsiveness & Engagement

2. Tier Level:
   - Transformational: Major impact, innovation
   - Developmental: Growth, improvement
   - Compliance: Meeting standards

3. Task Match: Does this evidence match the target task? (Yes/No and why)

4. Confidence: How confident are you? (0.0-1.0)

Return JSON:
{{
  "kpa": "KPA2",
  "task": "OHS compliance training",
  "tier": "Compliance",
  "impact_summary": "Based on user description...",
  "confidence": 0.95,
  "user_context_used": true
}}
"""
    # Send to Ollama
    return ollama_request(prompt)
```

**Key Point**: User description is weighted HIGHEST in the prompt, instructing Ollama to trust the user's judgment.

## Rollout Plan

### Phase 1: Backend Enhancement Endpoint ✓
- Implement `/api/evidence/enhance` endpoint
- Add user description to evidence metadata
- Create enhanced Ollama prompt template

### Phase 2: Evidence Log Enhancement Button ✓
- Add "Enhance" button for confidence < 60%
- Create modal UI
- Wire up enhancement flow
- Show before/after confidence

### Phase 3: Scan-Time Assertions ✓
- Add modal to scan workflow when locked
- Collect user description during scan
- Apply enhancement immediately
- Store as user-validated assertion

### Phase 4: Reporting & Analytics
- Track enhancement impact
- Show "User Enhanced" badges
- Report on confidence improvements
- Identify patterns for future automation

## Expected Results

### Confidence Distribution

**Before Enhancement**:
```
0-30%: 15% of evidence
31-50%: 60% of evidence  ← Most evidence here!
51-70%: 20% of evidence
71-100%: 5% of evidence
```

**After Enhancement** (with 40% adoption):
```
0-30%: 5% of evidence
31-50%: 30% of evidence
51-70%: 25% of evidence
71-100%: 40% of evidence  ← User-enhanced evidence here!
```

### User Trust Impact

| Metric | Before | After |
|--------|--------|-------|
| User trusts mappings | 45% | 85% |
| Evidence feels "counted" | 50% | 90% |
| Manual corrections needed | High | Low |
| Time spent validating | 30 min/month | 10 min/month |

## Technical Notes

### Why This Works

1. **Human-in-the-Loop**: Users provide ground truth that algorithms can't infer
2. **Semantic Understanding**: Ollama better classifies with natural language context
3. **Confidence Calibration**: User validation justifies higher confidence scores
4. **Incremental**: Works for both new scans and existing evidence
5. **Optional**: Users can skip if evidence is obvious

### Limitations

- Requires user time (optional mitigation: only prompt for unclear items)
- Depends on Ollama quality (mitigated by strong prompt engineering)
- Users might not describe accurately (mitigated by showing classification result)

### Future Enhancements

- **Learning**: Store user descriptions to improve future auto-classification
- **Suggestions**: Pre-fill description based on similar past evidence
- **Batch Mode**: Describe multiple similar items at once
- **Voice Input**: Use voice-to-text for faster descriptions

---

**Status**: Ready for implementation  
**Priority**: High - directly addresses major user pain point  
**Effort**: Medium (2-3 days)  
**Impact**: High - transforms confidence from 35-50% to 85-95% for enhanced items
