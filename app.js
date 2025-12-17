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

/* ============================================================
   VAMP AGENT CONTROL
============================================================ */

const vampVideo = $("vamp-video");
const vampBubbles = $("vamp-bubbles");
const vampInput = $("ask-vamp-input");
const vampBtn = $("ask-vamp-btn");

function vampIdle(text = "Awaiting instruction…") {
  if (vampVideo) {
    vampVideo.pause();
    vampVideo.currentTime = 0;
  }
  pushBubble(text, "idle");
}

function vampSpeak(text) {
  if (vampVideo) {
    vampVideo.currentTime = 0;
    vampVideo.play().catch(() => {});
  }
  pushBubble(text, "speak");
}

function pushBubble(text, mode = "speak") {
  if (!vampBubbles) return;
  const div = document.createElement("div");
  div.className = "vamp-bubble " + mode;
  div.textContent = text;
  vampBubbles.appendChild(div);
  vampBubbles.scrollTop = vampBubbles.scrollHeight;
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

    vampSpeak("Let me consider that…");

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
    } catch (e) {
      vampSpeak(
        "I am unable to reach my cognitive core. Please ensure the local AI service is running."
      );
      log("Ask-VAMP error: " + e.message);
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
  });
});

/* ============================================================
   ENROLMENT FLOW (PRESERVED)
============================================================ */

$("enrolBtn")?.addEventListener("click", async () => {
  vampSpeak("Registering your academic identity…");

  const profile = {
    staff_id: $("staffId").value,
    cycle_year: $("cycleYear").value,
    name: $("name").value,
    position: $("position").value,
    faculty: $("faculty").value,
    manager: $("manager").value
  };

  const res = await fetch("/api/profile/enrol", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile)
  });

  if (res.ok) {
    $("profilePill").textContent = "Profile loaded";
    $("profilePill").classList.remove("bad");
    $("profilePill").classList.add("ok");
    $("stagePill").textContent = "Stage: Profile loaded";
    vampIdle("Your profile is set. Upload your Task Agreement when ready.");
  } else {
    vampSpeak("Enrolment failed. Please review your details.");
  }
});

/* ============================================================
   TASK AGREEMENT IMPORT
============================================================ */

$("taUploadBtn")?.addEventListener("click", async () => {
  const f = $("taFile").files[0];
  if (!f) return;

  vampSpeak("I am reading your Task Agreement. This may take a moment…");

  const fd = new FormData();
  fd.append("file", f);

  const res = await fetch("/api/ta/import", { method: "POST", body: fd });

  if (res.ok) {
    $("taPill").textContent = "TA imported";
    $("chipTA").classList.remove("bad");
    $("chipTA").classList.add("ok");
    $("stagePill").textContent = "Stage: TA imported";
    vampIdle("Your agreed work has been fully understood.");
  } else {
    vampSpeak("I could not interpret the Task Agreement.");
  }
});

/* ============================================================
   SCAN FLOW — VAMP GUIDANCE HOOKS
============================================================ */

$("scanStartBtn")?.addEventListener("click", async () => {
  vampSpeak("I am examining your evidence. Remain patient…");
  $("scanStatus").textContent = "Scanning…";

  const res = await fetch("/api/scan/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      folder: $("scanFolder").value,
      month: $("scanMonth").value,
      use_brain: $("scanUseBrain").checked,
      use_contextual: $("scanUseContextual").checked
    })
  });

  if (!res.ok) {
    vampSpeak("The scan could not be initiated.");
    $("scanStatus").textContent = "Error";
  }
});

/* ============================================================
   SERVER-SENT EVENTS (SCAN FEEDBACK)
============================================================ */

const evt = new EventSource("/api/scan/events");
evt.onmessage = (e) => {
  const data = JSON.parse(e.data);

  if (data.type === "file_scanned") {
    log(`Scanned: ${data.file}`);
  }

  if (data.type === "needs_clarification") {
    vampSpeak(
      "This evidence is unclear. Please specify which Key Performance Area it supports."
    );
  }

  if (data.type === "scan_finished") {
    $("scanStatus").textContent = "Complete";
    vampIdle("Evidence scan complete.");
  }
};

/* ============================================================
   REPORT GENERATION
============================================================ */

$("genPABtn")?.addEventListener("click", async () => {
  vampSpeak("I am forging your Performance Agreement…");

  const res = await fetch("/api/report/generate?period=final");
  const data = await res.json();

  if (data.path) {
    $("reportBox").innerHTML =
      `<div class="pill ok">Generated: ${data.path}</div>`;
    vampIdle("Your Performance Agreement is complete.");
  } else {
    vampSpeak("The report could not be generated.");
  }
});

/* ============================================================
   INIT
============================================================ */

document.addEventListener("DOMContentLoaded", () => {
  vampIdle();
  log("VAMP interface initialised.");
});
