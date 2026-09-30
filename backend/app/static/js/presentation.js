/* Small, escaped text renderer. Model output is never trusted as HTML. */
(function (root) {
    const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const plain = value => String(value ?? '').replace(/\*\*([^*]+)\*\*/g, '$1').replace(/__([^_]+)__/g, '$1').replace(/`([^`]+)`/g, '$1');
    function inline(text) {
        return escape(text).replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
            .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
            .replace(/`([^`\n]+)`/g, '<code>$1</code>')
            .replace(/\[Source (\d+)\]/g, '<span class="citation">Source $1</span>');
    }
    function richText(value) {
        const lines = String(value ?? '').replace(/\r/g, '').split('\n');
        let html = '', list = false;
        const close = () => { if (list) { html += '</ul>'; list = false; } };
        for (const raw of lines) {
            const line = raw.trim();
            if (!line) { close(); continue; }
            if (/^[-*•]\s+|^\d+[.)]\s+/.test(line)) {
                if (!list) { html += '<ul>'; list = true; }
                html += '<li>' + inline(line.replace(/^([-*•]|\d+[.)])\s+/, '')) + '</li>';
            } else {
                close();
                const heading = /^#{1,6}\s+/.test(line) || /^\*\*[^*]+\*\*:?$/.test(line);
                html += heading ? '<h4>' + inline(line.replace(/^#{1,6}\s+/, '')) + '</h4>' : '<p>' + inline(line) + '</p>';
            }
        }
        close();
        return html;
    }
    const headings = {
        'overview':'Overview', 'summary':'Overview', 'meeting overview':'Overview',
        'main topics discussed':'Discussion', 'main topics':'Discussion', 'key points':'Discussion',
        'key discussion points':'Discussion', 'discussion':'Discussion',
        'important decisions':'Decisions', 'key decisions':'Decisions', 'decisions':'Decisions',
        'important deadlines':'Dates & deadlines', 'key deadlines':'Dates & deadlines', 'deadlines':'Dates & deadlines',
        'important responsibilities':'Responsibilities', 'responsibilities':'Responsibilities',
        'action items':'Action items', 'next steps':'Next steps', 'open questions':'Open questions'
    };
    function summarySections(value) {
        const sections = [];
        let current = null;
        for (const raw of String(value ?? '').replace(/\r/g, '').split('\n')) {
            const line = raw.trim();
            if (!line || /^[-*_]{3,}$/.test(line) || /^```/.test(line)) continue;
            const normalized = plain(line).replace(/^#{1,6}\s*/, '').replace(/:$/, '').trim();
            if (/^(meeting summary|summary of the meeting)\s*:/i.test(normalized)) continue;
            const title = headings[normalized.toLowerCase()];
            const customHeading = /^#{1,6}\s+/.test(line) || /^\*\*[^*]+\*\*:?$/.test(line);
            if (title || customHeading) {
                current = {title: title || normalized, items: []};
                sections.push(current);
            } else {
                if (!current) { current = {title:'Overview', items:[]}; sections.push(current); }
                current.items.push(line.replace(/^([-*•]|\d+[.)])\s+/, ''));
            }
        }
        return sections.filter(s => s.items.length);
    }
    function statusLabel(value) {
        return ({ready:'Ready',processing:'Processing',processing_failed:'Needs attention',uploaded:'Awaiting recording',embedded:'Indexed',chunked:'Indexed',processed:'Ready'})[value] || value || 'Pending';
    }
    root.MeetingUI = {escape, plain, richText, summarySections, statusLabel};
    if (typeof module !== 'undefined') module.exports = root.MeetingUI;
})(typeof window !== 'undefined' ? window : globalThis);
