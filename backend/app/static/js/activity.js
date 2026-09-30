/* Account-scoped announcements. Text is always inserted as text, never HTML. */
(() => {
    const bell = document.getElementById('notification-bell');
    if (!bell) return;
    const panel = document.getElementById('notification-panel');
    const list = document.getElementById('notification-list');
    const live = document.getElementById('live-meetings');
    let busy = false, initialized = false;
    const seen = new Set();
    const node = (tag, text, css) => { const el = document.createElement(tag); el.textContent = text; if(css) el.className = css; return el; };
    async function api(path, method='GET') {
        const token = localStorage.getItem('access_token');
        if (!token) throw new Error('Sign in to see team activity.');
        const response = await fetch(path, {method, headers:{Authorization:`Bearer ${token}`}});
        if (!response.ok) throw new Error('Unable to refresh team activity. Reconnecting…');
        return response.json();
    }
    function target(item) {
        if (item.live_session_id && item.join_available) return '/live/' + encodeURIComponent(item.live_session_id) + '?join=1';
        if (item.meeting_id) return '/meetings/' + Number(item.meeting_id);
        return null;
    }
    function link(item) {
        const a = node('a', item.live_session_id ? 'Join meeting →' : 'Open notes →', 'activity-link');
        a.href = target(item);
        a.onclick = () => { api(`/api/notifications/${item.id}/read`, 'PATCH').catch(()=>{}); };
        return a;
    }
    function toast(item) {
        const container = document.getElementById('activity-toast');
        container.replaceChildren(node('strong', 'Your team is meeting'), node('p', item.message), link(item));
        const dismiss = node('button','Dismiss','button-secondary button-small');
        dismiss.onclick = () => {container.hidden = true;};
        container.append(dismiss);
        container.hidden = false;
        setTimeout(()=>{container.hidden=true;},15000);
    }
    async function refresh() {
        if (busy || document.hidden) return;
        busy = true;
        try {
            const [items, count, sessions] = await Promise.all([
                api('/api/notifications/'), api('/api/notifications/unread-count'), live ? api('/api/live/') : Promise.resolve([])
            ]);
            const badge = document.getElementById('notification-count');
            const unread = count.unread_count ?? count.count ?? 0;
            badge.textContent = unread > 99 ? '99+' : String(unread); badge.hidden = !unread;
            bell.setAttribute('aria-label', `Notifications, ${unread} unread`);
            list.replaceChildren();
            for (const item of items) {
                const row = node('article', '', 'notification-row' + (item.is_read ? '' : ' unread'));
                row.append(node('p',item.message),node('small',new Date(item.created_at).toLocaleString()));
                if (target(item)) row.append(link(item));
                else if (item.live_session_id) row.append(node('small','Meeting ended'));
                if (!item.is_read) {
                    const read = node('button','Mark read','activity-link');
                    read.onclick = async () => {try{await api(`/api/notifications/${item.id}/read`,'PATCH'); await refresh();}catch(e){read.textContent='Retry';}};
                    row.append(read);
                }
                list.append(row);
                if (initialized && !seen.has(item.id) && !item.is_read && item.join_available) toast(item);
                seen.add(item.id);
            }
            if (!items.length) list.append(node('p','You’re all caught up. New meetings and notes will appear here.','empty-note'));
            initialized = true;
            if (live) {
                live.replaceChildren();
                const active = sessions.filter(s=>s.is_live);
                document.getElementById('live-count').textContent = `${active.length} live`;
                for (const s of active) {
                    const card = node('article','','live-card');
                    const details = node('div','');
                    const minutes = Math.max(0,Math.floor((Date.now()-new Date(s.started_at).getTime())/60000));
                    details.append(node('span','● LIVE NOW','live-label'),node('h3',s.title),node('p',`${s.organizer} · ${s.attendee_count} joined · ${minutes} min`));
                    const join = node('a',s.can_record ? 'Return to meeting →' : 'Join meeting →','button-primary');
                    join.href = s.invite_path + '?join=1';
                    card.append(details,join); live.append(card);
                }
                if (!active.length) live.append(node('p','No live meetings right now. When your host starts one, your invitation appears here automatically.','live-empty'));
            }
        } catch(error) {
            if (!initialized) list.replaceChildren(node('p',error.message,'empty-note'));
            if (live) document.getElementById('live-count').textContent = 'Reconnecting…';
        } finally { busy = false; }
    }
    function close() {panel.hidden=true;bell.setAttribute('aria-expanded','false');}
    bell.onclick = () => {panel.hidden=!panel.hidden;bell.setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden) refresh();};
    document.addEventListener('click',e=>{if(!panel.contains(e.target)&&!bell.contains(e.target)) close();});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'){close();bell.focus();}});
    document.getElementById('notifications-read-all').onclick = async () => {
        try {await api('/api/notifications/mark-all-read','PATCH');await refresh();}
        catch(error){list.prepend(node('p',error.message));}
    };
    document.addEventListener('visibilitychange',refresh);
    refresh();setInterval(refresh,5000);
})();
