// ============================================================
// GLOBAL AUTH HELPERS
// ============================================================

function getToken() {
    return localStorage.getItem("access_token");
}


function clearAuth() {
    localStorage.removeItem("access_token");
}


async function getCurrentUser() {
    const token = getToken();

    if (!token) {
        return null;
    }

    try {
        const response = await fetch("/users/me", {
            headers: {
                "Authorization": `Bearer ${token}`,
                "Accept": "application/json"
            }
        });

        if (!response.ok) {
            clearAuth();
            return null;
        }

        return await response.json();

    } catch (error) {
        console.error("Authentication check failed:", error);
        return null;
    }
}


// ============================================================
// LOGIN PAGE
// ============================================================

function loginDestination() {
    const next = new URLSearchParams(location.search).get('next') || '';
    return /^\/live(?:\/[0-9a-f-]{36})?$/.test(next) ? next : '/dashboard';
}

function loginPage() {

    return {

        email: "",
        password: "",

        loading: true,
        error: "",


        async init() {

            const token =
                localStorage.getItem("access_token");


            // --------------------------------------------
            // No token = normal login page
            // --------------------------------------------

            if (!token) {

                this.loading = false;
                return;
            }


            // --------------------------------------------
            // Token exists.
            // Verify it.
            // --------------------------------------------

            try {

                const response =
                    await fetch(
                        "/users/me",
                        {
                            method: "GET",

                            headers: {
                                "Authorization":
                                    `Bearer ${token}`,

                                "Accept":
                                    "application/json"
                            }
                        }
                    );


                // ----------------------------------------
                // Token is valid
                // ----------------------------------------

                if (response.ok) {

                    console.log(
                        "Already logged in. Redirecting..."
                    );

                    window.location.replace(
                        loginDestination()
                    );

                    return;
                }


                // ----------------------------------------
                // Token expired/invalid
                // ----------------------------------------

                localStorage.removeItem(
                    "access_token"
                );

                this.loading = false;


            } catch (error) {

                console.error(
                    "Auth check failed:",
                    error
                );

                // Don't block login if server check fails
                this.loading = false;
            }
        },


        async login() {

            this.loading = true;
            this.error = "";


            try {

                const response =
                    await fetch(
                        "/users/login",
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json",

                                "Accept":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                email: this.email,
                                password: this.password
                            })
                        }
                    );


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Invalid email or password."
                    );
                }


                if (!data.access_token) {

                    throw new Error(
                        "Server did not return an access token."
                    );
                }


                localStorage.setItem(
                    "access_token",
                    data.access_token
                );


                console.log(
                    "Login successful."
                );


                window.location.replace(
                    loginDestination()
                );


            } catch (error) {

                console.error(
                    "Login error:",
                    error
                );

                this.error =
                    error.message ||
                    "Unable to login.";


            } finally {

                this.loading = false;
            }
        }
    };
}

// ============================================================
// DASHBOARD
// ============================================================
function dashboardPage() {
    return {
        user: null,
        meetings: [],
        loading: true,
        error: "",

        creating: false,

        showCreateModal: false,

        pollHandle: null,

        newMeeting: {
            title: "",
            meeting_date: "",
            duration_minutes: "",
            transcript: ""
        },

        async init() {

            const token = getToken();


            // No token
            if (!token) {

                window.location.href = "/login";
                return;
            }


            try {

                // ==========================================
                // GET CURRENT USER
                // ==========================================

                const userResponse = await fetch(
                    "/users/me",
                    {
                        headers: {
                            "Authorization": `Bearer ${token}`,
                            "Accept": "application/json"
                        }
                    }
                );


                if (userResponse.status === 401) {

                    clearAuth();
                    window.location.href = "/login";
                    return;
                }


                if (!userResponse.ok) {

                    throw new Error(
                        "Could not verify authentication."
                    );
                }


                this.user =
                    await userResponse.json();


                // ==========================================
                // GET MEETINGS
                // ==========================================

                const meetingsResponse =
                    await fetch(
                        "/api/meetings/",
                        {
                            headers: {
                                "Authorization":
                                    `Bearer ${token}`,

                                "Accept":
                                    "application/json"
                            }
                        }
                    );


                if (meetingsResponse.status === 401) {

                    clearAuth();
                    window.location.href = "/login";
                    return;
                }


                if (meetingsResponse.status === 403) {

                    throw new Error(
                        "You do not have permission to view meetings."
                    );
                }


                if (!meetingsResponse.ok) {

                    const errorText =
                        await meetingsResponse.text();

                    console.error(
                        "Meetings API error:",
                        errorText
                    );

                    throw new Error(
                        "Could not load meetings."
                    );
                }


                this.meetings =
                    await meetingsResponse.json();

                this.startPolling();


            } catch (error) {

                console.error(error);

                this.error =
                    error.message ||
                    "Could not load dashboard.";


            } finally {

                this.loading = false;


                this.$nextTick(() => {

                    if (
                        typeof lucide !== "undefined"
                    ) {
                        lucide.createIcons();
                    }
                });
            }
        },

        async createMeeting() {

            // Prevent duplicate submissions
            if (this.creating) {
                return;
            }



            // ==========================================
            // ADMIN ONLY
            // ==========================================

            if (!this.user || this.user.role !== "admin") {
                alert("Only administrators can create meetings.");
                return;
            }

            const token = getToken();

            if (!token) {
                window.location.href = "/login";
                return;
            }

            // ==========================================
            // VALIDATION
            // ==========================================

            if (!this.newMeeting.title.trim()) {
                alert("Meeting title is required.");
                return;
            }

            if (!this.newMeeting.meeting_date) {
                alert("Meeting date is required.");
                return;
            }

            const transcript = (this.newMeeting.transcript || "").trim();
            if (!transcript) { alert("Paste a transcript to save a meeting, or use the recording studio to start a live session."); return; }
            this.creating = true;
            try {

                // ======================================
                // STEP 1 — CREATE MEETING
                // ======================================

                const response = await fetch(
                    "/api/meetings/",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type": "application/json",
                            "Authorization": `Bearer ${token}`,
                            "Accept": "application/json"
                        },

                        body: JSON.stringify({
                            title: this.newMeeting.title.trim(),
                            transcript: transcript,

                            meeting_date:
                                new Date(
                                    this.newMeeting.meeting_date
                                ).toISOString(),

                            duration_minutes:
                                this.newMeeting.duration_minutes
                                    ? Number(
                                        this.newMeeting.duration_minutes
                                    )
                                    : null
                        })
                    }
                );

                if (response.status === 401) {

                    clearAuth();

                    window.location.href = "/login";

                    return;
                }

                if (response.status === 403) {

                    throw new Error(
                        "Only administrators can create meetings."
                    );
                }

                const data = await response.json();

                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Could not create meeting."
                    );
                }

                // ======================================
                // STEP 3 — UPDATE UI
                // ======================================

                // Re-fetch from the server instead of unshifting the
                // stale pre-transcript "data" object — otherwise the
                // card would show "Uploaded" even though a transcript
                // was attached and processing has actually started.
                await this.loadMeetings();
                this.startPolling();

                this.newMeeting = {
                    title: "",
                    meeting_date: "",
                    duration_minutes: "",
                    transcript: ""
                };

                this.showCreateModal = false;

                alert(
                    transcript
                        ? "Meeting created. Automatic processing has started."
                        : "Meeting created successfully."
                );

            } catch (error) {

                console.error(
                    "CREATE MEETING ERROR:",
                    error
                );

                alert(
                    error.message ||
                    "Could not create meeting."
                );
            } finally {
                this.creating = false;
            }
        },

        async loadMeetings() {
            const token = getToken();

            const response = await fetch("/api/meetings/", {
                headers: {
                    "Authorization": `Bearer ${token}`
                }
            });

            if (response.status === 401) {
                clearAuth();
                window.location.href = "/login";
                return;
            }

            if (!response.ok) {
                throw new Error("Could not load meetings.");
            }

            this.meetings = await response.json();
        },

        // ======================================
        // REAL-TIME STATUS TRACKING
        // ======================================
        // Polls every 4s while ANY meeting is still "processing", so
        // the card flips to Ready/Failed automatically without the
        // user needing to refresh the page.

        startPolling() {

            if (this.pollHandle) {
                clearInterval(this.pollHandle);
            }

            this.pollHandle = setInterval(async () => {

                // Poll even when currently idle: new webhook meetings may arrive.
                if (!document.hidden && !this.pollInFlight) {
                    this.pollInFlight = true;
                    try {
                        await this.loadMeetings();
                    } catch (error) {
                        console.error("POLL ERROR:", error);
                    } finally { this.pollInFlight = false; }
                }

            }, 4000);
        },

        async deleteMeeting(meetingId) {
            if (!confirm(
                "Are you sure you want to delete this meeting?"
            )) {
                return;
            }

            const token = localStorage.getItem("access_token");

            try {
                const response = await fetch(
                    `/api/meetings/${meetingId}`, {
                    method: "DELETE",
                    headers: {
                        "Authorization": `Bearer ${token}`
                    }
                })
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.detail || "Could not delete meeting."
                    );
                }

                this.meetings = this.meetings.filter(
                    meeting => meeting.id !== meetingId
                );

            } catch (error) {
                this.error = error.message;
            }
        },


        formatDate(date) {

            if (!date) {
                return "Unknown date";
            }

            return new Date(date).toLocaleString(
                [],
                {
                    dateStyle: "medium",
                    timeStyle: "short"
                }
            );
        },


        logout() {

            clearAuth();

            window.location.href = "/login";
        },


    };
}


// ============================================================
// Get Meeting ID from URL HELPER FUNCTION
// ============================================================

function getMeetingIdFromUrl() {
    const parts = window.location.pathname
        .split("/")
        .filter(Boolean);

    const editIndex = parts.indexOf("edit");

    if (editIndex !== -1 && editIndex > 0) {
        return parts[editIndex - 1];
    }

    const meetingsIndex = parts.indexOf("meetings");

    if (
        meetingsIndex !== -1 &&
        parts[meetingsIndex + 1]
    ) {
        return parts[meetingsIndex + 1];
    }

    return null;
}

// ============================================================
// ADMIN PAGE
// ============================================================


function adminPage() {

    return {

        user: null,

        meetings: [],

        loading: true,

        creating: false,

        error: "",

        showCreateModal: false,

        editingMeeting: null,

        showEditModal: false,

        deletingMeeting: null,

        showDeleteModal: false,

        deleting: false,

        // Search / filter / sort (Phase 15)
        searchQuery: "",
        statusFilter: "",
        sortOrder: "newest",

        // Dashboard-style stats (Phase 11)
        stats: {
            total: 0,
            uploaded: 0,
            processing: 0,
            ready: 0,
            processing_failed: 0
        },

        // Real-time status tracking + manual reprocess
        pollHandle: null,
        reprocessingId: null,

        // Participant management (Phase 2)
        showParticipantsModal: false,
        participantsMeeting: null,
        assignedParticipants: [],
        availableEmployees: [],
        selectedEmployeeId: "",
        assignedTeams: [],
        availableTeams: [],
        selectedTeamId: "",
        participantsLoading: false,
        participantActionLoading: false,
        participantsError: "",
        participantsSuccess: "",

        editMeetingData: {
            title: "",
            meeting_date: "",
            duration_minutes: ""
        },

        newMeeting: {
            title: "",
            meeting_date: "",
            duration_minutes: "",
            transcript: ""
        },



        async init() {

            const token =
                localStorage.getItem("access_token");

            if (!token) {
                window.location.href = "/login";
                return;
            }


            try {

                const userResponse =
                    await fetch(
                        "/users/me",
                        {
                            headers: {
                                "Authorization":
                                    `Bearer ${token}`
                            }
                        }
                    );


                if (
                    userResponse.status === 401
                ) {

                    localStorage.removeItem(
                        "access_token"
                    );

                    window.location.href =
                        "/login";

                    return;
                }


                if (!userResponse.ok) {
                    throw new Error(
                        "Could not verify user."
                    );
                }


                this.user =
                    await userResponse.json();


                // ======================================
                // ONLY ADMIN CAN ENTER /admin
                // ======================================

                if (this.user.role !== "admin") {

                    window.location.href =
                        "/dashboard";

                    return;
                }


                // ======================================
                // YOUR EXISTING ADMIN LOADING CODE
                // ======================================

                await this.loadMeetings();
                await this.loadStats();

                this.startPolling();

            } catch (error) {
                console.error(error);

                this.error =
                    error.message ||
                    "Could not load admin page.";

            } finally {

                this.loading = false;

                this.$nextTick(() => {

                    if (
                        typeof lucide !==
                        "undefined"
                    ) {
                        lucide.createIcons();
                    }

                });

            }
        },

        async loadMeetings() {

            const token = getToken();

            if (!token) {
                window.location.href = "/login";
                return;
            }

            try {

                const params = new URLSearchParams();
                if (this.searchQuery) params.set("q", this.searchQuery);
                if (this.statusFilter) params.set("status_filter", this.statusFilter);
                if (this.sortOrder) params.set("sort", this.sortOrder);

                const response =
                    await fetch(
                        `/api/meetings/?${params.toString()}`,
                        {
                            method: "GET",

                            headers: {
                                "Authorization":
                                    `Bearer ${token}`,

                                "Accept":
                                    "application/json"
                            }
                        }
                    );

                if (response.status === 401) {

                    clearAuth();

                    window.location.href = "/login";

                    return;
                }

                if (response.status === 403) {

                    throw new Error(
                        "Administrator access required."
                    );
                }

                const data =
                    await response.json();

                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Could not load meetings."
                    );
                }

                this.meetings =
                    Array.isArray(data)
                        ? data
                        : (data.meetings || []);

            } catch (error) {

                console.error(
                    "LOAD ADMIN MEETINGS ERROR:",
                    error
                );

                this.error =
                    error.message ||
                    "Could not load meetings.";

            }
        },

        async loadStats() {

            const token = getToken();

            try {

                const response = await fetch(
                    "/api/meetings/stats/overview",
                    {
                        headers: {
                            "Authorization": `Bearer ${token}`
                        }
                    }
                );

                if (response.ok) {
                    this.stats = await response.json();
                }

            } catch (error) {
                console.error("LOAD STATS ERROR:", error);
            }
        },

        // ======================================
        // REAL-TIME STATUS TRACKING (Phase 3 UX)
        // ======================================
        // Polls every 4s while ANY meeting is still "processing", so
        // status flips to Ready/Failed automatically without the
        // admin needing to refresh the page. Stops polling once
        // nothing is in-flight, to avoid hammering the API forever.

        startPolling() {

            if (this.pollHandle) {
                clearInterval(this.pollHandle);
            }

            this.pollHandle = setInterval(async () => {

                // Poll even when currently idle: new webhook meetings may arrive.
                if (!document.hidden && !this.pollInFlight) {
                    this.pollInFlight = true;
                    try {
                        await this.loadMeetings();
                        await this.loadStats();
                    } catch (error) { console.error("POLL ERROR:", error); }
                    finally { this.pollInFlight = false; }
                }

            }, 4000);
        },

        async reprocessMeeting(meeting) {

            const token = getToken();
            this.reprocessingId = meeting.id;

            try {

                const response = await fetch(
                    `/api/meetings/${meeting.id}/reprocess`,
                    {
                        method: "POST",
                        headers: { "Authorization": `Bearer ${token}` }
                    }
                );

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || "Could not restart processing.");
                }

                await this.loadMeetings();
                await this.loadStats();

            } catch (error) {
                console.error("REPROCESS ERROR:", error);
                this.error = error.message || "Could not restart processing.";
            } finally {
                this.reprocessingId = null;
            }
        },


        // ======================================
        // PARTICIPANT MANAGEMENT (Phase 2)
        // ======================================

        async openParticipantsModal(meeting) {

            this.participantsMeeting = meeting;
            this.showParticipantsModal = true;
            this.participantsError = "";
            this.participantsSuccess = "";
            this.selectedEmployeeId = "";
            this.selectedTeamId = "";

            await this.loadParticipantsData();
        },

        async loadParticipantsData() {

            const token = getToken();
            const meetingId = this.participantsMeeting.id;
            this.participantsLoading = true;
            this.participantsError = "";

            try {

                const [participantsRes, employeesRes, assignedTeamsRes, teamsRes] = await Promise.all([
                    fetch(`/api/meetings/${meetingId}/participants`, {
                        headers: { "Authorization": `Bearer ${token}` }
                    }),
                    fetch(`/users/?role=employee`, {
                        headers: { "Authorization": `Bearer ${token}` }
                    }),
                    fetch(`/api/meetings/${meetingId}/teams`, {
                        headers: { "Authorization": `Bearer ${token}` }
                    }),
                    fetch(`/api/teams/`, {
                        headers: { "Authorization": `Bearer ${token}` }
                    })
                ]);

                if (!participantsRes.ok) {
                    throw new Error("Could not load participants.");
                }
                if (!employeesRes.ok) {
                    throw new Error("Could not load employees.");
                }
                if (!assignedTeamsRes.ok || !teamsRes.ok) {
                    throw new Error("Could not load team access.");
                }

                this.assignedParticipants = await participantsRes.json();
                const allEmployees = await employeesRes.json();
                this.assignedTeams = await assignedTeamsRes.json();
                const allTeams = await teamsRes.json();

                const assignedIds = new Set(
                    this.assignedParticipants.map(p => p.user_id)
                );

                this.availableEmployees = allEmployees.filter(
                    e => !assignedIds.has(e.id) && e.is_active !== false
                );

                const assignedTeamIds = new Set(
                    this.assignedTeams.map(item => item.team_id)
                );
                this.availableTeams = allTeams.filter(
                    team => !assignedTeamIds.has(team.id)
                );

            } catch (error) {

                console.error("LOAD PARTICIPANTS ERROR:", error);
                this.participantsError = error.message || "Could not load participant data.";

            } finally {
                this.participantsLoading = false;
            }
        },

        async assignParticipant() {

            if (!this.selectedEmployeeId) return;

            const token = getToken();
            const meetingId = this.participantsMeeting.id;
            this.participantActionLoading = true;
            this.participantsError = "";
            this.participantsSuccess = "";

            try {

                const response = await fetch(
                    `/api/meetings/${meetingId}/participants`,
                    {
                        method: "POST",
                        headers: {
                            "Authorization": `Bearer ${token}`,
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            user_id: parseInt(this.selectedEmployeeId, 10)
                        })
                    }
                );

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || "Could not assign employee.");
                }

                this.selectedEmployeeId = "";
                this.participantsSuccess = "Employee assigned successfully.";
                await this.loadParticipantsData();

            } catch (error) {

                console.error("ASSIGN PARTICIPANT ERROR:", error);
                this.participantsError = error.message || "Could not assign employee.";

            } finally {
                this.participantActionLoading = false;
            }
        },

        async removeParticipant(userId) {

            const token = getToken();
            const meetingId = this.participantsMeeting.id;
            this.participantActionLoading = true;
            this.participantsError = "";
            this.participantsSuccess = "";

            try {

                const response = await fetch(
                    `/api/meetings/${meetingId}/participants/${userId}`,
                    {
                        method: "DELETE",
                        headers: { "Authorization": `Bearer ${token}` }
                    }
                );

                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || "Could not remove participant.");
                }

                this.participantsSuccess = "Participant removed.";
                await this.loadParticipantsData();

            } catch (error) {

                console.error("REMOVE PARTICIPANT ERROR:", error);
                this.participantsError = error.message || "Could not remove participant.";

            } finally {
                this.participantActionLoading = false;
            }
        },

        async assignTeam() {
            if (!this.selectedTeamId) return;

            const token = getToken();
            const meetingId = this.participantsMeeting.id;
            this.participantActionLoading = true;
            this.participantsError = "";
            this.participantsSuccess = "";

            try {
                const response = await fetch(
                    `/api/meetings/${meetingId}/teams/${parseInt(this.selectedTeamId, 10)}`,
                    {
                        method: "POST",
                        headers: { "Authorization": `Bearer ${token}` }
                    }
                );
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || "Could not assign team.");
                }
                this.selectedTeamId = "";
                this.participantsSuccess = "Team access added successfully.";
                await this.loadParticipantsData();
            } catch (error) {
                this.participantsError = error.message || "Could not assign team.";
            } finally {
                this.participantActionLoading = false;
            }
        },

        async removeTeam(teamId) {
            const token = getToken();
            const meetingId = this.participantsMeeting.id;
            this.participantActionLoading = true;
            this.participantsError = "";
            this.participantsSuccess = "";

            try {
                const response = await fetch(
                    `/api/meetings/${meetingId}/teams/${teamId}`,
                    {
                        method: "DELETE",
                        headers: { "Authorization": `Bearer ${token}` }
                    }
                );
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || "Could not remove team access.");
                }
                this.participantsSuccess = "Team access removed.";
                await this.loadParticipantsData();
            } catch (error) {
                this.participantsError = error.message || "Could not remove team access.";
            } finally {
                this.participantActionLoading = false;
            }
        },


        openEditModal(meeting) {

            this.editingMeeting = meeting;

            this.editMeetingData = {
                title: meeting.title || "",

                meeting_date:
                    meeting.meeting_date
                        ? new Date(meeting.meeting_date)
                            .toISOString()
                            .slice(0, 16)
                        : "",

                duration_minutes:
                    meeting.duration_minutes || "",

                transcript: meeting.transcript || ""
            };

            this.showEditModal = true;
        },

        openDeleteModal(meeting) {

            this.deletingMeeting = meeting;

            this.showDeleteModal = true;
        },

        async deleteMeeting() {

            if (!this.deletingMeeting) {
                return;
            }

            if (this.deleting) {
                return;
            }

            const token = getToken();

            if (!token) {
                window.location.href = "/login";
                return;
            }

            this.deleting = true;

            try {

                const response = await fetch(
                    `/api/meetings/${this.deletingMeeting.id}`,
                    {
                        method: "DELETE",

                        headers: {
                            "Authorization": `Bearer ${token}`,
                            "Accept": "application/json"
                        }
                    }
                );

                if (response.status === 401) {

                    clearAuth();

                    window.location.href = "/login";

                    return;
                }

                if (response.status === 403) {

                    throw new Error(
                        "Only administrators can delete meetings."
                    );
                }

                const data =
                    await response.json();

                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Could not delete meeting."
                    );
                }

                // Close modal
                this.showDeleteModal = false;

                this.deletingMeeting = null;

                // Reload meetings
                await this.loadMeetings();

                alert("Meeting deleted successfully.");

            } catch (error) {

                console.error(
                    "DELETE MEETING ERROR:",
                    error
                );

                alert(
                    error.message ||
                    "Could not delete meeting."
                );

            } finally {

                this.deleting = false;
            }
        },

        async updateMeeting() {

            if (!this.editingMeeting) {
                return;
            }

            const token = getToken();

            if (!token) {
                window.location.href = "/login";
                return;
            }

            const title =
                (this.editMeetingData.title || "").trim();

            if (!title) {
                alert("Meeting title is required.");
                return;
            }

            if (!this.editMeetingData.meeting_date) {
                alert("Meeting date is required.");
                return;
            }

            try {

                const response = await fetch(
                    `/api/meetings/${this.editingMeeting.id}`,
                    {
                        method: "PUT",

                        headers: {
                            "Content-Type": "application/json",
                            "Authorization": `Bearer ${token}`,
                            "Accept": "application/json"
                        },

                        body: JSON.stringify({

                            title: title,

                            meeting_date:
                                new Date(
                                    this.editMeetingData
                                        .meeting_date
                                ).toISOString(),

                            duration_minutes:
                                this.editMeetingData
                                    .duration_minutes
                                    ? Number(
                                        this.editMeetingData
                                            .duration_minutes
                                    )
                                    : null
                        })
                    }
                );

                if (response.status === 401) {

                    clearAuth();

                    window.location.href = "/login";

                    return;
                }

                if (response.status === 403) {

                    throw new Error(
                        "Only administrators can edit meetings."
                    );
                }

                const data =
                    await response.json();

                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Could not update meeting."
                    );
                }

                // --------------------------------
                // Transcript (only send if changed)
                // --------------------------------

                const newTranscript =
                    (this.editMeetingData.transcript || "").trim();

                const oldTranscript =
                    (this.editingMeeting.transcript || "").trim();

                if (newTranscript !== oldTranscript) {

                    if (!newTranscript) {
                        throw new Error(
                            "Transcript cannot be empty."
                        );
                    }

                    const transcriptResponse = await fetch(
                        `/api/meetings/${this.editingMeeting.id}/transcript`,
                        {
                            method: "PUT",
                            headers: {
                                "Content-Type": "application/json",
                                "Authorization": `Bearer ${token}`
                            },
                            body: JSON.stringify({
                                transcript: newTranscript
                            })
                        }
                    );

                    const transcriptData =
                        await transcriptResponse.json();

                    if (!transcriptResponse.ok) {
                        throw new Error(
                            transcriptData.detail ||
                            "Could not update transcript."
                        );
                    }
                }

                // Refresh meetings from backend
                await this.loadMeetings();
                await this.loadStats();

                // Close modal
                this.showEditModal = false;

                this.editingMeeting = null;

                this.editMeetingData = {
                    title: "",
                    meeting_date: "",
                    duration_minutes: "",
                    transcript: ""
                };

                alert(
                    newTranscript !== oldTranscript
                        ? "Meeting updated. Automatic processing has restarted."
                        : "Meeting updated successfully."
                );

            } catch (error) {

                console.error(
                    "UPDATE MEETING ERROR:",
                    error
                );

                alert(
                    error.message ||
                    "Could not update meeting."
                );
            }
        },

        async createMeeting() {

            // ==========================================
            // ADMIN ONLY
            // ==========================================

            if (!this.user || this.user.role !== "admin") {
                alert("Administrator access required.");
                return;
            }

            // Prevent double submission
            if (this.creating) {
                return;
            }

            const token = getToken();

            if (!token) {
                window.location.href = "/login";
                return;
            }

            // ==========================================
            // VALIDATION
            // ==========================================

            const title =
                (this.newMeeting.title || "").trim();

            const meetingDate =
                this.newMeeting.meeting_date;

            const transcript =
                (this.newMeeting.transcript || "").trim();

            if (!title) {
                alert("Meeting title is required.");
                return;
            }

            if (!meetingDate) {
                alert("Meeting date is required.");
                return;
            }

            if (!transcript) { alert("Paste a transcript to save a meeting, or use the recording studio."); return; }

            // ==========================================
            // START CREATION
            // ==========================================

            this.creating = true;

            try {

                const response = await fetch(
                    "/api/meetings/",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type": "application/json",
                            "Authorization": `Bearer ${token}`,
                            "Accept": "application/json"
                        },

                        body: JSON.stringify({

                            title: title,

                            meeting_date:
                                new Date(
                                    meetingDate
                                ).toISOString(),

                            duration_minutes:
                                this.newMeeting.duration_minutes
                                    ? Number(
                                        this.newMeeting
                                            .duration_minutes
                                    )
                                    : null,

                            transcript:
                                transcript || null
                        })
                    }
                );

                // ======================================
                // AUTH ERROR
                // ======================================

                if (response.status === 401) {

                    clearAuth();

                    window.location.href = "/login";

                    return;
                }

                if (response.status === 403) {

                    throw new Error(
                        "Only administrators can create meetings."
                    );
                }

                // ======================================
                // RESPONSE
                // ======================================

                const data =
                    await response.json();

                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Could not create meeting."
                    );
                }

                // ======================================
                // UPDATE UI
                // ======================================

                this.meetings.unshift(data);

                // ======================================
                // RESET FORM
                // ======================================

                this.newMeeting = {

                    title: "",

                    meeting_date: "",

                    duration_minutes: "",

                    transcript: ""
                };

                // ======================================
                // CLOSE MODAL
                // ======================================

                this.showCreateModal = false;

                // ======================================
                // MESSAGE
                // ======================================

                alert(
                    transcript
                        ? "Meeting created. Automatic processing has started."
                        : "Meeting created successfully."
                );

                // Refresh list so status is accurate
                await this.loadMeetings();

            } catch (error) {

                console.error(
                    "ADMIN CREATE MEETING ERROR:",
                    error
                );

                alert(
                    error.message ||
                    "Could not create meeting."
                );

            } finally {

                this.creating = false;
            }
        },

        formatDate(date) {

            if (!date) {
                return "Unknown date";
            }


            return new Date(date).toLocaleString(
                [],
                {
                    dateStyle: "medium",
                    timeStyle: "short"
                }
            );

        },


        logout() {

            localStorage.removeItem(
                "access_token"
            );

            window.location.href =
                "/login";
        }

    };
}
// ============================================================
// MEETING PAGE
// ============================================================

function meetingPage() {

    return {

        meetingId: null,

        meeting: {},

        messages: [],

        question: "",

        loading: true,

        chatLoading: false,

        error: "",

        showTranscript: false,

        // Admin Properties

        isAdmin: false,

        processing: false,

        processingMessage: "",

        actionMessage: "",

        actionError: "",

        pollHandle: null,


        // ====================================================
        // INITIALIZE
        // ====================================================

        async retryProcessing() {
            this.processing = true;
            this.actionError = "";
            try {
                const response = await fetch(`/api/meetings/${this.meetingId}/reprocess`, {
                    method: "POST", headers: {Authorization: `Bearer ${getToken()}`}
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || "Could not restart processing");
                this.meeting = data;
            } catch (error) { this.actionError = error.message; }
            finally { this.processing = false; }
        },

        async init() {

            this.meetingId =
                window.location.pathname
                    .split("/")
                    .pop();


            const token = getToken();

            const user = await getCurrentUser();

            if (!user) {
                clearAuth();
                window.location.href = "/login";
                return;
            }

            this.isAdmin = user.role === "admin";


            // -----------------------------------------------
            // Authentication
            // -----------------------------------------------

            if (!token) {

                window.location.href = "/login";
                return;
            }


            try {

                // -------------------------------------------
                // Load meeting
                // -------------------------------------------

                await this.loadMeeting(token);

                this.startPolling(token);


                // -------------------------------------------
                // Load previous chat
                // -------------------------------------------

                await this.loadChat(token);


            } catch (error) {

                console.error(error);


                if (
                    error.message ===
                    "AUTH_EXPIRED"
                ) {

                    clearAuth();

                    window.location.href =
                        "/login";

                    return;
                }


                this.error =
                    error.message ||
                    "Could not load meeting.";


            } finally {

                this.loading = false;


                this.$nextTick(() => {

                    if (
                        typeof lucide !== "undefined"
                    ) {
                        lucide.createIcons();
                    }

                    this.scrollChatToBottom();
                });
            }
        },


        // ====================================================
        // LOAD MEETING
        // ====================================================

        async loadMeeting(token) {

            const url =
                `/api/meetings/${this.meetingId}`;


            console.log(
                "Fetching meeting:",
                url
            );


            const response =
                await fetch(
                    url,
                    {
                        method: "GET",

                        headers: {
                            "Authorization":
                                `Bearer ${token}`,

                            "Accept":
                                "application/json"
                        }
                    }
                );


            console.log(
                "Meeting API status:",
                response.status
            );


            // -----------------------------------------------
            // Authentication expired
            // -----------------------------------------------

            if (response.status === 401) {

                throw new Error(
                    "AUTH_EXPIRED"
                );
            }


            // -----------------------------------------------
            // Access denied
            // -----------------------------------------------

            if (response.status === 403) {

                throw new Error(
                    "You do not have access to this meeting."
                );
            }


            // -----------------------------------------------
            // Not found / server error
            // -----------------------------------------------

            if (!response.ok) {

                const text =
                    await response.text();

                console.error(
                    "Meeting API error:",
                    text
                );

                throw new Error(
                    "Could not load meeting."
                );
            }


            // -----------------------------------------------
            // Verify JSON
            // -----------------------------------------------

            const contentType =
                response.headers
                    .get("content-type") || "";


            if (
                !contentType.includes(
                    "application/json"
                )
            ) {

                const text =
                    await response.text();

                console.error(
                    "Expected JSON but received:",
                    text
                );

                throw new Error(
                    "Meeting API returned an invalid response."
                );
            }


            this.meeting =
                await response.json();
        },


        // ====================================================
        // REAL-TIME STATUS TRACKING
        // ====================================================
        // While this meeting is still "processing", poll every 4s so
        // the summary/action items/chat appear automatically once
        // ready — no manual refresh needed.

        startPolling(token) {

            if (this.pollHandle) {
                clearInterval(this.pollHandle);
            }

            this.pollHandle = setInterval(async () => {


                try {
                    await this.loadMeeting(token);
                } catch (error) {
                    console.error("POLL ERROR:", error);
                }

            }, 4000);
        },


        // ====================================================
        // LOAD CHAT HISTORY
        // ====================================================

        async loadChat(token) {

            const response =
                await fetch(
                    `/api/meetings/${this.meetingId}/chat-debug`,
                    {
                        headers: {
                            "Authorization":
                                `Bearer ${token}`,

                            "Accept":
                                "application/json"
                        }
                    }
                );


            if (response.status === 401) {

                throw new Error(
                    "AUTH_EXPIRED"
                );
            }


            if (response.status === 403) {

                throw new Error(
                    "You do not have access to this meeting."
                );
            }


            if (!response.ok) {

                console.error(
                    "Chat history failed:",
                    response.status
                );

                return;
            }


            const data =
                await response.json();


            this.messages =
                data.messages || [];
        },


        // ====================================================
        // ASK QUESTION
        // ====================================================

        async askQuestion() {

            const text =
                this.question.trim();


            if (
                !text ||
                this.chatLoading
            ) {
                return;
            }


            const token =
                getToken();


            if (!token) {

                window.location.href =
                    "/login";

                return;
            }


            // Add user message immediately
            this.messages.push({
                role: "user",
                content: text
            });


            this.question = "";

            this.chatLoading = true;


            this.scrollChatToBottom();


            try {

                const response =
                    await fetch(
                        `/api/meetings/${this.meetingId}/ask`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json",

                                "Authorization":
                                    `Bearer ${token}`,

                                "Accept":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                question: text
                            })
                        }
                    );


                if (
                    response.status === 401
                ) {

                    throw new Error(
                        "AUTH_EXPIRED"
                    );
                }


                if (
                    response.status === 403
                ) {

                    throw new Error(
                        "You do not have access to this meeting."
                    );
                }


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Could not get an answer."
                    );
                }


                this.messages.push({
                    role: "assistant",
                    content: data.answer,
                    sources: data.sources || []
                });


            } catch (error) {

                console.error(
                    "Question error:",
                    error
                );


                if (
                    error.message ===
                    "AUTH_EXPIRED"
                ) {

                    clearAuth();

                    window.location.href =
                        "/login";

                    return;
                }


                this.messages.push({
                    role: "assistant",

                    content:
                        error.message || "Could not process that question. Please retry."
                });


            } finally {

                this.chatLoading = false;


                this.$nextTick(() => {

                    if (
                        typeof lucide !== "undefined"
                    ) {
                        lucide.createIcons();
                    }

                    this.scrollChatToBottom();
                });
            }
        },


        // ====================================================
        // SCROLL CHAT
        // ====================================================

        scrollChatToBottom() {

            this.$nextTick(() => {

                const container =
                    document.getElementById(
                        "chat-container"
                    );


                if (container) {

                    container.scrollTop =
                        container.scrollHeight;
                }
            });
        },


        // ====================================================
        // FORMAT DATE
        // ====================================================

        formatDate(date) {

            if (!date) {
                return "Unknown date";
            }


            return new Date(date)
                .toLocaleString(
                    [],
                    {
                        dateStyle: "medium",
                        timeStyle: "short"
                    }
                );
        },


        // ====================================================
        // LOGOUT
        // ====================================================

        logout() {

            clearAuth();

            window.location.href =
                "/login";
        },

    };
}

// ============================================================
// EDIT MEETING PAGE
// ============================================================

function editMeetingPage() {
    return {
        meetingId: null,

        meeting: {},

        form: {
            title: "",
            meeting_date: "",
            duration_minutes: "",
            transcript: ""
        },

        loading: true,
        saving: false,
        error: "",

        async init() {

            const token =
                localStorage.getItem("access_token");

            if (!token) {
                window.location.href = "/login";
                return;
            }


            // ==========================================
            // CHECK CURRENT USER
            // ==========================================

            try {

                const userResponse = await fetch(
                    "/users/me",
                    {
                        headers: {
                            "Authorization":
                                `Bearer ${token}`
                        }
                    }
                );


                if (userResponse.status === 401) {

                    localStorage.removeItem(
                        "access_token"
                    );

                    window.location.href = "/login";

                    return;
                }


                if (!userResponse.ok) {
                    throw new Error(
                        "Could not verify user."
                    );
                }


                const user =
                    await userResponse.json();


                // ======================================
                // EMPLOYEE → NOT ALLOWED
                // ======================================

                if (user.role !== "admin") {

                    window.location.href =
                        "/dashboard";

                    return;
                }


            } catch (error) {

                console.error(error);

                window.location.href =
                    "/dashboard";

                return;
            }


            // ==========================================
            // NOW CONTINUE WITH YOUR EXISTING CODE
            // ==========================================

            const parts =
                window.location.pathname
                    .split("/")
                    .filter(Boolean);

            const editIndex =
                parts.indexOf("edit");


            if (
                editIndex === -1 ||
                editIndex === 0
            ) {

                this.error =
                    "Invalid meeting URL.";

                this.loading = false;

                return;
            }


            this.meetingId =
                parts[editIndex - 1];


            try {

                const response = await fetch(
                    `/api/meetings/${this.meetingId}`,
                    {
                        headers: {
                            "Authorization":
                                `Bearer ${token}`
                        }
                    }
                );


                if (response.status === 401) {

                    localStorage.removeItem(
                        "access_token"
                    );

                    window.location.href =
                        "/login";

                    return;
                }


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Could not load meeting."
                    );
                }


                this.meeting = data;


                this.form.title =
                    data.title || "";


                this.form.duration_minutes =
                    data.duration_minutes || "";


                this.form.transcript =
                    data.transcript || "";


                if (data.meeting_date) {

                    this.form.meeting_date =
                        this.toDateTimeLocal(
                            data.meeting_date
                        );
                }


            } catch (error) {

                console.error(error);

                this.error =
                    error.message ||
                    "Could not load meeting.";

            } finally {

                this.loading = false;

                this.$nextTick(() => {

                    if (
                        typeof lucide !==
                        "undefined"
                    ) {
                        lucide.createIcons();
                    }

                });

            }
        },
        // ----------------------------------------
        // Convert API date → datetime-local
        // ----------------------------------------

        toDateTimeLocal(dateString) {

            const date =
                new Date(dateString);


            const pad = value =>
                String(value).padStart(2, "0");


            return (
                date.getFullYear() +
                "-" +
                pad(date.getMonth() + 1) +
                "-" +
                pad(date.getDate()) +
                "T" +
                pad(date.getHours()) +
                ":" +
                pad(date.getMinutes())
            );
        },


        // ----------------------------------------
        // Save meeting
        // ----------------------------------------

        async saveMeeting() {

            const token =
                localStorage.getItem(
                    "access_token"
                );


            if (!token) {

                window.location.href =
                    "/login";

                return;
            }


            this.saving = true;


            try {

                // -------------------------------
                // Update basic meeting details
                // -------------------------------

                const meetingResponse =
                    await fetch(
                        `/api/meetings/${this.meetingId}`,
                        {
                            method: "PUT",

                            headers: {
                                "Content-Type":
                                    "application/json",

                                "Authorization":
                                    `Bearer ${token}`
                            },

                            body: JSON.stringify({

                                title:
                                    this.form.title,

                                meeting_date:
                                    new Date(
                                        this.form.meeting_date
                                    ).toISOString(),

                                duration_minutes:
                                    this.form
                                        .duration_minutes
                                        ? Number(
                                            this.form
                                                .duration_minutes
                                        )
                                        : null
                            })
                        }
                    );


                const meetingData =
                    await meetingResponse.json();


                if (!meetingResponse.ok) {

                    throw new Error(
                        meetingData.detail ||
                        "Could not update meeting."
                    );
                }


                // --------------------------------
                // Transcript
                // --------------------------------

                const newTranscript =
                    this.form.transcript.trim();


                const oldTranscript =
                    (this.meeting.transcript || "")
                        .trim();


                // Only send transcript if changed
                if (
                    newTranscript !==
                    oldTranscript
                ) {

                    if (!newTranscript) {

                        throw new Error(
                            "Transcript cannot be empty."
                        );
                    }


                    const transcriptResponse =
                        await fetch(
                            `/api/meetings/${this.meetingId}/transcript`,
                            {
                                method: "PUT",

                                headers: {
                                    "Content-Type":
                                        "application/json",

                                    "Authorization":
                                        `Bearer ${token}`
                                },

                                body: JSON.stringify({
                                    transcript:
                                        newTranscript
                                })
                            }
                        );


                    const transcriptData =
                        await transcriptResponse.json();


                    if (
                        !transcriptResponse.ok
                    ) {

                        throw new Error(
                            transcriptData.detail ||
                            "Could not update transcript."
                        );
                    }
                }


                // --------------------------------
                // Reload meeting
                // --------------------------------

                const reloadResponse =
                    await fetch(
                        `/api/meetings/${this.meetingId}`,
                        {
                            headers: {
                                "Authorization":
                                    `Bearer ${token}`
                            }
                        }
                    );


                if (reloadResponse.ok) {

                    this.meeting =
                        await reloadResponse.json();

                    this.form.transcript =
                        this.meeting.transcript ||
                        "";

                }


                alert(
                    "Meeting updated successfully."
                );


            } catch (error) {

                console.error(error);

                alert(
                    error.message ||
                    "Could not update meeting."
                );

            } finally {

                this.saving = false;
            }
        },


        // ----------------------------------------
        // Logout
        // ----------------------------------------

        logout() {

            localStorage.removeItem(
                "access_token"
            );

            window.location.href =
                "/login";
        }
    };
}


// ============================================================
// EMPLOYEES PAGE (Phase 12)
// ============================================================

function employeesPage() {

    return {

        user: null,
        users: [],
        teams: [],
        loading: true,
        error: "",
        successMessage: "",

        searchQuery: "",
        roleFilter: "",

        showCreateModal: false,
        showEditModal: false,
        showPasswordModal: false,
        showDeleteModal: false,

        submitting: false,
        formError: "",

        newUser: { name: "", email: "", password: "", role: "employee" },
        editUserData: { id: null, name: "", email: "", role: "employee" },
        passwordUser: null,
        newPassword: "",
        deletingUser: null,

        showTeamModal: false,
        editingTeam: null,
        teamForm: { name: "", description: "", member_ids: [] },
        teamError: "",

        async init() {

            const token = getToken();

            if (!token) {
                window.location.href = "/login";
                return;
            }

            try {

                const userResponse = await fetch("/users/me", {
                    headers: { "Authorization": `Bearer ${token}` }
                });

                if (userResponse.status === 401) {
                    clearAuth();
                    window.location.href = "/login";
                    return;
                }

                this.user = await userResponse.json();

                if (this.user.role !== "admin") {
                    window.location.href = "/dashboard";
                    return;
                }

                await Promise.all([this.loadUsers(), this.loadTeams()]);

            } catch (error) {
                console.error(error);
                this.error = error.message || "Could not load employees.";
            } finally {
                this.loading = false;
                this.$nextTick(() => {
                    if (typeof lucide !== "undefined") lucide.createIcons();
                });
            }
        },

        async loadUsers() {

            const token = getToken();
            this.error = "";

            try {

                const params = new URLSearchParams();
                if (this.searchQuery) params.set("q", this.searchQuery);
                if (this.roleFilter) params.set("role", this.roleFilter);

                const response = await fetch(`/users/?${params.toString()}`, {
                    headers: { "Authorization": `Bearer ${token}` }
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || "Could not load employees.");
                }

                this.users = data;

            } catch (error) {
                console.error("LOAD USERS ERROR:", error);
                this.error = error.message || "Could not load employees.";
            }
        },

        async loadTeams() {
            const token = getToken();
            try {
                const response = await fetch("/api/teams/", {
                    headers: { "Authorization": `Bearer ${token}` }
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || "Could not load teams.");
                }
                this.teams = data;
            } catch (error) {
                console.error("LOAD TEAMS ERROR:", error);
                this.error = error.message || "Could not load teams.";
            }
        },

        openNewTeam() {
            this.editingTeam = null;
            this.teamForm = { name: "", description: "", member_ids: [] };
            this.teamError = "";
            this.showTeamModal = true;
        },

        openTeam(team) {
            this.editingTeam = team;
            this.teamForm = {
                name: team.name || "",
                description: team.description || "",
                member_ids: [...(team.member_ids || [])]
            };
            this.teamError = "";
            this.showTeamModal = true;
        },

        teamMemberChecked(userId) {
            return this.teamForm.member_ids.includes(userId);
        },

        toggleTeamMember(userId) {
            if (this.teamForm.member_ids.includes(userId)) {
                this.teamForm.member_ids = this.teamForm.member_ids.filter(id => id !== userId);
            } else {
                this.teamForm.member_ids = [...this.teamForm.member_ids, userId];
            }
        },

        async saveTeam() {
            const token = getToken();
            this.submitting = true;
            this.teamError = "";
            try {
                const isEdit = !!this.editingTeam;
                const response = await fetch(
                    isEdit ? `/api/teams/${this.editingTeam.id}` : "/api/teams/",
                    {
                        method: isEdit ? "PUT" : "POST",
                        headers: {
                            "Authorization": `Bearer ${token}`,
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            name: this.teamForm.name,
                            description: this.teamForm.description
                        })
                    }
                );
                const team = await response.json();
                if (!response.ok) {
                    throw new Error(team.detail || "Could not save team.");
                }

                const membersResponse = await fetch(`/api/teams/${team.id}/members`, {
                    method: "PUT",
                    headers: {
                        "Authorization": `Bearer ${token}`,
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ user_ids: this.teamForm.member_ids })
                });
                const membersData = await membersResponse.json();
                if (!membersResponse.ok) {
                    throw new Error(membersData.detail || "Team saved, but members could not be updated.");
                }

                this.showTeamModal = false;
                this.successMessage = isEdit ? "Team updated successfully." : "Team created successfully.";
                await this.loadTeams();
            } catch (error) {
                this.teamError = error.message || "Could not save team.";
            } finally {
                this.submitting = false;
            }
        },

        async deleteTeam(team) {
            if (!confirm(`Delete ${team.name}? Saved meetings will keep their explicit employee access, but this team link will be removed.`)) {
                return;
            }
            const token = getToken();
            try {
                const response = await fetch(`/api/teams/${team.id}`, {
                    method: "DELETE",
                    headers: { "Authorization": `Bearer ${token}` }
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || "Could not delete team.");
                }
                this.successMessage = "Team deleted successfully.";
                await this.loadTeams();
            } catch (error) {
                this.error = error.message || "Could not delete team.";
            }
        },

        async createUser() {

            const token = getToken();
            this.submitting = true;
            this.formError = "";

            try {

                const response = await fetch("/users/admin-create", {
                    method: "POST",
                    headers: {
                        "Authorization": `Bearer ${token}`,
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify(this.newUser)
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || "Could not create employee.");
                }

                this.showCreateModal = false;
                this.newUser = { name: "", email: "", password: "", role: "employee" };
                this.successMessage = "Employee created successfully.";
                await this.loadUsers();

            } catch (error) {
                this.formError = error.message || "Could not create employee.";
            } finally {
                this.submitting = false;
            }
        },

        openEditModal(u) {
            this.editUserData = { id: u.id, name: u.name, email: u.email, role: u.role };
            this.formError = "";
            this.showEditModal = true;
        },

        async updateUser() {

            const token = getToken();
            this.submitting = true;
            this.formError = "";

            try {

                const response = await fetch(`/users/${this.editUserData.id}`, {
                    method: "PUT",
                    headers: {
                        "Authorization": `Bearer ${token}`,
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        name: this.editUserData.name,
                        email: this.editUserData.email,
                        role: this.editUserData.role
                    })
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || "Could not update employee.");
                }

                this.showEditModal = false;
                this.successMessage = "Employee updated successfully.";
                await this.loadUsers();

            } catch (error) {
                this.formError = error.message || "Could not update employee.";
            } finally {
                this.submitting = false;
            }
        },

        openPasswordModal(u) {
            this.passwordUser = u;
            this.newPassword = "";
            this.formError = "";
            this.showPasswordModal = true;
        },

        async resetPassword() {

            const token = getToken();
            this.submitting = true;
            this.formError = "";

            try {

                const response = await fetch(`/users/${this.passwordUser.id}/password`, {
                    method: "PUT",
                    headers: {
                        "Authorization": `Bearer ${token}`,
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ new_password: this.newPassword })
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || "Could not reset password.");
                }

                this.showPasswordModal = false;
                this.successMessage = "Password reset successfully.";

            } catch (error) {
                this.formError = error.message || "Could not reset password.";
            } finally {
                this.submitting = false;
            }
        },

        async toggleActive(u, activate) {

            const token = getToken();
            const action = activate ? "activate" : "deactivate";

            try {

                const response = await fetch(`/users/${u.id}/${action}`, {
                    method: "PATCH",
                    headers: { "Authorization": `Bearer ${token}` }
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || "Could not update employee status.");
                }

                await this.loadUsers();

            } catch (error) {
                this.error = error.message || "Could not update employee status.";
            }
        },

        async deleteUser() {

            const token = getToken();
            this.submitting = true;

            try {

                const response = await fetch(`/users/${this.deletingUser.id}`, {
                    method: "DELETE",
                    headers: { "Authorization": `Bearer ${token}` }
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || "Could not delete employee.");
                }

                this.showDeleteModal = false;
                this.successMessage = data.message || "Employee removed.";
                await this.loadUsers();

            } catch (error) {
                this.error = error.message || "Could not delete employee.";
            } finally {
                this.submitting = false;
            }
        },

        logout() {
            clearAuth();
            window.location.href = "/login";
        }

    };
}
