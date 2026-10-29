document.getElementById('analyze-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const caseText = document.getElementById('case-input').value.trim();
    if (!caseText) return;
    const button = document.getElementById('submit-btn');
    const spinner = document.getElementById('loading-spinner');
    button.disabled = true;
    spinner.classList.remove('hidden');
    button.querySelector('.btn-text').textContent = 'Analyzing...';
    document.getElementById('results-section').classList.add('hidden');
    const errorPanel = document.getElementById('ui-error');
    errorPanel.classList.add('hidden');
    errorPanel.textContent = '';
    let reportData;
    try {
        const response = await fetch('/analyze', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({case_text: caseText}),
        });
        if (!response.ok) throw new Error('Analysis failed');
        reportData = await response.json();
    } catch (error) {
        console.error(error);
        errorPanel.textContent = 'The analysis request failed. Please try again.';
        errorPanel.classList.remove('hidden');
    } finally {
        button.disabled = false;
        spinner.classList.add('hidden');
        button.querySelector('.btn-text').textContent = 'Analyze Case';
    }
    if (!reportData) return;
    try {
        renderResults(reportData);
    } catch (error) {
        console.error(error);
        document.getElementById('results-section').classList.add('hidden');
        errorPanel.textContent = 'The analysis finished, but this page could not display the report. Refresh the page and try again.';
        errorPanel.classList.remove('hidden');
    }
});

function element(tag, className, value) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (value !== undefined && value !== null) item.textContent = String(value);
    return item;
}

function clear(id) {
    const container = document.getElementById(id);
    container.replaceChildren();
    return container;
}

function addList(parent, heading, values, emptyText) {
    const group = element('div', 'review-group');
    group.appendChild(element('h4', '', heading));
    if (!values.length) group.appendChild(element('p', 'review-muted', emptyText));
    else {
        const list = element('ul', 'review-list');
        values.forEach(value => list.appendChild(element('li', '', value)));
        group.appendChild(list);
    }
    parent.appendChild(group);
}

function sourceLink(source, label) {
    try {
        const url = new URL(source.url);
        if (url.protocol === 'https:' && ['www.nice.org.uk', 'dailymed.nlm.nih.gov'].includes(url.hostname)) {
            const link = element('a', 'source-link', label);
            link.href = url.href;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            return link;
        }
    } catch (_) { /* invalid URLs are shown as text */ }
    return element('span', 'review-muted', `${label} (link unavailable)`);
}

function addCitation(parent, source, role, sourceId) {
    const row = element('div', 'citation-row');
    row.appendChild(element('span', 'citation-role', role));
    if (!source) {
        row.appendChild(element('span', 'review-muted', `Unresolved source: ${sourceId}`));
        parent.appendChild(row);
        return;
    }
    const date = source.updated_date || source.document_date || 'date unavailable';
    row.appendChild(sourceLink(source, `${source.source_name}: ${source.section} (${date})`));
    row.appendChild(element('span', 'citation-meta',
        `${source.document_id}, version ${source.document_version}; ${source.jurisdiction || 'jurisdiction unspecified'}`));
    const excerpt = element('details', 'citation-excerpt');
    excerpt.appendChild(element('summary', '', 'View cited passage'));
    excerpt.appendChild(element('p', '', source.passage));
    row.appendChild(excerpt);
    parent.appendChild(row);
}

function renderClaim(claim, sources) {
    const status = claim.status || 'unverified';
    const card = element('article', `claim-card status-${status}`);
    const header = element('div', 'claim-header');
    header.appendChild(element('p', 'claim-text', claim.text));
    const labels = {supported: 'Supported finding', conflicting: 'Conflicting', unverified: 'Needs verification'};
    header.appendChild(element('span', `claim-status ${status}`, labels[status] || labels.unverified));
    card.appendChild(header);
    if (claim.applies_to) card.appendChild(element('p', 'claim-applies', `Applies to: ${claim.applies_to}`));
    if (claim.conditions?.length) addList(card, 'Conditions', claim.conditions, '');
    if (claim.missing_checks?.length) addList(card, 'Checks still needed', claim.missing_checks, '');
    if (status === 'unverified') card.appendChild(element('p', 'claim-reason',
        claim.unverified_reason || 'Independent verification is incomplete.'));
    if (claim.claim_type === 'treatment' && status !== 'supported') card.appendChild(element('p', 'claim-caution',
        'This is a proposal for clinician review, not a cleared treatment.'));
    const citations = element('div', 'claim-citations');
    [
        ['supporting_evidence_ids', status === 'supported' ? 'Verified source' : 'Proposed supporting source'],
        ['conflicting_evidence_ids', 'Conflicting source'],
        ['unverified_evidence_ids', 'Source awaiting review'],
    ].forEach(([field, role]) => (claim[field] || []).forEach(id => addCitation(citations, sources.get(id), role, id)));
    (claim.rejected_evidence_ids || []).forEach(id =>
        citations.appendChild(element('p', 'review-muted', `Rejected citation: ${id}`)));
    if (!citations.childElementCount) citations.appendChild(element('p', 'review-muted', 'No authoritative citation linked.'));
    card.appendChild(citations);
    return card;
}

function renderClaimList(container, ids, claims, sources, emptyText) {
    const selected = ids.map(id => claims.get(id)).filter(Boolean);
    if (!selected.length) {
        if (emptyText) container.appendChild(element('p', 'review-muted', emptyText));
        return;
    }
    selected.forEach(claim => container.appendChild(renderClaim(claim, sources)));
}

function statusText(status, kind, values) {
    if (status === 'unknown') return `${kind} information was not supplied.`;
    if (status === 'conflicting') return `${kind} statements conflict and need confirmation.`;
    if (status === 'none_reported') return 'No current medicines were reported.';
    if (status === 'no_known_allergies') return 'No known allergies were reported; this is not a safety clearance.';
    return values.length ? values.join(', ') : `${kind} status was reported, but no names were extracted.`;
}

function renderResults(data) {
    const report = data.report || {};
    const context = data.patient_context || {};
    const claims = new Map((report.claims || []).map(item => [item.claim_id, item]));
    const sources = new Map((report.source_passages || []).map(item => [item.id, item]));
    document.getElementById('results-section').classList.remove('hidden');

    const contextPanel = clear('patient-context');
    contextPanel.classList.remove('empty-state');
    [
        ['Age', context.age ?? 'not supplied'], ['Sex', context.sex || 'not supplied'],
        ['Allergy status', (context.allergy_status || 'unknown').replaceAll('_', ' ')],
        ['Medication list', (context.medication_list_status || 'unknown').replaceAll('_', ' ')],
    ].forEach(([label, value]) => {
        const row = element('p', 'context-fact');
        row.appendChild(element('strong', '', `${label}: `));
        row.appendChild(document.createTextNode(String(value)));
        contextPanel.appendChild(row);
    });

    const missing = clear('missing-info-list');
    (report.missing_information || []).forEach(item => missing.appendChild(element('li', '', item)));
    if (!missing.childElementCount) missing.appendChild(element('li', '', 'No additional missing facts recorded.'));
    document.getElementById('case-summary').textContent = report.case_summary || 'No case summary available.';
    const counts = report.evidence_completeness || {};
    document.getElementById('evidence-overview').textContent =
        `${counts.supported_claims || 0} supported findings; ${counts.conflicting_claims || 0} conflicting claims; ` +
        `${counts.unverified_claims || 0} claims need verification. These counts are not diagnostic probabilities.`;

    const differential = clear('diagnoses-container');
    const entries = report.differential?.length ? report.differential :
        (report.ranked_diagnoses || []).map((item, index) => ({rank: index + 1, diagnosis: item.diagnosis, diagnostic_claim_ids: []}));
    if (!entries.length) differential.appendChild(element('p', 'review-muted', 'No differential candidates were generated.'));
    entries.forEach(entry => {
        const card = element('article', 'differential-card glass-panel');
        card.appendChild(element('h4', 'differential-title', `${entry.rank}. ${entry.diagnosis}`));
        renderClaimList(card, entry.diagnostic_claim_ids || [], claims, sources,
            'No source-linked diagnostic claim was generated for this candidate.');
        differential.appendChild(card);
    });
    if (report.unassigned_diagnostic_claim_ids?.length) {
        const other = element('article', 'differential-card glass-panel');
        other.appendChild(element('h4', 'differential-title', 'Other diagnostic claims'));
        renderClaimList(other, report.unassigned_diagnostic_claim_ids, claims, sources, '');
        differential.appendChild(other);
    }
    renderClaimList(clear('investigations-list'), report.investigation_claim_ids || [], claims,
        sources, 'No source-linked investigation was proposed.');
    renderClaimList(clear('treatments-list'), report.treatment_claim_ids || [], claims,
        sources, 'No source-linked treatment option was proposed.');

    const safetyPanel = clear('medication-safety');
    const safety = report.medication_safety || {};
    addList(safetyPanel, 'Current medicines', [statusText(safety.medication_list_status || 'unknown',
        'Medication', safety.current_medications || [])], '');
    addList(safetyPanel, 'Allergies', [statusText(safety.allergy_status || 'unknown',
        'Allergy', safety.allergies || [])], '');
    const warningIds = safety.warning_claim_ids || [];
    const warningTexts = new Set(warningIds.map(id => claims.get(id)?.text).filter(Boolean));
    const findings = (safety.findings || []).filter(item => !warningTexts.has(item.description));
    if (!findings.length && !warningIds.length) safetyPanel.appendChild(element('p', 'claim-caution',
        'No verified medication warning was found by this limited check. Medication safety has not been established.'));
    findings.forEach(finding => {
        const item = element('article', `safety-finding ${finding.verification_status || 'unverified'}`);
        item.appendChild(element('p', 'safety-label', finding.verification_status === 'supported'
            ? 'Label-backed warning' : 'Unverified safety concern'));
        item.appendChild(element('p', '', finding.description));
        if (finding.source_passage_id) addCitation(item, sources.get(finding.source_passage_id),
            'Safety source', finding.source_passage_id);
        safetyPanel.appendChild(item);
    });
    renderClaimList(safetyPanel, warningIds, claims, sources, '');

    const limitations = clear('limitations-list');
    addList(limitations, 'Review before use',
        [...new Set([...(report.limitations || []), ...(report.verification_failures || [])])],
        'No limitations recorded.');
    document.getElementById('report-disclaimer').textContent = report.disclaimer || 'This is a research prototype.';
}
