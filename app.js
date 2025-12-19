/* ============================================================
   CORE STATE & HELPERS
============================================================ */

const $ = (id) => document.getElementById(id);
const log = (msg) => {
  const el = $("appLog");
  if (el) {
    el.textContent += `[${new Date().toLocaleTimeString()}] ${msg}\n`;
    el.scrollTop = el.scrollHeight;
  }
};

const scanLog = (msg) => {
  const el = $("scanLog");
  if (el) {
    el.textContent += `[${new Date().toLocaleTimeString()}] ${msg}\n`;
    el.scrollTop = el.scrollHeight;
  }
};

// Fallback global tab switcher so inline `onclick="switchToTab(...)"` never fails
window.switchToTab = function(tabKey) {
  try {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    const tab = document.querySelector(`.tab[data-tab="${tabKey}"]`);
    if (tab) tab.classList.add('active');
    const panel = document.getElementById('tab-' + tabKey);
    if (panel) panel.classList.add('active');
    log(`Switched to: ${tabKey}`);
  } catch (e) {
    console.error('switchToTab error', e);
  }
}

// Global state
let currentProfile = null;
let currentExpectations = [];
let currentScanResults = [];
let currentResolveItem = null;
let currentScanTargetTaskId = null;
let currentScanAbortController = null;
let currentAIGuidanceTask = null; // Store the task for AI guidance modal

// Scan panel DOM home (so we can move it inline under a month/KPA and restore safely)
let scanPanelHome = null;

function rememberScanPanelHome() {
  if (scanPanelHome) return;
  const section = $("scanEvidenceSection");
  if (!section || !section.parentNode) return;
  scanPanelHome = {
    parent: section.parentNode,
    nextSibling: section.nextSibling
  };
}

function restoreScanPanelHome({ hide = true } = {}) {
  const section = $("scanEvidenceSection");
  if (!section || !scanPanelHome?.parent) return;

  const { parent, nextSibling } = scanPanelHome;
  if (nextSibling && nextSibling.parentNode === parent) {
    parent.insertBefore(section, nextSibling);
  } else {
    parent.appendChild(section);
  }

  if (hide) section.style.display = "none";
}

function attachScanPanelTo(hostEl) {
  // To avoid losing file input selection when moving elements between
  // containers (browsers often clear file inputs on DOM move), do NOT
  // physically move the scan section. Instead, insert a lightweight
  // anchor in the requested host which shows the fixed scan panel when
  // the user clicks it. This preserves any selected files and keeps
  // event listeners intact.
  const section = $("scanEvidenceSection");
  if (!section || !hostEl) return;
  rememberScanPanelHome();

  // Remove any existing inline anchors so we never create duplicates
  try {
    document.querySelectorAll('#scanEvidenceSectionInlineAnchor').forEach(a => a.remove());
  } catch (e) {
    // ignore
  }

  // If the section is already displayed (user opened it), nothing more to do
  if (section.style.display === 'block') {
    section.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }

  // Create an inline anchor button that opens the scan panel in its fixed location
  const anchor = document.createElement('div');
  anchor.id = 'scanEvidenceSectionInlineAnchor';
  anchor.style.cssText = 'margin-bottom:8px;';
  anchor.innerHTML = `<button class="btn" style="width:100%;" aria-label="Open scan panel">Open Scan Panel ⤴</button>`;
  anchor.querySelector('button').addEventListener('click', () => {
    // Show the fixed scan panel in its original home and scroll it into view
    section.style.display = 'block';
    section.scrollIntoView({ behavior: 'smooth', block: 'center' });
    // Reveal target task label if set
    const targetLabel = $("scanTargetTaskLabel");
    if (targetLabel && targetLabel.style.display === 'none') targetLabel.style.display = 'block';
  });

  hostEl.appendChild(anchor);
}

function clearTargetedScanState() {
  currentScanTargetTaskId = null;
  const targetInput = $("scanTargetTaskId");
  if (targetInput) targetInput.value = "";
  const targetLabel = $("scanTargetTaskLabel");
  if (targetLabel) targetLabel.style.display = "none";
}

/* ============================================================
   VAMP AGENT CONTROL — VIDEO STATE MANAGEMENT
============================================================ */

const vampVideo = $("vamp-video");
const vampSound = $("vampSound");
const vampBubbles = $("vamp-bubbles");
const vampInput = $("ask-vamp-input");
const vampBtn = $("ask-vamp-btn");
const vampOverlay = $("vampThinking");
const vampOverlayText = $("vampThinkingText");

// Video States
const VAMP_STATE = {
  IDLE: 'idle',
  BUSY: 'busy',
  SPEAKING: 'speaking'
};

let currentVampState = VAMP_STATE.IDLE;

function vampIdle(text = "Awaiting instruction…") {
  currentVampState = VAMP_STATE.IDLE;
  if (vampVideo) {
    vampVideo.pause();
    vampVideo.currentTime = 0;
  }
  try {
    vampSound?.pause();
    if (vampSound) vampSound.currentTime = 0;
  } catch (e) {}
  hideVampOverlay();
  pushBubble(text, "idle");
}

function vampBusy(text = "Analysing…") {
  currentVampState = VAMP_STATE.BUSY;
  if (vampVideo) {
    vampVideo.pause();
    vampVideo.currentTime = 0;
  }
  try { vampSound?.pause(); } catch(e) {}
  showVampOverlay(text);
}

function vampSpeak(text) {
  currentVampState = VAMP_STATE.SPEAKING;
  if (vampVideo) {
    vampVideo.loop = true;
    vampVideo.currentTime = 0;
    vampVideo.play().catch(() => {});
  }
  // ElevenLabs voice will play instead of vamp.wav
  hideVampOverlay();
  pushBubble(text, "speak");
  
  // Don't auto-return to idle - let voice audio control this
  // The playVoiceResponse function will call vampIdle() when audio ends
}

function showVampOverlay(text) {
  if (vampOverlay) {
    vampOverlay.style.display = 'flex';
    if (vampOverlayText) {
      vampOverlayText.textContent = text;
    }
  }
}

function hideVampOverlay() {
  if (vampOverlay) {
    vampOverlay.style.display = 'none';
  }
}

function pushBubble(text, mode = "speak") {
  if (!vampBubbles) return;
  const div = document.createElement("div");
  div.className = "vamp-bubble " + mode;
  div.textContent = text;
  vampBubbles.appendChild(div);
  vampBubbles.scrollTop = vampBubbles.scrollHeight;
  
  // Limit bubble count
  while (vampBubbles.children.length > 10) {
    vampBubbles.removeChild(vampBubbles.firstChild);
  }
}

/* ============================================================
   ASK VAMP — AI INTERACTION SURFACE
============================================================ */

if (vampBtn) {
  vampBtn.addEventListener("click", async () => {
    const q = vampInput.value.trim();
    if (!q) return;

    pushBubble(q, "user");
    vampInput.value = "";

    vampBusy("Consulting the archives…");

    try {
      // Use voice-enabled endpoint if voice is available
      const endpoint = voiceEnabled ? "/api/vamp/ask-voice" : "/api/vamp/ask";
      
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          context: collectContext()
        })
      });

      if (!res.ok) throw new Error("VAMP unavailable");

      const data = await res.json();
      const answer = data.answer || "I have nothing further to add.";
      
      vampSpeak(answer);
      log(`Ask-VAMP: ${q.substring(0, 50)}...`);
      
      // Play voice response if available
      if (data.audio_url) {
        playVoiceResponse(data.audio_url);
      }
    } catch (e) {
      vampSpeak(
        "I am unable to reach my cognitive core. Please ensure Ollama is running."
      );
      log("Ask-VAMP error: " + e.message);
    }
  });
}

// Allow Enter to submit (Shift+Enter for newline)
if (vampInput) {
  vampInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      vampBtn?.click();
    }
  });
}

/* ============================================================
   CONTEXT GATHERING (SAFE, NON-INTRUSIVE)
============================================================ */

function collectContext() {
  const context = {
    staff_id: $("staffId")?.value || null,
    cycle_year: $("cycleYear")?.value || null,
    stage: $("stagePill")?.textContent || null,
    scan_month: $("scanMonth")?.value || null,
    current_tab: document.querySelector(".tab.active")?.dataset.tab || null,
    expectations_count: currentExpectations.length,
    scan_results_count: currentScanResults.length
  };
  
  // Include current task info if AI guidance modal is active
  if (currentAIGuidanceTask) {
    context.task = {
      id: currentAIGuidanceTask.id || currentAIGuidanceTask.task_id,
      _baseId: currentAIGuidanceTask._baseId || null,
      _canonicalId: currentAIGuidanceTask._canonicalId || null,
      title: currentAIGuidanceTask.title || currentAIGuidanceTask.task || currentAIGuidanceTask.output,
      kpa: currentAIGuidanceTask.kpa_name || currentAIGuidanceTask.kpa || currentAIGuidanceTask.kpa_code,
      goal: currentAIGuidanceTask.goal || currentAIGuidanceTask.outputs || currentAIGuidanceTask.what_to_do,
      cadence: currentAIGuidanceTask.cadence,
      minimum_count: currentAIGuidanceTask.minimum_count || currentAIGuidanceTask.min_required,
      stretch_count: currentAIGuidanceTask.stretch_count || currentAIGuidanceTask.stretch_target,
      evidence_hints: currentAIGuidanceTask.evidence_hints,
      evidence_required: currentAIGuidanceTask.evidence_required
    };
  }
  
  return context;
}

/* ============================================================
   TAB NAVIGATION (UNCHANGED BEHAVIOUR)
============================================================ */

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));

    tab.classList.add("active");
    const target = "tab-" + tab.dataset.tab;
    const panel = document.getElementById(target);
    if (panel) panel.classList.add("active");
    
    log(`Switched to: ${tab.textContent}`);
  });
});

/* ============================================================
   ENROLMENT FLOW (PRESERVED)
============================================================ */

async function enrolOrLoadProfile() {
  vampBusy("Registering your academic identity…");

  const profile = {
    staff_id: $("staffId")?.value,
    cycle_year: $("cycleYear")?.value,
    name: $("name")?.value,
    position: $("position")?.value,
    faculty: $("faculty")?.value,
    manager: $("manager")?.value
  };

  try {
    const res = await fetch("/api/profile/enrol", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile)
    });

    if (res.ok) {
      currentProfile = profile;
      $("chipProfile").textContent = "Profile ✓";
      $("chipProfile").classList.remove("bad");
      $("chipProfile").classList.add("ok");
      $("profilePill").textContent = "Profile loaded";
      $("profilePill").classList.remove("bad");
      $("profilePill").classList.add("ok");
      $("stagePill").textContent = "Stage: Profile loaded";
      vampSpeak("Your profile is set. Upload your Task Agreement when ready.");
      log(`Enrolled: ${profile.name} (${profile.staff_id})`);
    } else {
      vampSpeak("Enrolment failed. Please review your details.");
      log("Enrolment failed: " + (await res.text()));
    }
  } catch (e) {
    vampSpeak("Cannot reach the server. Please ensure it is running.");
    log("Enrolment error: " + e.message);
  }
}

// Expose as a global for the inline fallback handler (and for debugging).
window.enrolOrLoadProfile = enrolOrLoadProfile;

$("enrolBtn")?.addEventListener("click", enrolOrLoadProfile);

/* ============================================================
   TASK AGREEMENT IMPORT
============================================================ */

$("taUploadBtn")?.addEventListener("click", async () => {
  const f = $("taFile").files[0];
  if (!f) {
    vampSpeak("Please select a Task Agreement file first.");
    return;
  }

  vampBusy("Reading your Task Agreement…");

  const fd = new FormData();
  fd.append("file", f);
  fd.append("staff_id", $("staffId").value);
  fd.append("cycle_year", $("cycleYear").value);

  try {
    const res = await fetch("/api/ta/import", { method: "POST", body: fd });

    if (res.ok) {
      const data = await res.json();
      $("chipTA").textContent = "TA ✓";
      $("chipTA").classList.remove("bad");
      $("chipTA").classList.add("ok");
      $("taPill").textContent = "TA imported";
      $("taPill").classList.remove("bad");
      $("taPill").classList.add("ok");
      $("stagePill").textContent = "Stage: TA imported";
      const tasksCount = data.tasks_count || 0;
      vampSpeak(`Your agreed work has been fully understood. ${tasksCount} tasks extracted.`);
      log(`TA imported: ${tasksCount} tasks found`);
      
      // Auto-load expectations
      setTimeout(() => loadExpectations(), 500);
      
      // If less than 10 tasks, something went wrong - try rebuild
      if (tasksCount < 10) {
        log("Warning: Low task count. Attempting rebuild...");
        setTimeout(() => $("rebuildExpBtn")?.click(), 1000);
      }
    } else {
      vampSpeak("I could not interpret the Task Agreement.");
      log("TA import failed: " + (await res.text()));
    }
  } catch (e) {
    vampSpeak("Upload failed. Check your connection.");
    log("TA upload error: " + e.message);
  }
});

/* ============================================================
   STATUS REFRESH — UPDATE PILLS/CHIPS WITHOUT FULL PAGE RELOAD
============================================================ */

$("refreshStatusBtn")?.addEventListener("click", refreshStatusIndicators);

async function refreshStatusIndicators() {
  const staffId = $("staffId")?.value?.trim();
  const cycleYear = $("cycleYear")?.value?.trim();

  if (!staffId || !cycleYear) {
    vampSpeak("Enter your Staff ID and cycle year before refreshing status.");
    return;
  }

  vampBusy("Refreshing system status…");
  log("Refreshing UI status indicators");

  try {
    const [progressResult, expectationsResult] = await Promise.allSettled([
      fetch(`/api/progress?staff_id=${staffId}&year=${cycleYear}`),
      fetch(`/api/expectations?staff_id=${staffId}&year=${cycleYear}`)
    ]);

    let progressData = null;
    if (progressResult.status === "fulfilled") {
      if (progressResult.value.ok) {
        progressData = await progressResult.value.json();
        taskCompletionMap = progressData.task_completion || {};
      } else if (progressResult.value.status === 404) {
        taskCompletionMap = {};
      } else {
        const errorText = await progressResult.value.text();
        throw new Error(errorText || `Progress refresh failed (${progressResult.value.status})`);
      }
    } else {
      const reason = progressResult.reason?.message || progressResult.reason || "unknown error";
      log(`Status refresh: progress fetch failed (${reason})`);
    }

    let expectationsData = null;
    if (expectationsResult.status === "fulfilled") {
      if (expectationsResult.value.ok) {
        expectationsData = await expectationsResult.value.json();
      } else if (expectationsResult.value.status === 404) {
        currentExpectations = [];
        renderMonthlyExpectations({}, []);
        renderPAExpectationsTable([]);
      } else {
        const errorText = await expectationsResult.value.text();
        throw new Error(errorText || `Expectations refresh failed (${expectationsResult.value.status})`);
      }
    } else {
      const reason = expectationsResult.reason?.message || expectationsResult.reason || "unknown error";
      log(`Status refresh: expectations fetch failed (${reason})`);
    }

    if (expectationsData) {
      currentExpectations = expectationsData.tasks || expectationsData.expectations || [];
      renderMonthlyExpectations(expectationsData.by_month || {}, currentExpectations);
      renderPAExpectationsTable(currentExpectations);
    }

    await updateYearTimeline(progressData?.months_progress || null);

    const expectationsLoaded = currentExpectations.length > 0;
    const taImported = expectationsLoaded || Boolean(progressData?.progress?.total_tasks);
    const profileLoaded = currentProfile
      ? currentProfile.staff_id === staffId && String(currentProfile.cycle_year) === cycleYear
      : (expectationsLoaded || taImported);

    updateStatusChips({ profileLoaded, taImported, expectationsLoaded });
    vampSpeak("Status refreshed.");
  } catch (e) {
    vampSpeak("Could not refresh status.");
    log("Status refresh error: " + e.message);
  }
}

function updateStatusChips({ profileLoaded, taImported, expectationsLoaded }) {
  setChipState("chipProfile", "Profile", profileLoaded);
  setChipState("chipTA", "TA", taImported);
  setChipState("chipExp", "Expectations", expectationsLoaded);

  setPillState("profilePill", "Profile loaded", "No profile loaded", profileLoaded);
  setPillState("taPill", "TA imported", "No TA imported", taImported);

  const stagePill = $("stagePill");
  if (stagePill) {
    if (expectationsLoaded) {
      stagePill.textContent = "Stage: Expectations ready";
    } else if (taImported) {
      stagePill.textContent = "Stage: TA imported";
    } else if (profileLoaded) {
      stagePill.textContent = "Stage: Profile loaded";
    } else {
      stagePill.textContent = "Stage: Awaiting enrolment";
    }
  }
}

function setChipState(id, label, ok) {
  const el = $(id);
  if (!el) return;
  el.textContent = ok ? `${label} ✓` : `${label} ❌`;
  el.classList.toggle("ok", ok);
  el.classList.toggle("bad", !ok);
}

function setPillState(id, okText, badText, ok) {
  const el = $(id);
  if (!el) return;
  el.textContent = ok ? okText : badText;
  el.classList.toggle("ok", ok);
  el.classList.toggle("bad", !ok);
}

/* ============================================================
   EXPECTATIONS TAB — TABLE RENDERING
============================================================ */

// Global task completion map
let taskCompletionMap = {};

async function loadExpectations() {
  const staffId = $("staffId")?.value?.trim();
  const cycleYear = $("cycleYear")?.value?.trim();
  
  if (!staffId || !cycleYear) {
    log("Cannot load expectations: staff ID or cycle year not set");
    return;
  }
  
  vampBusy("Loading expectations…");
  
  try {
    const res = await fetch(`/api/expectations?staff_id=${staffId}&year=${cycleYear}`);
    
    if (!res.ok) {
      if (res.status === 404) {
        throw new Error("Expectations not found. Please import a Task Agreement.");
      }
      throw new Error(`Failed to load expectations (${res.status})`);
    }
    
    const data = await res.json();
    console.log("Expectations data received:", data);
    
    // Use tasks array from the response
    const tasks = data.tasks || data.expectations || [];
    currentExpectations = tasks;
    
    // Also store by_month for task lookup
    window.expectationsData = data;

    // Prefer backend canonical hashed IDs: build base->month->hid map from tasks
    try {
      const baseToHashed = {};
      (data.tasks || []).forEach(bt => {
        const baseId = bt.task_id || bt.id;
        const hashed = bt.hashed_ids || {};
        if (baseId && hashed && typeof hashed === 'object') {
          Object.entries(hashed).forEach(([mon, hid]) => {
            baseToHashed[`${baseId}|${mon.padStart ? mon.padStart(2,'0') : String(mon).padStart(2,'0')}`] = hid;
          });
        }
      });

      // Normalize by_month tasks to use canonical hashed id when available
      const byMonth = data.by_month || {};
      Object.entries(byMonth).forEach(([monthKey, monthEntry]) => {
        const monthNum = monthKey.split('-')[1] || null;
        const monthTasks = Array.isArray(monthEntry) ? monthEntry : (monthEntry.tasks || []);
        monthTasks.forEach(mt => {
          const baseId = mt._baseId || mt.task_id || mt.id;
          if (!baseId || !monthNum) return;
          const key = `${baseId}|${String(parseInt(monthNum,10)).padStart(2,'0')}`;
          const hid = baseToHashed[key];
          if (hid) {
            mt._canonicalId = hid;
            mt.id = hid; // prefer canonical hashed id for UI lookup
          }
        });
      });
    } catch (e) {
      console.warn('Could not apply backend canonical id normalization:', e);
    }

    // Robust normalization: always set monthly task.id to canonical hashed ID if available, and add baseId for fallback
    try {
      const taskIndex = {};
      (tasks || []).forEach(t => {
        const key = t.task_id || t.id;
        if (key) taskIndex[key] = t;
      });

      const byMonth = data.by_month || {};
      Object.keys(byMonth).forEach(monthKey => {
        const monthEntry = byMonth[monthKey];
        const monthTasks = Array.isArray(monthEntry) ? monthEntry : (monthEntry.tasks || []);
        monthTasks.forEach(t => {
          const baseId = t.task_id || t.id;
          const base = taskIndex[baseId];
          // Always store the original baseId for fallback
          t._baseId = baseId;
          if (base && base.hashed_ids) {
            const m = monthKey.split('-')[1];
            if (base.hashed_ids[m]) {
              t.id = base.hashed_ids[m];
              t._canonicalId = base.hashed_ids[m];
            }
          }
        });
      });
    } catch (e) {
      console.warn('Could not robustly normalize hashed task ids:', e);
    }
    
    console.log("Tasks count:", tasks.length);
    console.log("By month keys:", Object.keys(data.by_month || {}));
    console.log("KPA summary:", data.kpa_summary);
    
    // Load progress/completion status
    await loadProgress();
    // Render the year timeline based on progress data
    await updateYearTimeline();
    
    renderMonthlyExpectations(data.by_month || {}, tasks);
    renderPAExpectationsTable(tasks);
    
    $("chipExp").textContent = "Expectations ✓";
    $("chipExp").classList.remove("bad");
    $("chipExp").classList.add("ok");
    
    const kpaCount = Object.keys(data.kpa_summary || {}).length;
    const completedCount = Object.keys(taskCompletionMap).length;
    vampSpeak(`Loaded ${tasks.length} tasks across ${kpaCount} KPAs. ${completedCount} tasks completed.`);
    log(`Expectations loaded: ${tasks.length} tasks, ${kpaCount} KPAs, ${completedCount} completed`);
  } catch (e) {
    vampSpeak(e.message || "Could not load expectations.");
    log("Expectations error: " + e.message);
    console.error("Expectations error:", e);
  }
}

async function loadProgress() {
  try {
    const res = await fetch(`/api/progress?staff_id=${$("staffId").value}&year=${$("cycleYear").value}`);
    if (res.ok) {
      const progressData = await res.json();
      taskCompletionMap = progressData.task_completion || {};
      console.log("Progress loaded:", progressData.stats);
    }
  } catch (e) {
    console.warn("Could not load progress:", e);
    taskCompletionMap = {};
  }
}

// Update year timeline UI with per-month completion counts
async function updateYearTimeline(prefetchedMonthsProgress = null) {
  const container = $("yearTimeline");
  const staffId = $("staffId").value;
  const year = $("cycleYear").value;
  if (!container || !staffId || !year) return;

  container.innerHTML = '';
  let monthsProgress = null;

  if (prefetchedMonthsProgress) {
    monthsProgress = prefetchedMonthsProgress;
  } else {
    let monthsData = null;
    try {
      const res = await fetch(`/api/progress?staff_id=${staffId}&year=${year}`);
      if (res.ok) monthsData = await res.json();
    } catch (e) {
      console.warn('Year timeline fetch failed, falling back to per-month requests', e);
    }
    monthsProgress = monthsData?.months_progress || null;
  }

  const monthKeys = Array.from({ length: 12 }, (_, i) => `${year}-${String(i + 1).padStart(2, '0')}`);

  // If we have aggregated months_progress, use it; otherwise fall back to per-month fetches
  const results = monthsProgress
    ? monthKeys.map(mk => ({ monthKey: mk, data: monthsProgress[mk] || null }))
    : await Promise.all(monthKeys.map(monthKey => {
        return fetch(`/api/progress?staff_id=${staffId}&year=${year}&month=${monthKey}`)
          .then(r => r.ok ? r.json() : null)
          .then(d => ({ monthKey, data: d }))
          .catch(() => ({ monthKey, data: null }));
      }));

  results.forEach(res => {
    const { monthKey, data } = res;
    const label = new Date(monthKey + '-01').toLocaleDateString('en-US', { month: 'short' });
    const monthEl = document.createElement('div');
    monthEl.className = 'month-badge';
    monthEl.dataset.month = monthKey;

    const drop = document.createElement('div');
    drop.className = 'blood-drop';
    drop.textContent = '🩸';

    const count = document.createElement('div');
    count.className = 'month-count';
    let completed = 0;
    let total = 0;
    let evidenceCount = 0;

    const progress = data?.progress || {};
    const stats = data?.stats || {};
    completed = parseInt(progress.completed_count || 0, 10);
    total = parseInt(progress.total_tasks || 0, 10);
    evidenceCount = parseInt(stats.evidence_count || 0, 10);

    // Show task completion ratio (never substitute evidence-only counts)
    count.textContent = `${completed}/${total}`;

    // Month is complete only when all expected tasks are done
    const isComplete = total > 0 && completed >= total;
    if (isComplete) {
      monthEl.classList.add('done');
      monthEl.title = `${label}: complete`;
    } else {
      monthEl.title = total > 0
        ? `${label}: incomplete (${completed}/${total} tasks)`
        : `${label}: incomplete (no tasks defined)`;
    }

    const lbl = document.createElement('div');
    lbl.className = 'month-label';
    lbl.textContent = label;

    monthEl.appendChild(drop);
    const nameWrap = document.createElement('div');
    nameWrap.style.display = 'flex';
    nameWrap.style.flexDirection = 'column';
    nameWrap.appendChild(lbl);
    monthEl.appendChild(count);
    monthEl.appendChild(nameWrap);

    monthEl.addEventListener('click', () => {
      const select = $("currentMonthSelect");
      if (select) select.value = monthKey;
      // Render expectations and reload evidence for the selected month
      renderMonthView(monthKey);
      loadEvidence(monthKey);
      // Also update the month status using the check-month endpoint
      checkMonthStatus();
    });

    container.appendChild(monthEl);
  });
}

function renderMonthlyExpectations(byMonth, allTasks) {
  const container = $("monthlyExpectationsContainer");
  const monthSelect = $("currentMonthSelect");
  if (!container || !monthSelect) return;
  
  // Validate inputs
  if (!byMonth || typeof byMonth !== 'object' || Object.keys(byMonth).length === 0) {
    container.innerHTML = '<div class="muted" style="text-align:center;padding:20px;">Import a Task Agreement to see monthly expectations.</div>';
    return;
  }
  
  // Store for later use
  window.currentByMonth = byMonth;
  window.currentAllTasks = Array.isArray(allTasks) ? allTasks : [];
  
  // Initial render for current month
  renderMonthView(monthSelect.value);
  
  // Update when month changes
  monthSelect.addEventListener("change", () => {
    const mk = monthSelect.value;
    renderMonthView(mk);
    // reload evidence log for selected month
    loadEvidence(mk);
  });
}

function renderMonthView(monthKey) {
  const container = $("monthlyExpectationsContainer");
  if (!container || !window.currentByMonth) return;

  const kpaSectionMap = {};

  // If the scan panel was previously moved inside the month container,
  // restore it before wiping the container to avoid losing it.
  restoreScanPanelHome({ hide: true });
  
  container.innerHTML = "";
  
  let tasks = window.currentByMonth[monthKey] || [];
  
  // Handle both array format and object format with tasks property
  if (!Array.isArray(tasks) && tasks.tasks) {
    tasks = tasks.tasks;
  }
  if (!Array.isArray(tasks)) {
    tasks = [];
  }
  
  if (tasks.length === 0) {
    container.innerHTML = `<div class="muted" style="text-align:center;padding:20px;">No expectations for this month.</div>`;
    return;
  }
  
  // Group tasks by KPA
  const kpaGroups = {};
  tasks.forEach(task => {
    const code = task.kpa_code || 'KPA1';
    if (!kpaGroups[code]) {
      kpaGroups[code] = {
        code: code,
        name: task.kpa_name || code,
        tasks: []
      };
    }
    kpaGroups[code].tasks.push(task);
  });
  
  // Render each KPA section
  const monthName = new Date(monthKey + "-01").toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  
  const headerDiv = document.createElement("div");
  headerDiv.style.cssText = "margin-bottom:16px;padding:12px;background:var(--panel);border-radius:8px;";
  headerDiv.innerHTML = `
    <h3 style="margin:0;color:var(--purple);">${monthName} Expectations</h3>
    <div style="color:var(--grey-muted);font-size:12px;margin-top:4px;">
      ${tasks.length} tasks across ${Object.keys(kpaGroups).length} KPAs
    </div>
  `;
  container.appendChild(headerDiv);
  
  // Sort KPAs by code
  const sortedKPAs = Object.entries(kpaGroups).sort((a, b) => a[0].localeCompare(b[0]));
  
  sortedKPAs.forEach(([code, kpaData]) => {
    const kpaSection = document.createElement("div");
    kpaSection.style.cssText = "margin-bottom:16px;border:1px solid var(--grey-dim);border-radius:8px;overflow:hidden;";
    kpaSectionMap[code] = kpaSection;
    
    // KPA Header
    const kpaHeader = document.createElement("div");
    kpaHeader.style.cssText = "background:var(--purple);color:white;padding:12px 16px;font-weight:bold;";
    kpaHeader.innerHTML = `${code}: ${kpaData.name}`;

    // Host container where the scan panel can be moved inline for this KPA
    const scanHost = document.createElement("div");
    scanHost.id = `scanHost-${monthKey}-${code}`;
    scanHost.dataset.month = monthKey;
    scanHost.dataset.kpa = code;
    scanHost.style.cssText = "padding:12px;background:var(--panel-dark);";
    
    // Tasks for this KPA
    const tasksList = document.createElement("div");
    tasksList.style.cssText = "padding:12px;background:var(--panel-dark);";
    
    kpaData.tasks.forEach(task => {
      const taskItem = document.createElement("div");
      taskItem.style.cssText = "display:flex;align-items:flex-start;padding:10px;margin-bottom:8px;background:var(--panel);border-radius:4px;border-left:3px solid var(--purple);";
      
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.id = `task-${task.id}`;
      checkbox.style.cssText = "margin-right:12px;margin-top:4px;";
      checkbox.dataset.taskId = task.id;
      checkbox.checked = !!taskCompletionMap[task.id];
      checkbox.disabled = true;
      
      const label = document.createElement("label");
      label.htmlFor = `task-${task.id}`;
      label.style.cssText = "flex:1;cursor:pointer;";

      const outputsText = (task.outputs || task.output || "").toString().trim();
      const whatToDoText = (task.what_to_do || task.description || "").toString().trim();
      const evidenceReqText = (task.evidence_required || "").toString().trim();
      const hintsArr = Array.isArray(task.evidence_hints) ? task.evidence_hints : [];
      const hintsText = hintsArr.length ? hintsArr.join(", ") : "";

      label.innerHTML = `
        <div style="font-weight:bold;margin-bottom:4px;">${task.title}</div>
        <div style="font-size:11px;color:var(--grey-muted);">
          <span style="margin-right:12px;">📅 ${task.cadence}</span>
          <span style="margin-right:12px;">🎯 Required: ${task.minimum_count}</span>
          <span>⭐ Stretch: ${task.stretch_count}</span>
        </div>
        ${whatToDoText ? `<div style="font-size:11px;color:var(--grey-dim);margin-top:6px;"><strong>What to do:</strong> ${whatToDoText}</div>` : ''}
        ${outputsText ? `<div style="font-size:11px;color:var(--grey-dim);margin-top:6px;"><strong>Activity / output:</strong> ${outputsText}</div>` : ''}
        ${evidenceReqText ? `<div style="font-size:11px;color:var(--grey-dim);margin-top:4px;"><strong>Evidence required:</strong> ${evidenceReqText}</div>` : ''}
        ${hintsText ? `<div style="font-size:11px;color:var(--grey-dim);margin-top:4px;"><strong>Evidence examples:</strong> ${hintsText}</div>` : ''}
      `;
      
      const aiBtn = document.createElement("button");
      aiBtn.className = "btn-small";
      aiBtn.textContent = "🤖 AI";
      aiBtn.onclick = () => openAIGuidance(task.id);

      const scanBtn = document.createElement("button");
      scanBtn.className = "btn-small";
      scanBtn.textContent = "📎 Scan";
      scanBtn.style.marginLeft = "8px";
      scanBtn.onclick = () => {
        currentScanTargetTaskId = task.id;
        const targetInput = $("scanTargetTaskId");
        if (targetInput) targetInput.value = task.id;

        const targetLabel = $("scanTargetTaskLabel");
        const targetText = $("scanTargetTaskText");
        if (targetText) targetText.textContent = task.title;
        if (targetLabel) targetLabel.style.display = "block";

        const scanMonth = $("scanMonth");
        if (scanMonth) scanMonth.value = monthKey;

        // Move scan panel inline under this KPA section
        attachScanPanelTo(scanHost);
        vampSpeak("Upload evidence for the selected task.");
      };
      
      taskItem.appendChild(checkbox);
      taskItem.appendChild(label);
      taskItem.appendChild(aiBtn);
      taskItem.appendChild(scanBtn);
      
      tasksList.appendChild(taskItem);
    });
    
    kpaSection.appendChild(kpaHeader);
    kpaSection.appendChild(scanHost);
    kpaSection.appendChild(tasksList);
    container.appendChild(kpaSection);
  });

  // Highlight KPAs that are already complete for this month
  try {
    const staffId = $("staffId").value;
    const year = $("cycleYear").value;
    fetch(`/api/progress?staff_id=${staffId}&year=${year}&month=${monthKey}`)
      .then(r => r.ok ? r.json() : null)
      .then(pdata => {
        const byKpa = pdata?.progress?.by_kpa || {};
        Object.entries(byKpa).forEach(([code, stats]) => {
          const section = kpaSectionMap[code];
          if (!section) return;
          if (stats.expected > 0 && stats.completed >= stats.expected) {
            section.classList.add('neon-complete');
            section.classList.add('animate');
            setTimeout(() => {
              try { section.classList.remove('animate'); } catch (e) {}
            }, 800);
          }
        });
      })
      .catch(() => {});
  } catch (e) {
    console.warn('Could not fetch KPA month progress', e);
  }
}

function renderPAExpectationsTable(tasks) {
  const tbody = $("paExpectationsTableBody");
  if (!tbody) return;
  
  tbody.innerHTML = "";
  
  if (!Array.isArray(tasks) || tasks.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="no-data">No expectations loaded. Import Task Agreement first.</td></tr>';
    return;
  }
  
  tasks.forEach(task => {
    const row = document.createElement("tr");
    const months = (task.months || []).join(", ");
    const hints = (task.evidence_hints || []).join(", ");
    const outputs = task.outputs || "N/A";
    
    row.innerHTML = `
      <td>${task.kpa_code || 'N/A'}</td>
      <td>${task.title || 'N/A'}</td>
      <td>${months}</td>
      <td>${task.cadence || 'N/A'}</td>
      <td>${task.minimum_count || 0}</td>
      <td>${task.stretch_count || 0}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">${outputs}</td>
      <td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;">${hints}</td>
    `;
    
    tbody.appendChild(row);
  });
}

$("rebuildExpBtn")?.addEventListener("click", async () => {
  vampBusy("Rebuilding expectations from contract...");
  
  try {
    const res = await fetch("/api/expectations/rebuild", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        staff_id: $("staffId").value,
        year: $("cycleYear").value
      })
    });
    
    if (!res.ok) throw new Error("Rebuild failed");
    
    const data = await res.json();
    vampSpeak(`Rebuilt ${data.tasks_count} tasks across ${data.kpas_count} KPAs.`);
    log(`Expectations rebuilt: ${data.tasks_count} tasks`);
    
    // Reload expectations
    setTimeout(() => loadExpectations(), 500);
  } catch (e) {
    vampSpeak("Could not rebuild expectations.");
    log("Rebuild error: " + e.message);
    console.error("Rebuild error:", e);
  }
});

$("checkMonthStatusBtn")?.addEventListener("click", () => checkMonthStatus());

async function checkMonthStatus() {
  const monthKey = $("currentMonthSelect").value;
  const staffId = $("staffId").value;
  
  vampBusy("Analyzing month completion status…");
  
  try {
    const res = await fetch("/api/expectations/check-month", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        staff_id: staffId,
        month: monthKey
      })
    });
    
    if (!res.ok) throw new Error("Month check failed");
    
    const data = await res.json();
    
    const statusPill = $("monthStatusPill");
    const reviewBox = $("monthReviewBox");
    
    // Build visual per-task progress display
    const taskStatusHtml = (data.task_status || [])
      .filter(t => t.minimum_required > 0)
      .map(t => {
        const progress = Math.min(100, (t.evidence_count / t.minimum_required) * 100);
        const statusClass = t.met ? 'ok' : 'bad';
        const statusIcon = t.met ? '✓' : '⚠';
        return `
          <div style="margin-bottom:12px;padding:8px;background:var(--panel);border-radius:4px;border-left:3px solid ${t.met ? 'var(--green)' : 'var(--red)'};">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
              <span style="font-weight:600;color:var(--text);">${statusIcon} ${t.kpa_code}: ${t.title}</span>
              <span class="pill ${statusClass}">${t.evidence_count}/${t.minimum_required}</span>
            </div>
            <div style="width:100%;height:6px;background:var(--panel-dark);border-radius:3px;overflow:hidden;">
              <div style="width:${progress}%;height:100%;background:${t.met ? 'var(--green)' : 'var(--purple)'};transition:width 0.3s;"></div>
            </div>
          </div>
        `;
      }).join('');
    
    if (data.complete) {
      statusPill.textContent = `Complete ✓ (${data.tasks_met}/${data.tasks_total})`;
      statusPill.className = "pill ok";
      reviewBox.innerHTML = `
        <div style="color:#8ff0b2;font-weight:bold;margin-bottom:12px;">✓ Month Complete</div>
        <div style="margin-bottom:12px;">${data.message || 'All expectations for this month have been met.'}</div>
        <div style="font-weight:600;margin-bottom:8px;">Task Progress:</div>
        ${taskStatusHtml || '<div class="muted">No task details available</div>'}
      `;
      vampSpeak(`${monthKey} is complete! All ${data.tasks_met} tasks met.`);
    } else {
      statusPill.textContent = `Incomplete ⚠️ (${data.tasks_met}/${data.tasks_total})`;
      statusPill.className = "pill bad";
      reviewBox.innerHTML = `
        <div style="color:#ff6b9d;font-weight:bold;margin-bottom:12px;">⚠️ Month Incomplete</div>
        <div style="margin-bottom:12px;">${data.message || 'Some expectations are not yet met.'}</div>
        <div style="padding:8px;background:var(--panel);border-radius:4px;margin-bottom:12px;color:var(--red);">
          <strong>Missing:</strong> ${data.missing || 'Upload more evidence to meet requirements.'}
        </div>
        <div style="font-weight:600;margin-bottom:8px;">Task Progress:</div>
        ${taskStatusHtml || '<div class="muted">No task details available</div>'}
      `;
      vampSpeak(`This month needs more evidence. ${data.tasks_met} of ${data.tasks_total} tasks complete.`);
    }
    
    log(`Month ${monthKey} status: ${data.complete ? 'Complete' : 'Incomplete'}`);
  } catch (e) {
    vampSpeak("Could not check month status.");
    log("Month check error: " + e.message);
  }
}

/* ============================================================
   SCAN FLOW — FILE UPLOAD & AI CLASSIFICATION
============================================================ */

// Store pending scan data for lock explanation modal
let pendingScanData = null;

$("scanUploadBtn")?.addEventListener("click", async () => {
  const files = $("scanFiles").files;
  if (files.length === 0) {
    vampSpeak("Please select files to scan.");
    return;
  }
  
  const targetTaskId = $("scanTargetTaskId")?.value;
  const lockToTask = $("scanLockToTask")?.checked;
  
  // If locking to task, show explanation modal first
  if (lockToTask && targetTaskId) {
    // Store scan parameters for later
    pendingScanData = {
      files: files,
      targetTaskId: targetTaskId,
      month: $("scanMonth").value,
      useBrain: $("scanUseBrain").checked,
      useContextual: $("scanUseContextual").checked
    };
    
    // Open explanation modal
    openLockExplanationModal(files, targetTaskId);
    return;  // Don't proceed with scan yet
  }
  
  // Regular scan (not locked)
  await performScan(files, targetTaskId, null, false);
});

async function performScan(files, targetTaskId, userExplanation, isLocked) {
  vampBusy(`Scanning ${files.length} files…`);
  $("scanStatus").textContent = "Scanning…";
  scanLog(`Starting scan of ${files.length} files...`);

  const abortController = new AbortController();
  currentScanAbortController = abortController;
  
  const fd = new FormData();
  for (let i = 0; i < files.length; i++) {
    fd.append("files", files[i]);
  }
  fd.append("staff_id", $("staffId").value);
  fd.append("month", $("scanMonth").value);
  fd.append("use_brain", $("scanUseBrain").checked);
  fd.append("use_contextual", $("scanUseContextual").checked);

  if (targetTaskId) {
    fd.append("target_task_id", targetTaskId);
  }
  
  // Lock-to-task mode with user explanation
  if (isLocked && targetTaskId) {
    fd.append("asserted_mapping", "true");
    if (userExplanation) {
      fd.append("user_explanation", userExplanation);
    }
  }
  
  try {
    const res = await fetch("/api/scan/upload", {
      method: "POST",
      body: fd,
      signal: abortController.signal
    });
    if (!res.ok) throw new Error("Scan failed");
    
    const data = await res.json();
    currentScanResults = data.results || [];
    
    renderScanResults(currentScanResults);
    
    $("scanStatus").textContent = "Complete";
    $("scanProgress").textContent = `${currentScanResults.length} items scanned`;
    
    vampSpeak(`Scan complete. ${currentScanResults.length} items classified.`);
    scanLog(`Scan complete: ${currentScanResults.length} items processed`);
    log(`Scan complete: ${files.length} files → ${currentScanResults.length} evidence items`);
    
    // Count how many tasks were mapped
    const mappedCount = currentScanResults.reduce((sum, r) => {
      const tasks = r.mapped_tasks;
      if (Array.isArray(tasks)) return sum + tasks.length;
      return sum + (r.mapped_count || 0);
    }, 0);
    if (mappedCount > 0) {
      vampSpeak(`${mappedCount} task mappings created. Refreshing expectations...`);
      // Reload progress and expectations to show updated checkboxes
      setTimeout(() => loadExpectations(), 1000);
    }
    
    // Auto-refresh evidence log for the current month
    try {
      const monthKey = $("currentMonthSelect")?.value;
      loadEvidence(monthKey);
    } catch (e) {
      loadEvidence();
    }

    // Refresh the timeline UI
    updateYearTimeline();
    
    // Close + restore scan section after successful scan
    restoreScanPanelHome({ hide: true });
    clearTargetedScanState();
  } catch (e) {
    if (e.name === "AbortError") {
      $("scanStatus").textContent = "Cancelled";
      $("scanProgress").textContent = "—";
      scanLog("Scan cancelled by user.");
      log("Scan cancelled by user");
      vampSpeak("Scan cancelled.");
      return;
    }
    vampSpeak("Scan failed. Please check the server logs.");
    $("scanStatus").textContent = "Error";
    scanLog(`Error: ${e.message}`);
    log("Scan error: " + e.message);
  } finally {
    if (currentScanAbortController === abortController) {
      currentScanAbortController = null;
    }
  }
}

$("scanStopBtn")?.addEventListener("click", cancelActiveScan);

function cancelActiveScan() {
  const controller = currentScanAbortController;
  const hasStream = !!eventSource;

  if (!controller && !hasStream) {
    vampSpeak("No scan is currently running.");
    return;
  }

  const status = $("scanStatus");
  if (status) status.textContent = "Cancelling…";
  const progress = $("scanProgress");
  if (progress) progress.textContent = "—";
  scanLog("Cancelling scan…");

  if (controller) {
    controller.abort();
  }

  if (hasStream) {
    try {
      eventSource.close();
    } catch (e) {}
    eventSource = null;
    setTimeout(() => connectEventStream(), 1500);
  }
}

function renderScanResults(results) {
  const tbody = $("scanResultsTableBody");
  if (!tbody) return;
  
  tbody.innerHTML = "";
  
  if (results.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="no-data">No scans performed yet. Upload files to begin.</td></tr>';
    return;
  }
  
  results.forEach((item, idx) => {
    const row = document.createElement("tr");
    
    const confidence = item.confidence || 0;
    const confidenceClass = confidence >= 0.7 ? 'confidence-high' : confidence >= 0.5 ? 'confidence-medium' : 'confidence-low';
    const needsResolve = confidence < 0.6;
    
    // Format mapped tasks display
    const mappedTasks = item.mapped_tasks || [];
    const mappedCount = Array.isArray(mappedTasks) ? mappedTasks.length : (item.mapped_count || 0);
    let mappedTasksHtml = `<span style="color:var(--grey-muted);">${mappedCount} tasks</span>`;
    
    if (Array.isArray(mappedTasks) && mappedTasks.length > 0) {
      const taskList = mappedTasks.map(t => 
        `<div style="font-size:10px;color:var(--text);">• ${t.task_id}: ${t.title} (${(t.confidence * 100).toFixed(0)}%)</div>`
      ).join('');
      mappedTasksHtml = `
        <div style="cursor:pointer;" title="Click to expand" onclick="this.querySelector('.task-details').style.display=this.querySelector('.task-details').style.display==='none'?'block':'none';">
          <span style="color:var(--green);font-weight:bold;">🔗 ${mappedCount}</span>
          <div class="task-details" style="display:none;margin-top:4px;padding:4px;background:var(--panel-dark);border-radius:2px;">
            ${taskList}
          </div>
        </div>
      `;
    } else if (mappedCount === 0) {
      mappedTasksHtml = '<span style="color:var(--red);">⚠️ 0</span>';
    }
    
    row.innerHTML = `
      <td>${item.date || new Date().toLocaleDateString()}</td>
      <td>${item.file || 'N/A'}</td>
      <td>${item.kpa || 'Unknown'}</td>
      <td>${item.task || 'N/A'}</td>
      <td>${item.tier || 'N/A'}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">${item.impact_summary || 'N/A'}</td>
      <td class="${confidenceClass}">${(confidence * 100).toFixed(0)}%</td>
      <td>${mappedTasksHtml}</td>
      <td>
        ${needsResolve ? `<button class="btn-small" onclick="openResolveModal(${idx})">🔧 Resolve</button>` : '<span style="color:#8ff0b2;">✓</span>'}
      </td>
    `;
    
    tbody.appendChild(row);
  });
  
  // Update insights
  const lowConfidence = results.filter(r => (r.confidence || 0) < 0.6).length;
  const insights = $("scanInsights");
  if (insights) {
    insights.innerHTML = `
      <div style="margin-bottom:8px;">✓ ${results.length} items scanned</div>
      <div style="margin-bottom:8px;">⚠️ ${lowConfidence} items need review</div>
      <div>Average confidence: ${(results.reduce((sum, r) => sum + (r.confidence || 0), 0) / results.length * 100).toFixed(1)}%</div>
    `;
  }
}

$("scanRefreshEvidenceBtn")?.addEventListener("click", () => loadEvidence());

/* ============================================================
   EVIDENCE TAB
============================================================ */

async function loadEvidence(monthKey = null) {
  vampBusy("Loading stored evidence…");

  try {
    let data = null;

    if (monthKey) {
      // Use the progress endpoint to fetch evidence for a specific month
      const year = $("cycleYear").value;
      const staff = $("staffId").value;
      const res = await fetch(`/api/progress?staff_id=${staff}&year=${year}&month=${monthKey}`);
      if (!res.ok) throw new Error("Failed to load evidence for month");
      data = await res.json();
      data = data.evidence ? { evidence: data.evidence } : { evidence: [] };
    } else {
      const res = await fetch(`/api/evidence?staff_id=${$("staffId").value}`);
      if (!res.ok) throw new Error("Failed to load evidence");
      data = await res.json();
    }

    let evidence = data.evidence || [];

    // Merge recent scan results so the UI shows mappings immediately
    try {
      if (Array.isArray(currentScanResults) && currentScanResults.length > 0) {
        const byId = {};
        evidence.forEach(ev => { if (ev && ev.evidence_id) byId[ev.evidence_id] = ev; });

        currentScanResults.forEach(scan => {
          const sid = scan.evidence_id || null;
          const sf = scan.file || scan.filename || scan.file_name || null;
          const sm = scan.month || scan.month_bucket || null;

          if (sid && byId[sid]) {
            byId[sid].mapped_tasks = scan.mapped_tasks || byId[sid].mapped_tasks || [];
            byId[sid].mapped_count = scan.mapped_count !== undefined ? scan.mapped_count : (byId[sid].mapped_tasks || []).length;
            byId[sid].recent_scan = true;
          } else if (sf) {
            const match = evidence.find(ev => (ev.filename === sf || ev.file === sf) && (!sm || ev.month === sm));
            if (match) {
              match.mapped_tasks = scan.mapped_tasks || match.mapped_tasks || [];
              match.mapped_count = scan.mapped_count !== undefined ? scan.mapped_count : (match.mapped_tasks || []).length;
              match.recent_scan = true;
            } else if (sm) {
              evidence.unshift({
                evidence_id: sid || (`scan_${Math.random().toString(36).slice(2,9)}`),
                date: scan.date || new Date().toISOString().split('T')[0],
                filename: sf,
                file_path: scan.file_path || '',
                kpa: scan.kpa_code || scan.kpa || '',
                month: sm,
                task: scan.task || '',
                task_id: scan.task_id || '',
                mapped_tasks: scan.mapped_tasks || [],
                mapped_count: scan.mapped_count !== undefined ? scan.mapped_count : (scan.mapped_tasks || []).length,
                tier: scan.tier || '',
                impact_summary: scan.impact_summary || scan.summary || '',
                confidence: scan.confidence !== undefined ? scan.confidence : 0.0,
                recent_scan: true
              });
            }
          }
        });
      }
    } catch (e) {
      console.warn('Could not merge scan results into evidence view', e);
    }

    // Render using the shared renderer (evidence log table)
    const rendered = renderEvidenceLogTable(evidence);

    // Fallback: legacy container if the new table is absent
    if (!rendered) {
      const legacyContainer = $("evidenceTable");
      if (legacyContainer) {
        if (evidence.length === 0) {
          legacyContainer.innerHTML = '<div style="padding:20px;text-align:center;color:var(--grey-dim);">No evidence stored yet. Scan files to begin.</div>';
        } else {
          legacyContainer.innerHTML = `
            <div style="margin-bottom:10px;font-size:13px;color:var(--grey-muted);">
              Total evidence items: ${evidence.length}
            </div>
            <table class="vamp-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>File</th>
                  <th>KPA</th>
                  <th>Task</th>
                  <th>Impact</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                ${evidence.map(e => {
                  const conf = e.confidence || 0;
                  const confClass = conf >= 0.7 ? 'confidence-high' : conf >= 0.5 ? 'confidence-medium' : 'confidence-low';
                  return `
                    <tr>
                      <td>${e.date || 'N/A'}</td>
                      <td>${e.filename || e.file || 'N/A'}</td>
                      <td>${e.kpa || 'N/A'}</td>
                      <td>${e.task || 'N/A'}</td>
                      <td style="max-width:250px;">${e.impact_summary || 'N/A'}</td>
                      <td class="${confClass}">${(conf * 100).toFixed(0)}%</td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          `;
        }
      }
    }

    vampIdle();
    log(`Evidence loaded: ${evidence.length} items`);
  } catch (e) {
    vampSpeak("Could not load evidence.");
    log("Evidence error: " + e.message);
  } finally {
    // Ensure we always return to idle state even if the DOM didn't match or an error occurred
    try { if (currentVampState !== 'idle') vampIdle(); } catch (e) {}
  }
}

$("evidenceReloadBtn")?.addEventListener("click", () => loadEvidence());

/* ============================================================
   REPORT GENERATION
============================================================ */

$("genPABtn")?.addEventListener("click", async () => {
  vampBusy("Forging your Performance Agreement…");

  try {
    const res = await fetch(`/api/report/generate?staff_id=${$("staffId").value}&year=${$("cycleYear").value}&export=true`);
    
    if (!res.ok) throw new Error("Report generation failed");
    
    const data = await res.json();

    // Render PA in table format
    renderPAReportTable(data);
    
    const reportBox = $("reportBox");
    if (reportBox) {
      reportBox.innerHTML = `
        <div class="pill ok" style="margin-bottom:10px;">✓ PA Generated: ${data.title || 'Performance Agreement'}</div>
        <div style="color:var(--grey-muted);font-size:12px;">
          ✓ ${data.rows?.length || 0} KPAs included<br/>
          ${data.excel_path ? `✓ Saved to: ${data.excel_path.split('/').pop()}` : ''}
        </div>
      `;
    }
    
    vampSpeak("Your Performance Agreement is complete.");
    log(`PA generated: ${data.rows?.length || 0} KPAs`);
  } catch (e) {
    vampSpeak("The report could not be generated.");
    log("Report error: " + e.message);
  }
});

function renderPAReportTable(paData) {
  const tbody = $("paExpectationsTableBody");
  if (!tbody) return;
  
  tbody.innerHTML = "";
  
  if (!paData.rows || paData.rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="no-data">No PA data. Import TA first.</td></tr>';
    return;
  }
  
  paData.rows.forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong style="color:var(--purple);">${row.kpa_name}</strong></td>
      <td style="white-space:pre-wrap;font-size:11px;">${row.outputs || '-'}</td>
      <td style="white-space:pre-wrap;font-size:11px;">${row.kpis || '-'}</td>
      <td>${row.weight.toFixed(2)}%</td>
      <td>${row.hours.toFixed(1)}</td>
      <td style="white-space:pre-wrap;font-size:10px;">${row.outcomes || '-'}</td>
      <td style="text-align:center;">${row.active}</td>
    `;
    tbody.appendChild(tr);
  });
}

/* ============================================================
   MODALS — AI GUIDANCE & CLASSIFICATION RESOLUTION
============================================================ */

function openAIGuidance(taskId) {
  const modal = $("aiGuidanceModal");
  
  if (!modal) {
    vampSpeak("Error: AI guidance modal not found.");
    return;
  }
  let task = null;

  // Search strategy: try multiple sources since tasks can have different IDs
  
  let debugSteps = [];
  // 1. Try current month view first (most likely to match)
  if (window.currentByMonth) {
    const monthSelect = $("currentMonthSelect");
    const currentMonth = monthSelect ? monthSelect.value : null;
    if (currentMonth) {
      const monthData = window.currentByMonth[currentMonth];
      const monthTasks = Array.isArray(monthData) ? monthData : (monthData?.tasks || []);
      task = monthTasks.find(t => t.id === taskId || t.task_id === taskId || t._baseId === taskId || t._canonicalId === taskId);
      debugSteps.push({step: 'currentMonth', found: !!task, taskId, available: monthTasks.map(t => t.id || t.task_id || t._baseId || t.title)});
    }
  }

  // 2. Try base expectations by ID
  if (!task) {
    task = currentExpectations.find(e => e.id === taskId || e.task_id === taskId || e.task === taskId);
    debugSteps.push({step: 'baseExpectations', found: !!task, taskId});
  }

  // 3. Try finding by hashed_ids in base tasks
  if (!task && currentExpectations) {
    task = currentExpectations.find(e => {
      if (e.hashed_ids && typeof e.hashed_ids === 'object') {
        return Object.values(e.hashed_ids).includes(taskId);
      }
      return false;
    });
    debugSteps.push({step: 'hashedIds', found: !!task, taskId});
  }

  // 4. Search all months in by_month data, with all possible ID fields
  if (!task && window.expectationsData && window.expectationsData.by_month) {
    for (const [monthKey, monthData] of Object.entries(window.expectationsData.by_month)) {
      const monthTasks = Array.isArray(monthData) ? monthData : (monthData?.tasks || []);
      task = monthTasks.find(t => t.id === taskId || t.task_id === taskId || t._baseId === taskId || t._canonicalId === taskId);
      debugSteps.push({step: 'allMonths', monthKey, found: !!task, taskId, available: monthTasks.map(t => t.id || t.task_id || t._baseId || t.title)});
      if (task) break;
    }
  }

  // 4b. Use top-level id_map provided by backend to resolve hashed -> base ids
  if (!task && window.expectationsData && window.expectationsData._id_map) {
    const idMap = window.expectationsData._id_map || {};
    const baseId = idMap[taskId];
    debugSteps.push({step: 'id_map_lookup', found: !!baseId, baseId, taskId});
    if (baseId) {
      task = currentExpectations.find(e => e.id === baseId || e.task_id === baseId);
      if (task) {
        // annotate so subsequent flows know the canonical hashed id used
        task._canonicalId = task._canonicalId || taskId;
      }
    }
  }

  // 5. Fallback: try to find by title if all else fails (last resort, for debugging)
  if (!task && window.currentByMonth) {
    const monthSelect = $("currentMonthSelect");
    const currentMonth = monthSelect ? monthSelect.value : null;
    if (currentMonth) {
      const monthData = window.currentByMonth[currentMonth];
      const monthTasks = Array.isArray(monthData) ? monthData : (monthData?.tasks || []);
      const maybeTask = monthTasks.find(t => (t.title && taskId && t.title === taskId));
      debugSteps.push({step: 'fallbackTitle', found: !!maybeTask, taskId, available: monthTasks.map(t => t.title)});
      if (maybeTask) {
        task = maybeTask;
      }
    }
  }

  if (!task) {
    // Debug info for developers, and log to logs tab if available
    let debugMsg = `Could not find that task. TaskId: ${taskId}`;
    debugMsg += `\nDebug steps:\n` + debugSteps.map(s => JSON.stringify(s)).join('\n');
    if (window.appendLog) {
      window.appendLog(debugMsg, 'error');
    }
    if ($('logsTabContent')) {
      const logDiv = document.createElement('div');
      logDiv.style.color = '#ff6b9d';
      logDiv.style.fontSize = '12px';
      logDiv.style.marginBottom = '8px';
      logDiv.textContent = debugMsg;
      $('logsTabContent').appendChild(logDiv);
    }
    console.warn(debugMsg);
    vampSpeak("Could not find that task.");
    return;
  }
  
  // Store the task globally so it can be sent with the AI request
  currentAIGuidanceTask = task;
  
  const contextDiv = $("aiTaskContext");
  if (contextDiv) {
    // Handle both PA expectations format and monthly task format
    const taskTitle = task.title || task.task || task.output || "Unknown task";
    const kpaInfo = task.kpa_name || task.kpa || task.kpa_code || "Unknown KPA";
    const goalInfo = task.goal || task.outputs || task.what_to_do || "";
    const weightInfo = task.weight !== undefined ? `${task.weight}%` : "N/A";
    
    contextDiv.innerHTML = `
      <strong>${taskTitle}</strong><br/>
      KPA: ${kpaInfo}<br/>
      ${goalInfo ? `Goal: ${goalInfo}<br/>` : ''}
      ${task.weight !== undefined ? `Weight: ${weightInfo}` : ''}
    `;
  }
  
  modal?.classList.add("active");
  $("aiGuidanceInput")?.focus();
  
  log(`Opened AI guidance for: ${task.title || task.task || taskId}`);
}

function openResolveModal(resultIndex) {
  const item = currentScanResults[resultIndex];
  if (!item) return;
  
  currentResolveItem = { ...item, index: resultIndex };
  
  const modal = $("resolveModal");
  $("resolveFileName").textContent = item.file || 'Unknown file';
  $("resolveInitialClass").textContent = `AI classified as: ${item.kpa || 'Unknown'} (${(item.confidence * 100).toFixed(0)}% confidence)`;
  
  modal?.classList.add("active");
  $("resolveKpaSelect")?.focus();
  
  log(`Opened resolve modal for: ${item.file}`);
}

function closeModal(modalId) {
  const modal = $(modalId);
  modal?.classList.remove("active");
  
  // Clear AI guidance task when AI modal closes
  if (modalId === "aiGuidanceModal") {
    currentAIGuidanceTask = null;
  }
}

// AI Guidance submission
$("submitGuidanceBtn")?.addEventListener("click", async () => {
  const question = $("aiGuidanceInput")?.value.trim();
  if (!question) return;
  
  vampBusy("Consulting VAMP…");
  
  try {
    const res = await fetch("/api/ai/guidance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        context: collectContext()
      })
    });
    
    if (!res.ok) throw new Error("AI guidance failed");
    
    const data = await res.json();
    
    const responseSection = $("aiGuidanceResponse");
    const responseDiv = responseSection?.querySelector(".modal-response");
    
    if (responseDiv) {
      responseDiv.textContent = data.guidance || data.answer || "No guidance available.";
      responseSection.style.display = "block";
    }
    
    vampSpeak("I have provided guidance in the modal.");
    log("AI guidance received");
  } catch (e) {
    vampSpeak("Could not get AI guidance. Ensure Ollama is running.");
    log("AI guidance error: " + e.message);
  }
});

// Classification resolution
$("submitResolveBtn")?.addEventListener("click", async () => {
  if (!currentResolveItem) return;
  
  const kpa = $("resolveKpaSelect")?.value;
  const explanation = $("resolveExplanation")?.value.trim();
  
  if (!kpa || !explanation) {
    vampSpeak("Please select a KPA and provide an explanation.");
    return;
  }
  
  vampBusy("Saving resolved classification…");
  
  try {
    const res = await fetch("/api/evidence/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file: currentResolveItem.file,
        original_kpa: currentResolveItem.kpa,
        resolved_kpa: kpa,
        explanation,
        staff_id: $("staffId").value
      })
    });
    
    if (!res.ok) throw new Error("Resolution failed");
    
    // Update the scan results
    currentScanResults[currentResolveItem.index].kpa = kpa;
    currentScanResults[currentResolveItem.index].confidence = 1.0;
    currentScanResults[currentResolveItem.index].status = "Resolved";
    
    renderScanResults(currentScanResults);
    closeModal("resolveModal");
    
    vampSpeak("Classification resolved and saved.");
    log(`Resolved: ${currentResolveItem.file} → ${kpa}`);
    
    currentResolveItem = null;
  } catch (e) {
    vampSpeak("Could not save the resolution.");
    log("Resolution error: " + e.message);
  }
});

/* ============================================================
   SERVER-SENT EVENTS (REAL-TIME SCAN FEEDBACK)
============================================================ */

let eventSource = null;

function connectEventStream() {
  if (eventSource) return;
  
  try {
    eventSource = new EventSource("/api/scan/events");
    
    eventSource.onmessage = (e) => {
      const data = JSON.parse(e.data);
      
      if (data.type === "file_scanned") {
        scanLog(`✓ Scanned: ${data.file}`);
        $("scanProgress").textContent = `${data.current || 0} / ${data.total || 0}`;
      }
      
      if (data.type === "classification") {
        scanLog(`→ ${data.file}: ${data.kpa} (${(data.confidence * 100).toFixed(0)}%)`);
      }
      
      if (data.type === "needs_clarification") {
        vampSpeak("This evidence is unclear. Please check the scan results.");
        scanLog(`⚠️ Low confidence: ${data.file}`);
      }
      
      if (data.type === "scan_finished") {
        $("scanStatus").textContent = "Complete";
        vampSpeak("Evidence scan complete.");
        scanLog("Scan finished");
      }
      
      if (data.type === "error") {
        scanLog(`❌ Error: ${data.message}`);
      }
    };
    
    eventSource.onerror = () => {
      log("Event stream disconnected");
      eventSource = null;
    };
  } catch (e) {
    log("Could not connect event stream: " + e.message);
  }
}

/* ============================================================
   SCAN SECTION TOGGLE (IN EXPECTATIONS TAB)
============================================================ */

$("scanEvidenceBtn")?.addEventListener("click", () => {
  const section = $("scanEvidenceSection");
  if (!section) return;

  const isVisible = section.style.display !== "none";
  if (isVisible) {
    restoreScanPanelHome({ hide: true });
    clearTargetedScanState();
    return;
  }

  // Prefer showing inline under the first KPA of the currently selected month
  const monthKey = $("currentMonthSelect")?.value;
  let host = null;
  if (monthKey) {
    host = document.querySelector(`#monthlyExpectationsContainer [id^="scanHost-${monthKey}-"]`);
  }

  if (host) {
    attachScanPanelTo(host);
  } else {
    rememberScanPanelHome();
    section.style.display = "block";
  }

  vampSpeak("Upload your evidence files and I'll classify them for you.");
});

$("closeScanSection")?.addEventListener("click", () => {
  restoreScanPanelHome({ hide: true });
  clearTargetedScanState();
});

/* ============================================================
   EVIDENCE LOG WITH FILTERING
============================================================ */

async function loadEvidenceLog(monthFilter = 'all') {
  try {
    const staffId = $("staffId")?.value;
    const year = $("cycleYear")?.value;

    if (!staffId || !year) {
      vampSpeak("Please enrol your profile first.");
      return;
    }
    
    const res = await fetch(`/api/progress?staff_id=${staffId}&year=${year}`);
    if (!res.ok) throw new Error("Could not load evidence log");
    
    const data = await res.json();
    const evidence = data.evidence || [];
    
    // Filter by month if specified
    const filtered = monthFilter === 'all' 
      ? evidence 
      : evidence.filter(e => e.month === monthFilter);
    
    renderEvidenceLogTable(filtered);
    
    log(`Evidence log loaded: ${filtered.length} items${monthFilter !== 'all' ? ` for ${monthFilter}` : ''}`);
  } catch (e) {
    vampSpeak("Could not load evidence log.");
    log("Evidence log error: " + e.message);
  }
}

function renderEvidenceLogTable(evidence) {
  const tbody = $("evidenceLogTableBody");
  if (!tbody) return false;
  
  tbody.innerHTML = "";
  
  if (evidence.length === 0) {
    tbody.innerHTML = '<tr><td colspan="12" class="no-data">No evidence logged yet. Use "Scan Evidence" in the Expectations tab.</td></tr>';
    return true;
  }
  
  evidence.forEach(item => {
    const row = document.createElement("tr");
    if (item.recent_scan) row.classList.add('recent-scan');
    const confidence = item.confidence || 0;
    const confidenceClass = confidence >= 0.7 ? 'confidence-high' : confidence >= 0.5 ? 'confidence-medium' : 'confidence-low';
    const mappedCount = (item.mapped_count !== undefined) ? item.mapped_count : (item.mapped_tasks ? item.mapped_tasks.length : 0);
    const mappedTitles = (item.mapped_tasks || []).map(m => m.title).filter(Boolean).slice(0,3).join(', ');
    const tooltip = mappedCount > 0 ? `Mapped to: ${mappedTitles}` : '';
    
    // Extract rating from brain scorer (0-5 scale)
    const rating = item.rating !== undefined ? item.rating : (item.brain?.rating || null);
    const ratingLabel = item.rating_label || (item.brain?.rating_label || '');
    const ratingDisplay = rating !== null ? `${rating.toFixed(1)} ⭐` : 'N/A';
    const ratingClass = rating >= 4.0 ? 'confidence-high' : rating >= 2.5 ? 'confidence-medium' : rating ? 'confidence-low' : '';
    const ratingTooltip = ratingLabel ? `Rating: ${ratingLabel}` : '';
    
    // Check if enhancement available (low confidence or user requested)
    const isEnhanced = item.meta?.user_enhanced || item.user_enhanced;
    const showEnhanceBtn = confidence < 0.6 && !isEnhanced;
    
    // Format enhanced impact summary for better readability
    let impactDisplay = item.impact_summary || item.impact || 'N/A';
    if (impactDisplay !== 'N/A' && impactDisplay.includes('•')) {
      // Enhanced format detected - add subtle styling
      impactDisplay = impactDisplay
        .replace(/User:/g, '<strong>User:</strong>')
        .replace(/Analysis:/g, '<em>Analysis:</em>')
        .replace(/Rating \d+\.\d+\/5\.0/g, match => `<span style="color:var(--green);">${match}</span>`)
        .replace(/Values:/g, '<span style="color:var(--grey-dim);">Values:</span>')
        .replace(/Policies:/g, '<span style="color:var(--grey-dim);">Policies:</span>')
        .replace(/Tier:/g, '<span style="color:var(--grey-dim);">Tier:</span>');
    } else if (impactDisplay !== 'N/A' && impactDisplay.includes('|')) {
      // Old format with | separators - convert to • for consistency
      impactDisplay = impactDisplay.replace(/\s*\|\s*/g, ' • ');
    }
    
    // Build row with an initial empty cell (we'll replace with expand button)
    row.innerHTML = `
      <td></td>
      <td>${item.date || item.timestamp || 'N/A'}</td>
      <td>${item.filename || item.file || 'N/A'}${isEnhanced ? ' <span class="pill" style="font-size:0.75em;background:var(--accent);color:white;" title="User enhanced">✓</span>' : ''}</td>
      <td>${item.kpa || 'Unknown'}</td>
      <td>${item.month || 'N/A'}</td>
      <td><span class="pill mapped-pill" title="${tooltip}" style="cursor:default;">${mappedCount}</span></td>
      <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;">${item.task || item.title || 'N/A'}</td>
      <td>${item.tier || 'N/A'}</td>
      <td class="${ratingClass}" title="${ratingTooltip}">${ratingDisplay}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;" class="impact-enhanced">${impactDisplay}</td>
      <td class="${confidenceClass}">${(confidence * 100).toFixed(0)}%</td>
      <td></td>
    `;

    // Create expand button in the first cell
    const expandCell = document.createElement('td');
    expandCell.style.width = '36px';
    expandCell.innerHTML = `<button class="expand-btn" aria-label="Expand mapped tasks">▸</button>`;
    row.replaceChild(expandCell, row.children[0]);
    
    // Create actions cell with enhance button
    const actionsCell = document.createElement('td');
    actionsCell.style.whiteSpace = 'nowrap';
    if (showEnhanceBtn) {
      const enhanceBtn = document.createElement('button');
      enhanceBtn.className = 'btn-small secondary';
      enhanceBtn.textContent = '✨ Enhance';
      enhanceBtn.title = 'Improve confidence with your description';
      enhanceBtn.onclick = (e) => {
        e.stopPropagation();
        openEnhanceModal(item);
      };
      actionsCell.appendChild(enhanceBtn);
    } else if (isEnhanced) {
      actionsCell.innerHTML = '<span style="color:var(--grey-dim);font-size:0.85em;">Enhanced ✓</span>';
    }
    row.replaceChild(actionsCell, row.children[row.children.length - 1]);
    
    tbody.appendChild(row);

    // Expanded detail row (hidden by default)
    const detailTr = document.createElement('tr');
    detailTr.className = 'evidence-expanded-row';
    detailTr.style.display = 'none';
    const detailTd = document.createElement('td');
    detailTd.colSpan = 12;
    const mappedListHtml = (item.mapped_tasks || []).map(m => {
      const confText = m.confidence !== undefined ? ` <span class="conf">${Math.round((m.confidence||0)*100)}%</span>` : '';
      const src = m.relevance_source ? ` <em style="color:var(--grey-dim);">(${m.relevance_source})</em>` : '';
      return `<div class="mapped-item">${m.kpa_code || ''} • ${m.title || m.task_id}${confText}${src}</div>`;
    }).join('') || '<div class="muted">No mapped tasks</div>';
    
    // Add full impact summary in expanded view
    const fullImpactHtml = impactDisplay !== 'N/A' 
      ? `<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border-dark);"><div style="font-weight:600;margin-bottom:6px;">Impact Assessment</div><div class="impact-enhanced" style="max-width:none;white-space:normal;line-height:1.6;">${impactDisplay}</div></div>`
      : '';
    
    detailTd.innerHTML = `<div class="evidence-expanded"><div style="font-weight:600;margin-bottom:6px;">Mapped tasks (${mappedCount})</div><div class="mapped-list">${mappedListHtml}</div>${fullImpactHtml}</div>`;
    detailTr.appendChild(detailTd);
    tbody.appendChild(detailTr);

    // Toggle on expand button click
    const expandBtn = row.querySelector('.expand-btn');
    if (expandBtn) {
      expandBtn.addEventListener('click', () => {
        const expanding = detailTr.style.display === 'none';
        detailTr.style.display = expanding ? 'table-row' : 'none';
        if (expanding) {
          detailTr.classList.add('expanded');
          expandBtn.textContent = '▾';
        } else {
          detailTr.classList.remove('expanded');
          expandBtn.textContent = '▸';
        }
      });
    }
  });

  return true;
}

$("evidenceReloadBtn")?.addEventListener("click", () => {
  const monthFilter = $("evidenceMonthFilter")?.value || 'all';
  loadEvidenceLog(monthFilter);
});

$("evidenceMonthFilter")?.addEventListener("change", () => {
  const monthFilter = $("evidenceMonthFilter")?.value || 'all';
  loadEvidenceLog(monthFilter);
});

/* ============================================================
   VOICE FUNCTIONALITY
============================================================ */

let voiceEnabled = false;
let currentAudio = null;

async function checkVoiceStatus() {
  try {
    const resp = await fetch('/api/voice/status');
    const data = await resp.json();
    
    if (data.available) {
      voiceEnabled = true;
      if (data.engine === 'elevenlabs') {
        log("✓ ElevenLabs TTS ready");
      } else if (data.is_trained) {
        log("✓ Voice cloning ready");
      } else {
        log("⚠ Voice available but not trained. Upload voice samples to train.");
      }
    } else {
      log("ℹ Voice TTS not available");
    }
    
    // Update voice status display if on voice tab
    updateVoiceStatusDisplay(data);
    
    return data;
  } catch (e) {
    console.error("Voice status check failed:", e);
    return null;
  }
}

function updateVoiceStatusDisplay(data) {
  const statusContent = $("voiceStatusContent");
  if (!statusContent) return;
  
  if (!data || !data.available) {
    statusContent.innerHTML = `
      <p style="color:var(--red);">❌ Voice cloning not available</p>
      <p style="color:var(--text);font-size:0.9em;margin-top:8px;">
        Install dependencies: pip install torch torchaudio soundfile scipy git+https://github.com/myshell-ai/OpenVoice.git
      </p>
    `;
  } else if (data.is_trained) {
    statusContent.innerHTML = `
      <p style="color:var(--green);">✅ Voice model trained and ready</p>
      <p style="color:var(--text);font-size:0.9em;margin-top:8px;">
        Device: ${data.device || 'Unknown'}<br>
        Voice: ${data.config?.voice_name || 'Default'}<br>
        Training files: ${data.training_files_available}<br>
        Trained: ${data.config?.last_trained || 'Unknown'}
      </p>
    `;
  } else {
    statusContent.innerHTML = `
      <p style="color:var(--yellow);">⚠️ Voice system available but not trained</p>
      <p style="color:var(--text);font-size:0.9em;margin-top:8px;">
        Device: ${data.device || 'Unknown'}<br>
        Training files available: ${data.training_files_available}<br>
        Upload voice samples and train the model to enable voice responses.
      </p>
    `;
  }
}

function playVoiceResponse(audioUrl) {
  if (!audioUrl) {
    // If no voice audio, return to idle after text display
    setTimeout(() => {
      if (currentVampState === VAMP_STATE.SPEAKING) {
        vampIdle();
      }
    }, 3000);
    return;
  }
  
  console.log('Playing ElevenLabs voice:', audioUrl);
  
  // Stop any currently playing audio
  if (window.currentAudio) {
    window.currentAudio.pause();
    window.currentAudio = null;
  }
  
  // Create and play new audio
  window.currentAudio = new Audio(audioUrl);
  window.currentAudio.play().catch(err => {
    console.error("ElevenLabs audio playback failed:", err);
    // Return to idle if playback fails
    setTimeout(() => vampIdle(), 1000);
  });
  
  // Cleanup and return to idle when done
  window.currentAudio.addEventListener('ended', () => {
    console.log('ElevenLabs voice finished playing');
    window.currentAudio = null;
    vampIdle();
  });
  
  // Safety timeout in case ended event doesn't fire
  window.currentAudio.addEventListener('error', (e) => {
    console.error('Audio error:', e);
    window.currentAudio = null;
    setTimeout(() => vampIdle(), 1000);
  });
}

async function uploadVoiceSample(file) {
  const formData = new FormData();
  formData.append('file', file);
  
  try {
    const resp = await fetch('/api/voice/upload', {
      method: 'POST',
      body: formData
    });
    
    const data = await resp.json();
    if (data.success) {
      log(`✓ Uploaded voice sample: ${data.filename}`);
      return true;
    } else {
      log(`✗ Upload failed: ${data.error}`);
      return false;
    }
  } catch (e) {
    log(`✗ Upload error: ${e.message}`);
    return false;
  }
}

async function trainVoice() {
  const statusDiv = $("voiceTrainStatus");
  if (statusDiv) statusDiv.innerHTML = '<p style="color:var(--yellow);">⏳ Training voice model...</p>';
  
  vampBusy("Training voice...");
  
  try {
    const resp = await fetch('/api/voice/train', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voice_name: 'vamp_voice' })
    });
    
    const data = await resp.json();
    if (data.success) {
      log(`✓ Voice trained successfully using ${data.samples_used} samples`);
      voiceEnabled = true;
      
      if (statusDiv) {
        statusDiv.innerHTML = `
          <p style="color:var(--green);">✅ Voice training complete!</p>
          <p style="color:var(--text);font-size:0.9em;">
            Samples used: ${data.samples_used}<br>
            Trained: ${data.trained_at}
          </p>
        `;
      }
      
      // Refresh voice status
      checkVoiceStatus();
      
      vampSpeak("Hello! My voice has been successfully trained.");
      return true;
    } else {
      log(`✗ Training failed: ${data.error}`);
      if (statusDiv) statusDiv.innerHTML = `<p style="color:var(--red);">❌ Training failed: ${data.error}</p>`;
      vampIdle();
      return false;
    }
  } catch (e) {
    log(`✗ Training error: ${e.message}`);
    if (statusDiv) statusDiv.innerHTML = `<p style="color:var(--red);">❌ Error: ${e.message}</p>`;
    vampIdle();
    return false;
  }
}

// Voice tab event handlers
if ($("uploadVoiceSampleBtn")) {
  $("uploadVoiceSampleBtn").addEventListener("click", async () => {
    const input = $("voiceSampleInput");
    const statusDiv = $("voiceUploadStatus");
    
    if (!input.files || input.files.length === 0) {
      if (statusDiv) statusDiv.innerHTML = '<p style="color:var(--red);">Please select voice sample files first.</p>';
      return;
    }
    
    if (statusDiv) statusDiv.innerHTML = '<p style="color:var(--yellow);">⏳ Uploading voice samples...</p>';
    
    let successCount = 0;
    let failCount = 0;
    
    for (let i = 0; i < input.files.length; i++) {
      const file = input.files[i];
      const success = await uploadVoiceSample(file);
      if (success) successCount++;
      else failCount++;
    }
    
    if (statusDiv) {
      if (failCount === 0) {
        statusDiv.innerHTML = `<p style="color:var(--green);">✅ Uploaded ${successCount} voice sample(s)</p>`;
      } else {
        statusDiv.innerHTML = `<p style="color:var(--yellow);">⚠️ Uploaded ${successCount}, failed ${failCount}</p>`;
      }
    }
    
    // Clear file input
    input.value = '';
    
    // Refresh voice status
    checkVoiceStatus();
  });
}

if ($("trainVoiceBtn")) {
  $("trainVoiceBtn").addEventListener("click", trainVoice);
}

if ($("testVoiceBtn")) {
  $("testVoiceBtn").addEventListener("click", async () => {
    const testText = $("voiceTestText")?.value?.trim();
    const playerDiv = $("voiceTestPlayer");
    
    if (!testText) {
      if (playerDiv) playerDiv.innerHTML = '<p style="color:var(--red);">Please enter text to synthesize.</p>';
      return;
    }
    
    if (playerDiv) playerDiv.innerHTML = '<p style="color:var(--yellow);">⏳ Generating speech...</p>';
    
    try {
      const resp = await fetch('/api/voice/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: testText })
      });
      
      const data = await resp.json();
      if (data.success) {
        if (playerDiv) {
          playerDiv.innerHTML = `
            <p style="color:var(--green);">✅ Speech generated</p>
            <audio controls style="width:100%;margin-top:8px;">
              <source src="${data.audio_url}" type="audio/wav">
            </audio>
          `;
        }
        log("✓ Test voice generated");
      } else {
        if (playerDiv) playerDiv.innerHTML = `<p style="color:var(--red);">❌ Failed: ${data.error}</p>`;
        log(`✗ Test voice failed: ${data.error}`);
      }
    } catch (e) {
      if (playerDiv) playerDiv.innerHTML = `<p style="color:var(--red);">❌ Error: ${e.message}</p>`;
      log(`✗ Test voice error: ${e.message}`);
    }
  });
}

/* ============================================================
   INIT
============================================================ */

document.addEventListener("DOMContentLoaded", () => {
  vampIdle();
  log("VAMP interface initialised.");
  log("System ready. Begin by enrolling your profile.");

  // Capture the scan panel's original DOM location so we can move it inline and restore safely
  rememberScanPanelHome();
  
  // Connect event stream for real-time updates
  connectEventStream();
  
  // Check voice status
  checkVoiceStatus();
  
  // Add keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    // Ctrl+K to focus Ask VAMP
    if (e.ctrlKey && e.key === 'k') {
      e.preventDefault();
      vampInput?.focus();
    }
    
    // Escape to close modals
    if (e.key === 'Escape') {
      closeModal('aiGuidanceModal');
      closeModal('resolveModal');
      closeEnhanceModal();
      closeLockExplanationModal();
    }
  });
});

/* ============================================================
   EVIDENCE ENHANCEMENT FUNCTIONALITY
============================================================ */

let currentEnhancingEvidence = null;

function openEnhanceModal(evidence) {
  currentEnhancingEvidence = evidence;
  const modal = $("evidenceEnhanceModal");
  if (!modal) return;
  
  // Populate modal with evidence details
  const fileSpan = $("modalEvidenceFile");
  const kpaSpan = $("modalCurrentKPA");
  const confSpan = $("modalCurrentConf");
  
  if (fileSpan) fileSpan.textContent = evidence.filename || evidence.file || "Unknown";
  if (kpaSpan) kpaSpan.textContent = evidence.kpa || "Unknown";
  if (confSpan) confSpan.textContent = evidence.confidence !== undefined 
    ? `${(evidence.confidence * 100).toFixed(0)}%` 
    : "N/A";
  
  // Clear previous description
  const textarea = $("evidenceDescriptionText");
  if (textarea) textarea.value = "";
  
  // Show modal
  modal.style.display = "block";
  setTimeout(() => textarea?.focus(), 100);
}

function closeEnhanceModal() {
  const modal = $("evidenceEnhanceModal");
  if (modal) modal.style.display = "none";
  currentEnhancingEvidence = null;
}

/* ============================================================
   LOCK EXPLANATION MODAL
============================================================ */

function openLockExplanationModal(files, targetTaskId) {
  const modal = $("lockExplanationModal");
  if (!modal) return;
  
  // Get task title from the dropdown
  const taskSelect = $("scanTargetTaskId");
  const taskTitle = taskSelect?.selectedOptions?.[0]?.text || "Selected task";
  const monthSelect = $("scanMonth");
  const monthText = monthSelect?.selectedOptions?.[0]?.text || "Selected month";
  
  // Update modal content
  $("lockModalTaskTitle").textContent = taskTitle;
  $("lockModalFileCount").textContent = `${files.length} file(s) selected`;
  $("lockModalMonth").textContent = monthText;
  $("lockExplanationText").value = "";

  modal.classList.add("active");
  $("lockExplanationText").focus();
}

function closeLockExplanationModal() {
  const modal = $("lockExplanationModal");
  if (modal) {
    modal.classList.remove("active");
  }
  pendingScanData = null;
}

async function submitLockExplanation() {
  const explanation = $("lockExplanationText")?.value.trim();
  
  if (!explanation || explanation.length < 20) {
    vampSpeak("Please provide a detailed explanation (at least 20 characters).");
    return;
  }
  
  if (!pendingScanData) {
    vampSpeak("No pending scan data found.");
    closeLockExplanationModal();
    return;
  }
  // Ensure files are present and capture targetTaskId defensively
  const files = pendingScanData.files || [];
  const targetTaskId = pendingScanData.targetTaskId || $("scanTargetTaskId")?.value || currentScanTargetTaskId || null;
  if (!files || (files.length === 0)) {
    vampSpeak("No files selected for scan.");
    closeLockExplanationModal();
    pendingScanData = null;
    return;
  }

  // Close modal
  closeLockExplanationModal();

  // Perform the scan with explanation (guard in try/catch to surface errors)
  try {
    await performScan(
      files,
      targetTaskId,
      explanation,
      true // isLocked
    );
  } catch (e) {
    console.error('submitLockExplanation: performScan failed', e);
    vampSpeak('Scan failed. Check server logs.');
  } finally {
    // Clear pending data
    pendingScanData = null;
  }
}

// Close modal on background click
$("lockExplanationModal")?.addEventListener("click", (e) => {
  if (e.target.id === "lockExplanationModal") {
    closeLockExplanationModal();
  }
});

async function submitEnhancement() {
  if (!currentEnhancingEvidence) return;
  
  const textarea = $("evidenceDescriptionText");
  const description = textarea?.value?.trim();
  
  if (!description) {
    alert("Please provide a description of how this evidence covers the expectation.");
    return;
  }
  
  const submitBtn = $("submitEnhanceBtn");
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Enhancing...";
  }
  
  try {
    const response = await fetch("/api/evidence/enhance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        evidence_id: currentEnhancingEvidence.evidence_id,
        staff_id: currentEnhancingEvidence.staff_id || $("staffInput")?.value,
        year: $("cycleYear")?.value || new Date().getFullYear(),
        user_description: description,
        target_task_id: null // Optional: could allow re-targeting
      })
    });
    
    const result = await response.json();
    
    if (result.success) {
      // Show success message
      const improvement = ((result.new_confidence - result.old_confidence) * 100).toFixed(0);
      alert(`✓ Evidence enhanced!\n\nConfidence: ${(result.old_confidence*100).toFixed(0)}% → ${(result.new_confidence*100).toFixed(0)}% (↑${improvement}%)\n${result.reclassified ? `KPA: ${result.old_kpa} → ${result.new_kpa}` : ''}\nMapped tasks: ${result.new_mapped_count}`);
      
      // Reload evidence log
      closeEnhanceModal();
      const monthFilter = $("evidenceMonthFilter")?.value || 'all';
      loadEvidenceLog(monthFilter);
    } else {
      alert("Enhancement failed: " + (result.error || "Unknown error"));
    }
  } catch (error) {
    console.error("Enhancement error:", error);
    alert("Failed to enhance evidence. Check console for details.");
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "✨ Enhance Confidence";
    }
  }
}

/* ============================================================
   KPA SCORE AVERAGING
============================================================ */

async function loadKPAScores(month) {
  const staffId = $("staffInput")?.value;
  if (!staffId) return;
  
  try {
    const response = await fetch(`/api/evidence/kpa-scores?staff_id=${staffId}&month=${month}`);
    const data = await response.json();
    
    if (data.ok && data.scores) {
      // Display KPA scores in UI (you can create a section for this)
      console.log("KPA Scores for", month, data.scores);
      // Example: data.scores = { "KPA1": 4.2, "KPA2": 3.8, "KPA3": 4.5, ...  }
    }
  } catch (error) {
    console.error("Failed to load KPA scores:", error);
  }
}
