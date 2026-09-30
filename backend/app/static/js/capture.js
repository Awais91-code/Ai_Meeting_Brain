(() => {
    const $ = id => document.getElementById(id);

    let sessionId = window.captureSessionId;
    let info, jitsi, recorder, display, mic, context;
    let parts = [], pending = null, pendingName = 'meeting.webm', uploading = false, size = 0;
    let closing = false, joinedRoom = false, recordStarted = 0;
    let joinWatch = null;

    const status = text => { $('status').textContent = text; };
    const headers = () => ({Authorization: `Bearer ${getToken()}`});
    const endpoint = () => `/api/live/${sessionId}`;

    async function api(path, options = {}) {
        const response = await fetch(path, {
            ...options,
            headers: {...headers(), ...options.headers}
        });
        const data = await response.json();
        if (!response.ok) {
            const error = new Error(
                typeof data.detail === 'string'
                    ? data.detail
                    : `Request failed (${response.status})`
            );
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function cleanup() {
        display?.getTracks().forEach(track => track.stop());
        mic?.getTracks().forEach(track => track.stop());
        context?.close();
        display = null;
        mic = null;
        context = null;
    }

    function finish() {
        if (recorder?.state === 'recording') {
            recorder.stop();
            $('stop').disabled = true;
            status('Meeting ended. Uploading recording automatically… Keep this page open.');
        }
    }

    async function endMeeting() {
        if (closing) return;
        closing = true;

        finish();

        if (info?.can_record) {
            try {
                await api(endpoint() + '/end', {method: 'POST'});
            } catch (error) {
                status(`Could not close invitations: ${error.message}. Retry End meeting.`);
                closing = false;
            }
        }

        $('join').disabled = !!info?.can_record;
        $('end-meeting').disabled = closing;
        joinedRoom = false;

        if (closing && info?.can_record && !recordStarted && !pending && !uploading) {
            status('Meeting ended. No audio was captured. Use Upload backup recording if you have a local copy.');
        }
    }

    async function ensureService(startIfNeeded) {
        let service = await api('/api/conference/status');
        $('service-status').textContent = service.message;

        if (service.state === 'ready') return;
        if (!startIfNeeded || !service.managed) throw new Error(service.message);

        await api('/api/conference/start', {method: 'POST'});
        const deadline = Date.now() + 100000;

        while (Date.now() < deadline) {
            $('service-status').textContent = 'Warming up the meeting service…';
            await new Promise(resolve => setTimeout(resolve, 2000));
            service = await api('/api/conference/status');

            if (service.state === 'ready') {
                $('service-status').textContent = service.message;
                return;
            }

            if (
                service.state === 'certificate_error'
                || (service.state === 'offline' && service.message.includes('Docker Desktop'))
            ) {
                throw new Error(service.message);
            }
        }

        throw new Error('Meeting service is still starting. Retry Start meeting.');
    }

    function backup(blob) {
        if ($('download').href) URL.revokeObjectURL($('download').href);
        $('download').href = URL.createObjectURL(blob);
        $('download').download = pendingName;
        $('download').hidden = false;
    }

    async function prepareCapture() {
        if (recorder?.state === 'recording') return;

        if (!navigator.mediaDevices?.getDisplayMedia || !window.MediaRecorder) {
            throw new Error('Automatic recording needs Chrome/Edge on HTTPS or localhost.');
        }

        display = await navigator.mediaDevices.getDisplayMedia({
            video: true,
            audio: true,
            preferCurrentTab: true
        });

        if (!display.getAudioTracks().length) {
            cleanup();
            throw new Error(
                'No tab audio selected. Start meeting again, select this Meeting Brain tab, and enable Share tab audio.'
            );
        }

        try {
            mic = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    sampleRate: 48000
                }
            });

            context = new AudioContext({sampleRate: 48000});
            await context.resume();

            const mix = context.createMediaStreamDestination();
            const compressor = context.createDynamicsCompressor();
            compressor.threshold.value = -6;
            compressor.knee.value = 6;
            compressor.ratio.value = 12;
            compressor.attack.value = 0.003;
            compressor.release.value = 0.25;
            compressor.connect(mix);

            for (const stream of [new MediaStream(display.getAudioTracks()), mic]) {
                const gain = context.createGain();
                gain.gain.value = 0.7;
                context.createMediaStreamSource(stream).connect(gain).connect(compressor);
            }

            const mimeType = [
                'audio/webm;codecs=opus',
                'audio/webm',
                'audio/mp4'
            ].find(type => MediaRecorder.isTypeSupported(type));

            if (!mimeType) {
                throw new Error('This browser cannot record a supported audio format.');
            }

            recorder = new MediaRecorder(mix.stream, {
                mimeType,
                audioBitsPerSecond: 128000
            });

            parts = [];
            size = 0;

            recorder.ondataavailable = event => {
                if (event.data.size) {
                    parts.push(event.data);
                    size += event.data.size;
                }
                if (info && size >= (info.max_audio_mb - 1) * 1024 * 1024) {
                    finish();
                }
            };

            recorder.onstop = () => {
                cleanup();
                pending = new Blob(parts, {type: mimeType});
                parts = [];
                pendingName = mimeType.includes('mp4') ? 'meeting.m4a' : 'meeting.webm';
                backup(pending);
                upload();
            };

            recorder.onerror = () => {
                status('Recorder error. Saving audio captured so far.');
                finish();
            };

            display.getVideoTracks()[0]?.addEventListener('ended', () => {
                if (!closing && info?.can_record) {
                    status('Screen/tab sharing stopped. Ending and saving the meeting automatically…');
                    endMeeting();
                    jitsi?.executeCommand('hangup');
                } else {
                    finish();
                }
            });

            recorder.start(1000);
            recordStarted = Date.now();

            $('stop').disabled = false;
            $('audio-file').disabled = true;
            $('start').hidden = true;
            status('Audio capture started automatically. Connecting to the meeting…');
        } catch (error) {
            cleanup();
            recorder = null;
            recordStarted = 0;
            throw error;
        }
    }

    function update(data) {
        info = data;
        $('results').hidden = !data.meeting_id;
        if (data.meeting_id) $('results').href = `/meetings/${data.meeting_id}`;

        $('join').disabled = !data.can_join;
        $('end-meeting').hidden = !data.can_record || !!data.ended_at;
        $('audio-file').disabled =
            !['draft', 'processing_failed'].includes(data.status) || !!data.meeting_id;
        $('retry-process').hidden =
            data.status !== 'processing_failed' || !data.can_record || !!data.meeting_id;

        if (data.status === 'ready') {
            status('Ready — transcript, notes and chatbot are updated.');
        } else if (data.status === 'processing_failed') {
            status(
                `Processing failed: ${data.processing_error}. ${
                    data.meeting_id
                        ? 'Open the saved meeting and use Reprocess.'
                        : 'Retry transcription or upload a clearer backup recording.'
                }`
            );
        } else if (data.status === 'processing' || data.status === 'saved') {
            status('Recording saved. Transcribing and preparing meeting notes automatically…');
        }
    }

    async function poll() {
        try {
            const data = await api(endpoint());
            update(data);
            if (['processing', 'saved'].includes(data.status)) {
                setTimeout(poll, 4000);
            }
        } catch (error) {
            status(
                `Status check failed: ${error.message}. Your uploaded recording remains saved. Reload to check again.`
            );
        }
    }

    async function upload() {
        if (!pending || uploading) return;

        uploading = true;
        $('retry').hidden = true;

        try {
            const data = new FormData();
            data.append('audio', pending, pendingName);
            await api(endpoint() + '/audio', {method: 'POST', body: data});
            pending = null;
            status('Recording uploaded. Transcription and meeting processing started automatically.');
            poll();
        } catch (error) {
            status(
                `Automatic upload failed: ${error.message}. Your local backup is available below; retry without closing this page.`
            );
            $('retry').hidden = false;
        } finally {
            uploading = false;
        }
    }

    async function attendance(receipt) {
        try {
            await api(endpoint() + '/joined', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({receipt})
            });
            sessionStorage.removeItem('attendance:' + sessionId);
            $('admission-status').textContent = info.can_record
                ? 'You’re live. Only selected employees and teams can join.'
                : 'You’re in. Access to the saved notes is automatic.';
        } catch (error) {
            if (error.status === 403 || error.status === 404) {
                sessionStorage.removeItem('attendance:' + sessionId);
                $('admission-status').textContent =
                    'Attendance could not be saved. Sign in with the selected employee account and rejoin.';
                return;
            }
            $('admission-status').textContent =
                'Saving your attendance… Keep this page open while we retry.';
            setTimeout(() => attendance(receipt), 5000);
        }
    }

    function cancelJoinWatch() {
        if (joinWatch !== null && typeof clearTimeout === 'function') {
            clearTimeout(joinWatch);
        }
        joinWatch = null;
    }

    function showDirectFallback(ticket, message) {
        if (ticket?.join_url) {
            $('direct-join').href = ticket.join_url;
            $('direct-join').hidden = false;
        }
        $('admission-status').textContent =
            message || 'Embedded meeting did not open. Use Open meeting directly.';
    }

    function preferDirectMobileJoin() {
        return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
            || window.matchMedia?.('(max-width: 720px)').matches;
    }

    async function loadJitsiApi(ticket) {
        if (window.JitsiMeetExternalAPI) return;

        await Promise.race([
            new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = `https://${ticket.domain}/external_api.js`;
                script.onload = resolve;
                script.onerror = () => reject(
                    new Error(
                        'The private Jitsi service could not load. The device may need to trust the Meeting Brain development certificate.'
                    )
                );
                document.head.appendChild(script);
            }),
            new Promise((_, reject) =>
                setTimeout(
                    () => reject(new Error('The private Jitsi service took too long to load.')),
                    12000
                )
            )
        ]);
    }

    $('join').onclick = async () => {
        $('join').disabled = true;
        $('direct-join').hidden = true;

        try {
            // The host's Join button is also a valid user gesture for browser
            // capture when returning to an unfinished draft.
            if (info?.can_record && recorder?.state !== 'recording') {
                await prepareCapture();
            }

            await ensureService(info.can_record);
            const ticket = await api(endpoint() + '/admission', {method: 'POST'});
            $('direct-join').href = ticket.join_url || '#';

            // Mobile browsers are much more reliable with Jitsi's full-page
            // interface than with the External API iframe. This also fixes the
            // case where an employee taps a notification but the embedded
            // meeting never appears. The JWT is freshly issued on every tap.
            if (!info.can_record && ticket.join_url && preferDirectMobileJoin()) {
                sessionStorage.setItem('attendance:' + sessionId, ticket.receipt);
                await attendance(ticket.receipt);
                $('admission-status').textContent = 'Opening the meeting securely…';
                window.location.assign(ticket.join_url);
                return;
            }

            try {
                await loadJitsiApi(ticket);
            } catch (error) {
                showDirectFallback(ticket, error.message);
                $('join').disabled = false;
                return;
            }

            jitsi?.dispose();
            closing = false;
            joinedRoom = false;
            $('conference').hidden = false;

            jitsi = new JitsiMeetExternalAPI(ticket.domain, {
                roomName: ticket.room,
                jwt: ticket.jwt,
                configOverwrite: {
                    prejoinConfig: {enabled: false},
                    disableDeepLinking: true,
                    startWithVideoMuted: true
                },
                userInfo: {displayName: ticket.display_name},
                parentNode: $('conference'),
                width: '100%',
                height: '100%'
            });

            cancelJoinWatch();
            joinWatch = setTimeout(() => {
                if (!joinedRoom) {
                    showDirectFallback(
                        ticket,
                        'The embedded meeting has not opened yet. This can happen on a new phone/browser or when the local Jitsi certificate is not trusted. Try Open meeting directly.'
                    );
                    $('join').disabled = false;
                }
            }, 18000);

            jitsi.addListener('videoConferenceJoined', () => {
                cancelJoinWatch();
                joinedRoom = true;
                $('direct-join').hidden = true;
                sessionStorage.setItem('attendance:' + sessionId, ticket.receipt);
                attendance(ticket.receipt);
            });

            jitsi.addListener('videoConferenceLeft', endMeeting);
            jitsi.addListener('readyToClose', endMeeting);
            jitsi.addListener('errorOccurred', () => {
                cancelJoinWatch();
                showDirectFallback(
                    ticket,
                    'Embedded admission failed. Retry Join meeting for a fresh token or open the meeting directly.'
                );
                $('join').disabled = false;
            });

            $('admission-status').textContent =
                'Connecting with a fresh, account-specific meeting token…';
        } catch (error) {
            $('admission-status').textContent = error.message;
            $('join').disabled = false;
            if (info?.can_record && recorder?.state === 'recording' && !sessionId) {
                finish();
            }
        }
    };

    function checkbox(kind, id, title, subtitle = '') {
        const label = document.createElement('label');
        label.className =
            'flex items-center gap-2 p-2 rounded-lg bg-slate-900 border border-slate-800 cursor-pointer';

        const input = document.createElement('input');
        input.type = 'checkbox';
        input.dataset.accessKind = kind;
        input.value = String(id);
        input.addEventListener('change', updateAccessCount);

        const text = document.createElement('span');
        text.className = 'min-w-0 text-xs';

        const strong = document.createElement('strong');
        strong.className = 'block text-slate-200 truncate';
        strong.textContent = title;
        text.append(strong);

        if (subtitle) {
            const small = document.createElement('span');
            small.className = 'block text-slate-500 truncate';
            small.textContent = subtitle;
            text.append(small);
        }

        label.append(input, text);
        return label;
    }

    function selectedAccess() {
        const employeeIds = [...document.querySelectorAll(
            'input[data-access-kind="employee"]:checked'
        )].map(input => Number(input.value));

        const teamIds = [...document.querySelectorAll(
            'input[data-access-kind="team"]:checked'
        )].map(input => Number(input.value));

        return {participant_ids: employeeIds, team_ids: teamIds};
    }

    function updateAccessCount() {
        if (!$('access-count')) return;
        const access = selectedAccess();
        const total = access.participant_ids.length + access.team_ids.length;
        $('access-count').textContent = `${total} selected`;
    }

    async function loadAccessOptions() {
        const [employees, teams] = await Promise.all([
            api('/users/?role=employee'),
            api('/api/teams/')
        ]);

        $('employee-options').replaceChildren();
        for (const employee of employees.filter(item => item.is_active !== false)) {
            $('employee-options').append(
                checkbox('employee', employee.id, employee.name, employee.email)
            );
        }
        if (!$('employee-options').children.length) {
            const empty = document.createElement('p');
            empty.className = 'text-xs text-slate-500';
            empty.textContent = 'No active employees.';
            $('employee-options').append(empty);
        }

        $('team-options').replaceChildren();
        for (const team of teams) {
            $('team-options').append(
                checkbox(
                    'team',
                    team.id,
                    team.name,
                    `${team.active_member_count} active member${team.active_member_count === 1 ? '' : 's'}`
                )
            );
        }
        if (!$('team-options').children.length) {
            const empty = document.createElement('p');
            empty.className = 'text-xs text-slate-500';
            empty.textContent = 'No teams yet. Create them from Team members.';
            $('team-options').append(empty);
        }

        updateAccessCount();
    }

    async function load() {
        const data = await api(endpoint());

        $('create-form').hidden = true;
        $('drafts').hidden = true;
        $('controls').hidden = false;
        $('record-controls').hidden = !data.can_record;
        $('title').textContent = data.title;

        const inviteUrl = new URL(data.invite_path, location.origin).href;
        $('invite').href = inviteUrl;
        $('invite').textContent = inviteUrl;
        $('invite-row').hidden = !data.show_invite;
        $('copy-invite').hidden = !data.show_invite;

        $('language-label').textContent = {
            auto: 'Mixed English / Urdu / Hindi',
            en: 'English',
            ur: 'Urdu',
            hi: 'Hindi'
        }[data.language];

        $('admission-status').textContent = data.conference_configured
            ? (
                data.can_record
                    ? `Only the ${data.selected_employee_count} selected employee(s) and members of ${data.selected_team_count} selected team(s) can join.`
                    : 'You have been selected for this live meeting. Tap Join meeting.'
            )
            : 'Private conferencing is not configured. An administrator must set up JWT-protected Jitsi with guests disabled.';

        status(
            data.can_record
                ? 'Live session ready. Recording starts automatically when you join as host.'
                : 'Meeting invitation ready.'
        );

        update(data);

        const receipt = sessionStorage.getItem('attendance:' + sessionId);
        if (receipt) attendance(receipt);
        if (['processing', 'saved'].includes(data.status)) poll();
    }

    $('create-form').onsubmit = async event => {
        event.preventDefault();

        const button = event.submitter || $('create-form').querySelector('button');
        const uploadOnly = button.value === 'upload';
        button.disabled = true;

        try {
            // This is intentionally the first awaited browser operation so the
            // screen-share prompt is tied to the user's Start meeting click.
            if (!uploadOnly) {
                await prepareCapture();
                await ensureService(true);
            }

            const access = selectedAccess();
            const data = await api('/api/live/', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    title: $('meeting-title').value,
                    language: $('meeting-language').value,
                    vocabulary: $('vocabulary').value,
                    participant_ids: access.participant_ids,
                    team_ids: access.team_ids
                })
            });

            sessionId = data.session_id;
            history.replaceState(null, '', data.invite_path);
            await load();

            if (!uploadOnly) {
                await $('join').onclick();
            } else {
                status(
                    'Choose Upload backup recording below. Access is limited to the selected employees and teams.'
                );
            }
        } catch (error) {
            status(error.message);
            if (!sessionId && recorder?.state === 'recording') {
                finish();
            }
        } finally {
            button.disabled = false;
        }
    };

    $('start').onclick = async () => {
        $('start').disabled = true;
        try {
            await prepareCapture();
        } catch (error) {
            status(error.message);
            $('start').disabled = false;
        }
    };

    $('stop').onclick = async () => {
        await endMeeting();
        jitsi?.executeCommand('hangup');
    };

    $('end-meeting').onclick = async () => {
        await endMeeting();
        jitsi?.executeCommand('hangup');
    };

    $('copy-invite').onclick = async () => {
        try {
            await navigator.clipboard.writeText($('invite').href);
            $('copy-invite').textContent = 'Link copied';
        } catch (_) {
            $('copy-invite').textContent = 'Copy the link above';
        }
    };

    setInterval(() => {
        const recording = recorder?.state === 'recording';
        $('record-timer').hidden = !recording;

        if (recording) {
            const seconds = Math.floor((Date.now() - recordStarted) / 1000);
            $('record-timer').textContent =
                `● REC ${String(Math.floor(seconds / 60)).padStart(2, '0')}:`
                + `${String(seconds % 60).padStart(2, '0')} · ${(size / 1048576).toFixed(1)} MB`;
        }
    }, 1000);

    setInterval(async () => {
        if (!sessionId || !joinedRoom || closing) return;
        try {
            const data = await api(endpoint());
            if (data.ended_at && !info.can_record) {
                joinedRoom = false;
                jitsi?.executeCommand('hangup');
                $('admission-status').textContent =
                    'The host ended this meeting. Your notes will appear when processing finishes.';
            }
        } catch (_) {
            // Conference/recording continue during a transient status failure.
        }
    }, 5000);

    $('retry').onclick = upload;

    $('retry-process').onclick = async () => {
        $('retry-process').hidden = true;
        try {
            await api(endpoint() + '/retry', {method: 'POST'});
            poll();
        } catch (error) {
            status(error.message);
            $('retry-process').hidden = false;
        }
    };

    $('audio-file').onchange = () => {
        const file = $('audio-file').files[0];
        if (!file) return;

        if (file.size > info.max_audio_mb * 1024 * 1024) {
            status(`Maximum upload is ${info.max_audio_mb} MB.`);
            return;
        }

        pending = file;
        pendingName = file.name;
        $('audio-file').disabled = true;
        backup(file);
        upload();
    };

    window.addEventListener('beforeunload', event => {
        if (recorder?.state === 'recording' || pending || uploading) {
            event.preventDefault();
            event.returnValue = '';
        }
    });

    setInterval(async () => {
        try {
            const session = await api('/users/refresh', {method: 'POST'});
            localStorage.setItem('access_token', session.access_token);
        } catch (_) {
            if (recorder?.state === 'recording') {
                status('Recording continues. Sign in in another tab before saving.');
            }
        }
    }, 15 * 60 * 1000);

    (async () => {
        const user = await getCurrentUser();
        if (!user) {
            location.href = '/login?next=' + encodeURIComponent(location.pathname);
            return;
        }

        if (window.captureMeetingId) {
            location.replace(`/meetings/${window.captureMeetingId}`);
            return;
        }

        if (sessionId) {
            await load();
            if (
                new URL(location.href || location.origin + location.pathname)
                    .searchParams.get('join') === '1'
                && info.can_join
            ) {
                await $('join').onclick();
            }
            return;
        }

        api('/api/conference/status')
            .then(service => {
                $('service-status').textContent = service.message;
            })
            .catch(() => {
                $('service-status').textContent =
                    'Service status unavailable. Retry Start meeting.';
            });

        $('create-form').hidden = user.role !== 'admin';

        if (user.role === 'admin') {
            await loadAccessOptions();
        }

        const drafts = await api('/api/live/');
        for (const draft of drafts) {
            const link = document.createElement('a');
            link.className = 'button-secondary';
            link.href = draft.invite_path;
            link.textContent = `${draft.title} · ${draft.status.replaceAll('_', ' ')}`;
            $('draft-list').appendChild(link);
        }
        $('drafts').hidden = !drafts.length;

        status(
            user.role === 'admin'
                ? 'Choose meeting access, then Start meeting. Recording and processing are automatic.'
                : 'Your live meetings appear on the dashboard. Employees never need a raw room link.'
        );
    })().catch(error => status(error.message));
})();
