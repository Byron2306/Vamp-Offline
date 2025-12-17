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

// Global state
let currentProfile = null;
let currentExpectations = [];
let currentScanResults = [];
let currentResolveItem = null;

/* ============================================================
   VAMP AGENT CONTROL — VIDEO STATE MANAGEMENT
============================================================ */

const vampVideo = $("vamp-video");
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
  hideVampOverlay();
  pushBubble(text, "idle");
}

function vampBusy(text = "Analysing…") {
  currentVampState = VAMP_STATE.BUSY;
  if (vampVideo) {
    vampVideo.pause();
    vampVideo.currentTime = 0;
  }
  showVampOverlay(text);
}

function vampSpeak(text) {
  currentVampState = VAMP_STATE.SPEAKING;
  if (vampVideo) {
    vampVideo.loop = true;
    vampVideo.currentTime = 0;
    vampVideo.play().catch(() => {});
  }
  hideVampOverlay();
  pushBubble(text, "speak");
  
  // Auto-return to idle after speaking (simulate reading time)
  setTimeout(() => {
    if (currentVampState === VAMP_STATE.SPEAKING) {
      vampIdle();
    }
  }, 3000 + (text.length * 30)); // ~30ms per character
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
      const res = await fetch("/api/vamp/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          context: collectContext()
        })
      });

      if (!res.ok) throw new Error("VAMP unavailable");

      const data = await res.json();
      vampSpeak(data.answer || "I have nothing further to add.");
      log(`Ask-VAMP: ${q.substring(0, 50)}...`);
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
  return {
    staff_id: $("staffId")?.value || null,
    cycle_year: $("cycleYear")?.value || null,
    stage: $("stagePill")?.textContent || null,
    scan_month: $("scanMonth")?.value || null,
    current_tab: document.querySelector(".tab.active")?.dataset.tab || null,
    expectations_count: currentExpectations.length,
    scan_results_count: currentScanResults.length
  };
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

$("enrolBtn")?.addEventListener("click", async () => {
  vampBusy("Registering your academic identity…");

  const profile = {
    staff_id: $("staffId").value,
    cycle_year: $("cycleYear").value,
    name: $("name").value,
    position: $("position").value,
    faculty: $("faculty").value,
    manager: $("manager").value
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
});

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
      vampSpeak("Your agreed work has been fully understood.");
      log(`TA imported: ${data.tasks_count || 0} tasks found`);
      
      // Auto-load expectations
      setTimeout(() => loadExpectations(), 500);
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
   EXPECTATIONS TAB — TABLE RENDERING
============================================================ */

async function loadExpectations() {
  vampBusy("Loading expectations…");
  
  try {
    const res = await fetch(`/api/expectations?staff_id=${$("staffId").value}&year=${$("cycleYear").value}`);
    
    if (!res.ok) throw new Error("Failed to load expectations");
    
    const data = await res.json();
    currentExpectations = data.expectations || [];
    
    renderExpectationsTable(currentExpectations);
    renderKPAProgress(data.kpa_summary || {});
    
    $("chipExp").textContent = "Expectations ✓";
    $("chipExp").classList.remove("bad");
    $("chipExp").classList.add("ok");
    
    vampSpeak(`Loaded ${currentExpectations.length} expectations across ${Object.keys(data.kpa_summary || {}).length} KPAs.`);
    log(`Expectations loaded: ${currentExpectations.length} tasks`);
  } catch (e) {
    vampSpeak("Could not load expectations. Import a Task Agreement first.");
    log("Expectations error: " + e.message);
  }
}

function renderExpectationsTable(expectations) {
  const tbody = $("expectationsTableBody");
  if (!tbody) return;
  
  tbody.innerHTML = "";
  
  if (expectations.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="no-data">No expectations loaded. Import Task Agreement first.</td></tr>';
    return;
  }
  
  expectations.forEach(exp => {
    const row = document.createElement("tr");
    
    const progress = exp.progress || 0;
    const progressClass = progress >= 80 ? 'confidence-high' : progress >= 50 ? 'confidence-medium' : 'confidence-low';
    
    row.innerHTML = `
      <td>${exp.kpa || 'N/A'}</td>
      <td>${exp.task || 'N/A'}</td>
      <td>${exp.month || 'N/A'}</td>
      <td>${exp.enabler || 'N/A'}</td>
      <td>${exp.goal || 'N/A'}</td>
      <td>${exp.lead_target || 'N/A'}</td>
      <td>${exp.lag_target || 'N/A'}</td>
      <td>${exp.weight || 0}%</td>
      <td>
        <div class="task-progress-bar">
          <div class="task-progress-fill" style="width:${progress}%"></div>
        </div>
        <span class="${progressClass}" style="margin-left:8px;">${progress}%</span>
      </td>
      <td>
        <button class="btn-small" onclick="openAIGuidance('${exp.id || exp.task}')">🤖 Ask AI</button>
      </td>
    `;
    
    tbody.appendChild(row);
  });
}

function renderKPAProgress(kpaSummary) {
  const container = $("kpaProgressContainer");
  if (!container) return;
  
  container.innerHTML = "";
  
  Object.entries(kpaSummary).forEach(([kpa, data]) => {
    const progress = data.progress || 0;
    const completed = data.completed || 0;
    const total = data.total || 0;
    
    const div = document.createElement("div");
    div.className = "kpa-progress";
    div.title = `${completed} of ${total} tasks completed`;
    
    div.innerHTML = `
      <div class="kpa-progress-label">
        <div class="kpa-progress-name">${kpa}</div>
        <div class="kpa-progress-stats">${completed} / ${total} tasks</div>
      </div>
      <div class="kpa-progress-bar-container">
        <div class="kpa-progress-bar" style="width:${progress}%"></div>
        <div class="kpa-progress-text">${progress}%</div>
      </div>
    `;
    
    container.appendChild(div);
  });
}

$("rebuildExpBtn")?.addEventListener("click", () => loadExpectations());
$("refreshProgressBtn")?.addEventListener("click", () => loadExpectations());

/* ============================================================
   SCAN FLOW — FILE UPLOAD & AI CLASSIFICATION
============================================================ */

$("scanUploadBtn")?.addEventListener("click", async () => {
  const files = $("scanFiles").files;
  if (files.length === 0) {
    vampSpeak("Please select files to scan.");
    return;
  }
  
  vampBusy(`Scanning ${files.length} files…`);
  $("scanStatus").textContent = "Scanning…";
  scanLog(`Starting scan of ${files.length} files...`);
  
  const fd = new FormData();
  for (let i = 0; i < files.length; i++) {
    fd.append("files", files[i]);
  }
  fd.append("staff_id", $("staffId").value);
  fd.append("month", $("scanMonth").value);
  fd.append("use_brain", $("scanUseBrain").checked);
  fd.append("use_contextual", $("scanUseContextual").checked);
  
  try {
    const res = await fetch("/api/scan/upload", {
      method: "POST",
      body: fd
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
    
    // Auto-refresh evidence tab
    loadEvidence();
  } catch (e) {
    vampSpeak("Scan failed. Please check the server logs.");
    $("scanStatus").textContent = "Error";
    scanLog(`Error: ${e.message}`);
    log("Scan error: " + e.message);
  }
});

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
    
    row.innerHTML = `
      <td>${item.date || new Date().toLocaleDateString()}</td>
      <td>${item.file || 'N/A'}</td>
      <td>${item.kpa || 'Unknown'}</td>
      <td>${item.task || 'N/A'}</td>
      <td>${item.tier || 'N/A'}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">${item.impact_summary || 'N/A'}</td>
      <td class="${confidenceClass}">${(confidence * 100).toFixed(0)}%</td>
      <td>${item.status || 'Pending'}</td>
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

async function loadEvidence() {
  vampBusy("Loading stored evidence…");
  
  try {
    const res = await fetch(`/api/evidence?staff_id=${$("staffId").value}`);
    
    if (!res.ok) throw new Error("Failed to load evidence");
    
    const data = await res.json();
    const evidence = data.evidence || [];
    
    const container = $("evidenceTable");
    if (!container) return;
    
    if (evidence.length === 0) {
      container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--grey-dim);">No evidence stored yet. Scan files to begin.</div>';
    } else {
      container.innerHTML = `
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
                  <td>${e.file || 'N/A'}</td>
                  <td>${e.kpa || 'N/A'}</td>
                  <td>${e.task || 'N/A'}</td>
                  <td style="max-width:250px;">${e.impact || 'N/A'}</td>
                  <td class="${confClass}">${(conf * 100).toFixed(0)}%</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      `;
    }
    
    vampIdle();
    log(`Evidence loaded: ${evidence.length} items`);
  } catch (e) {
    vampSpeak("Could not load evidence.");
    log("Evidence error: " + e.message);
  }
}

$("evidenceReloadBtn")?.addEventListener("click", () => loadEvidence());

/* ============================================================
   REPORT GENERATION
============================================================ */

$("genPABtn")?.addEventListener("click", async () => {
  vampBusy("Forging your Performance Agreement…");

  try {
    const res = await fetch(`/api/report/generate?staff_id=${$("staffId").value}&period=final`);
    
    if (!res.ok) throw new Error("Report generation failed");
    
    const data = await res.json();

    const reportBox = $("reportBox");
    if (reportBox) {
      reportBox.innerHTML = `
        <div class="pill ok" style="margin-bottom:10px;">Generated: ${data.path || 'report.xlsx'}</div>
        <div style="color:var(--grey-muted);font-size:12px;">
          ✓ ${data.kpas_count || 0} KPAs included<br/>
          ✓ ${data.tasks_count || 0} tasks documented<br/>
          ✓ ${data.evidence_count || 0} evidence items attached
        </div>
      `;
    }
    
    vampSpeak("Your Performance Agreement is complete.");
    log(`Report generated: ${data.path}`);
  } catch (e) {
    vampSpeak("The report could not be generated.");
    log("Report error: " + e.message);
  }
});

/* ============================================================
   MODALS — AI GUIDANCE & CLASSIFICATION RESOLUTION
============================================================ */

function openAIGuidance(taskId) {
  const modal = $("aiGuidanceModal");
  const task = currentExpectations.find(e => e.id === taskId || e.task === taskId);
  
  if (!task) {
    vampSpeak("Could not find that task.");
    return;
  }
  
  const contextDiv = $("aiTaskContext");
  if (contextDiv) {
    contextDiv.innerHTML = `
      <strong>${task.task}</strong><br/>
      KPA: ${task.kpa}<br/>
      Goal: ${task.goal}<br/>
      Weight: ${task.weight}%
    `;
  }
  
  modal?.classList.add("active");
  $("aiGuidanceInput")?.focus();
  
  log(`Opened AI guidance for: ${task.task}`);
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
   INIT
============================================================ */

document.addEventListener("DOMContentLoaded", () => {
  vampIdle();
  log("VAMP interface initialised.");
  log("System ready. Begin by enrolling your profile.");
  
  // Connect event stream for real-time updates
  connectEventStream();
  
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
    }
  });
});
