# policy_playbook.md

## NWU Policy Playbook – Performance Management Integration

This document maps NWU policies to their functional impact on academic performance evaluation. Each policy includes:
- **Policy ID**: Internal rule-matching code.
- **Title**: Full name of the NWU policy.
- **Scope**: Relevant KPA(s).
- **Trigger Phrases**: Words or phrases matched in evidence text.
- **Synonyms**: Equivalent or related terms.
- **Severity**: low | medium | high — impacts overall evaluation.
- **Action Guidance**: Automated reasoning and output behavior.
- **Must-Pass**: Boolean indicating critical compliance.

---

### POL-ETH-1: NWU Code of Ethics and Conduct
- **Scope**: KPA1, KPA3, KPA4
- **Trigger Phrases**: plagiarism, ethics violation, research misconduct, confidentiality breach, academic dishonesty, discrimination, harassment, falsification of data
- **Synonyms**: cheating, copying, fabrication, ethical non-compliance, unprofessional conduct, prejudice, integrity lapse, misconduct, bias, inappropriate behavior, conflict of interest, code breach, misconduct hearing
- **Severity**: high
- **Action Guidance**: Critical. Any infraction triggers `must_pass_risks`. Prevent rating above `"needs_review"` without override.
- **Must-Pass**: true

---

### POL-OHS-1: Occupational Health and Safety Policy
- **Scope**: KPA2
- **Trigger Phrases**: OHS compliance, safety training, risk assessment, laboratory hazard, incident report, PPE checklist, workplace safety, emergency procedure
- **Synonyms**: occupational compliance, biohazard, safety regulation, evacuation drill, safe working environment, injury prevention, health inspection, safety awareness
- **Severity**: high
- **Action Guidance**: Required evidence for all physical teaching or research environments. Breach = failure of KPA2.
- **Must-Pass**: true

---

### POL-TL-1: Teaching-Learning Strategy and Policy
- **Scope**: KPA1
- **Trigger Phrases**: STLES, student-centred learning, curriculum development, blended teaching, assessment design, module delivery
- **Synonyms**: instructional design, pedagogy, learning facilitation, course innovation, digital learning, flipped classroom, active learning, eFundi analytics, outcome alignment
- **Severity**: medium
- **Action Guidance**: Use for scoring compliance with best practice. Reward innovation or strong STLES. Flag STLES <60% with `"needs_review"`.
- **Must-Pass**: false

---

### POL-ASSESS-1: Assessment and Moderation Policy
- **Scope**: KPA1
- **Trigger Phrases**: moderation report, rubric, summative assessment, test bank, peer moderation, exam committee
- **Synonyms**: grading standard, marking schema, continuous assessment, assessment cycle, assessment blueprint, internal moderation, external reviewer
- **Severity**: medium
- **Action Guidance**: Confirm that assessments align with NWU norms. Flag lack of moderation or unmoderated final assessments.
- **Must-Pass**: false

---

### POL-RES-1: Research Policy
- **Scope**: KPA3
- **Trigger Phrases**: accredited publication, DHET list, NRF-rated output, research project, grant funding, postgrad supervision
- **Synonyms**: Scopus-indexed, WoS article, output subsidy, research grant, research output report, project funding, scholarly article, citation index
- **Severity**: medium
- **Action Guidance**: Use verified outputs for scoring. Missing grant or publication history may flag `"Partially Achieved"`.
- **Must-Pass**: false

---

### POL-RESETH-2: Research Ethics Policy
- **Scope**: KPA3
- **Trigger Phrases**: ethics clearance, HREC, informed consent, protocol approval, REC, risk to participants
- **Synonyms**: ethics committee, ethical approval, human subject research, consent documentation, animal research protocol, research risk, IRB, participant safety
- **Severity**: high
- **Action Guidance**: Required for any research involving human/animal subjects. No clearance → `must_pass_risks`.
- **Must-Pass**: true (conditional)

---

### POL-MGMT-1: Academic Leadership and Management Charter
- **Scope**: KPA4
- **Trigger Phrases**: programme leader, faculty board, committee service, performance management, strategic leadership, workload oversight
- **Synonyms**: academic governance, head of department, line manager, leadership development, decision-making body, quality assurance, supervisory role
- **Severity**: medium
- **Action Guidance**: Leadership contribution boosts KPA4. Lack of participation in mandated roles may flag `"Not Achieved"` or `"Partially"`.
- **Must-Pass**: false

---

### POL-CE-1: Community Engagement Policy
- **Scope**: KPA5
- **Trigger Phrases**: service learning, outreach project, stakeholder partnership, CE report, registered project, social responsiveness
- **Synonyms**: community partnership, outreach program, engagement initiative, community-university collaboration, local impact, CE portfolio
- **Severity**: medium
- **Action Guidance**: Reward documented CE contribution. Missing registration or evidence = `"Partially Achieved"` for KPA5.
- **Must-Pass**: false

---

### POL-INNOV-1: Innovation and IP Policy
- **Scope**: KPA3, KPA5
- **Trigger Phrases**: IP disclosure, tech transfer, patent filing, prototype, innovation output
- **Synonyms**: invention disclosure, first-of-its-kind, product development, licensing, novel methodology, software application, tech spinout
- **Severity**: medium
- **Action Guidance**: Innovation lifts score and tier. Lack of disclosure when patentable = flag.
- **Must-Pass**: false

---

### POL-WORKLOAD-1: Workload and Task Agreement Policy
- **Scope**: All KPAs
- **Trigger Phrases**: TA ratio, academic workload, task agreement, 40-hour model, role allocation, teaching-research split
- **Synonyms**: job profile, performance contract, duty breakdown, appointment role, hours allocation, academic role ratio
- **Severity**: low
- **Action Guidance**: Use TA context to interpret low scores. E.g., no research OK for 90% teaching appointment.
- **Must-Pass**: false

---

### POL-TRANSFORM-1: Institutional Transformation Framework
- **Scope**: KPA4, KPA5
- **Trigger Phrases**: transformation plan, EDI initiative, equity leadership, inclusive curriculum, mentoring of designated groups
- **Synonyms**: equity, diversity, inclusion, transformation KPIs, representation targets, transformation champion, social justice leadership
- **Severity**: medium
- **Action Guidance**: Bonus for equity-aligned leadership. Absence = neutral.
- **Must-Pass**: false

---

### POL-PROMO-1: Promotion Criteria
- **Scope**: Reference for all KPAs
- **Trigger Phrases**: rank expectation, promotion readiness, benchmark output, portfolio evidence
- **Synonyms**: advancement criteria, academic track, performance threshold, level descriptor, eligibility rubric, promotion dossier
- **Severity**: low
- **Action Guidance**: Use for contextual comparison (e.g., expected output at Senior Lecturer level). Do not penalize below target unless persistent.
- **Must-Pass**: false

---

### POL-LEARN-1: Learning and Development Policy
- **Scope**: KPA1, KPA3, KPA4
- **Trigger Phrases**: CPD, upskilling, training participation, professional development, learning plan
- **Synonyms**: skills development, capacity building, internal training, L&D, coaching, career pathway, induction programme
- **Severity**: low
- **Action Guidance**: Adds bonus for `"Developmental"` tier. Lack of L&D is neutral unless staff is underperforming.
- **Must-Pass**: false

---

### POL-EVAL-1: Evaluation and Moderation Guidelines
- **Scope**: All KPAs
- **Trigger Phrases**: moderation committee, performance rating, evaluation rubric, consistency check, score justification
- **Synonyms**: appraisal, evaluation cycle, performance moderation, review committee, calibration panel
- **Severity**: informational
- **Action Guidance**: Use to validate completeness and consistency of submitted evidence. Mismatch → `"next_steps"` recommendation.
- **Must-Pass**: false

---

### POL-SUPERV-1: Supervision and Postgraduate Training Policy
- **Scope**: KPA3
- **Trigger Phrases**: supervisor training, postgraduate contract, co-supervision, supervision load, graduation tracking
- **Synonyms**: PG supervision, master’s mentoring, doctoral tracking, supervision allocation, research mentoring, thesis completion
- **Severity**: medium
- **Action Guidance**: Essential for KPA3 scoring. Missing PG activity = `"Partially Achieved"` or lower if not explained via workload.
- **Must-Pass**: false

---

### POL-QA-1: Institutional Quality Assurance Framework
- **Scope**: KPA1, KPA4
- **Trigger Phrases**: programme review, accreditation report, quality audit, curriculum approval, QA process
- **Synonyms**: teaching review, academic audit, institutional quality cycle, SAQA/NQF compliance, quality indicators, internal validation
- **Severity**: medium
- **Action Guidance**: Bonus for leadership in QA processes. Absence = neutral unless evidence suggests poor quality.
- **Must-Pass**: false
