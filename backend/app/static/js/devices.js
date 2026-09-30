(() => {
    const $=id=>document.getElementById(id);
    async function load() {
        const token=localStorage.getItem('access_token');
        if(!token){location.href='/login';return;}
        const response=await fetch('/api/conference/device-access',{headers:{Authorization:'Bearer '+token}});
        if(response.status===401){location.href='/login';return;}
        if(response.status===403)throw new Error('Ask your administrator for the phone setup address.');
        if(!response.ok)throw new Error('Connection details could not be loaded. Please retry.');
        const data=await response.json();
        if(!data.configured){$('device-status').textContent='Phone access needs its one-time laptop setup. Run setup-network-meetings.ps1, then start.ps1.';return;}
        $('device-status').textContent='Current laptop address detected: '+(data.address||'private network')+'. The app refreshes this address automatically each time start.ps1 runs.';
        $('device-details').hidden=false;
        for(const [id,url] of [['device-setup',data.setup_url],['device-app',data.app_url]]){
            $(id).href=url;$(id).textContent=url;
            $('copy-'+id).onclick=async()=>{
                try{await navigator.clipboard.writeText(url);$('copy-'+id).textContent='Copied';}
                catch(_){$('copy-'+id).textContent='Select and copy the address';}
            };
        }
        $('device-fingerprint').textContent=data.certificate_sha256;
    }
    load().catch(error=>{$('device-status').textContent=error.message;});
})();
