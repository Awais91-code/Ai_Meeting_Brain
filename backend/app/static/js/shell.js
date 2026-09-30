(() => {
    const icons = () => window.lucide?.createIcons();
    icons();
    const sidebar = document.getElementById('app-sidebar');
    const toggle = document.getElementById('menu-toggle');
    const shade = document.getElementById('sidebar-shade');
    function setMenu(open) {
        sidebar?.classList.toggle('is-open', open);
        if (shade) shade.hidden = !open;
        toggle?.setAttribute('aria-expanded', String(open));
    }
    toggle?.addEventListener('click', () => setMenu(!sidebar.classList.contains('is-open')));
    shade?.addEventListener('click', () => setMenu(false));
    document.addEventListener('keydown', event => { if (event.key === 'Escape') setMenu(false); });
    document.querySelectorAll('[data-signout]').forEach(button => button.addEventListener('click', () => {
        localStorage.removeItem('access_token'); window.location.href = '/login';
    }));
    if (sidebar && localStorage.getItem('access_token')) {
        fetch('/users/me', {headers:{Authorization:'Bearer '+localStorage.getItem('access_token')}})
            .then(response => response.ok ? response.json() : null).then(user => {
                if (!user) return;
                document.querySelectorAll('[data-user-name]').forEach(el => {el.textContent=user.name;});
                document.querySelectorAll('[data-user-role]').forEach(el => {el.textContent=user.role === 'admin' ? 'Administrator' : 'Team member';});
                document.querySelectorAll('[data-user-initial]').forEach(el => {el.textContent=user.name.charAt(0).toUpperCase();});
                if (user.role === 'admin') document.querySelectorAll('[data-admin]').forEach(el => {el.hidden=false;});
            }).catch(() => {});
    }
})();
