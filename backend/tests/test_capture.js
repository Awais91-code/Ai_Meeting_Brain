// Exercise the shipped recording controller with simulated browser devices.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('backend/app/static/js/capture.js', 'utf8');
const sid = '12345678-1234-1234-1234-123456789abc';
const settle = async () => { for (let i=0;i<12;i++) await new Promise(resolve=>setImmediate(resolve)); };

function harness(user) {
    const elements = {};
    const node = id => elements[id] ||= {hidden:false, disabled:false, textContent:'', href:'', files:[], appendChild(){}, querySelector(){return node('submit');}};
    const calls = [], events = {}, timers = [];
    const state = {session_id:sid,title:'Team call',invite_path:'/live/'+sid,language:'auto',status:'draft',can_record:user?.role==='admin',can_join:true,conference_configured:true,max_audio_mb:250,meeting_id:null};
    const storage = new Map();
    const track = {stop(){},addEventListener(){}};
    const stream = {getTracks:()=>[track], getAudioTracks:()=>[track], getVideoTracks:()=>[track]};
    let recordedOptions;
    class Recorder {
        static isTypeSupported(){return true;}
        constructor(stream, options){recordedOptions=options;this.state='inactive';}
        start(){this.state='recording';}
        stop(){this.state='inactive';this.ondataavailable({data:new Blob(['speech'])});this.onstop();}
    }
    const audioNode = () => ({connect(next){return next;}});
    class AudioContext {
        async resume(){} close(){}
        createMediaStreamDestination(){return {...audioNode(),stream};}
        createMediaStreamSource(){return audioNode();}
        createGain(){return {...audioNode(),gain:{value:0}};}
        createDynamicsCompressor(){return {...audioNode(),threshold:{},knee:{},ratio:{},attack:{},release:{}};}
    }
    class Jitsi {constructor(domain,options){calls.push({jitsi:options});} addListener(name,callback){events[name]=callback;} dispose(){} executeCommand(){} }
    const location = {pathname:'/live/'+sid,origin:'https://app.example.test',href:'',replace(value){this.href=value;}};
    const context = {
        document:{getElementById:node}, window:{captureSessionId:sid,MediaRecorder:Recorder,JitsiMeetExternalAPI:Jitsi,addEventListener(){}},
        location, getCurrentUser:async()=>user, getToken:()=> 'app-token',
        sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
        localStorage:{setItem(){}}, setInterval(){}, setTimeout(fn){timers.push(fn);},
        navigator:{mediaDevices:{getDisplayMedia:async()=>stream,getUserMedia:async()=>stream}},
        AudioContext, MediaRecorder:Recorder, MediaStream:class{}, JitsiMeetExternalAPI:Jitsi,
        Blob, FormData, URL, history:{replaceState(){}},
        fetch:async(path,options)=>{
            calls.push({path,options});
            let data={...state};
            if(path==='/api/conference/status') data={state:'ready',message:'Ready',managed:true};
            if(path.endsWith('/admission')) data={domain:'meet.example.test',room:'restricted-room',jwt:'room-token',receipt:'attendance-receipt',display_name:'Employee'};
            if(path.endsWith('/joined')) data={joined:true};
            if(path.endsWith('/audio')) {state.status='ready';state.meeting_id=42;data={...state};}
            return {ok:true,status:200,json:async()=>data};
        }
    };
    vm.runInNewContext(code,context);
    return {node,calls,events,location,storage,options:()=>recordedOptions};
}

(async()=>{
    const anonymous=harness(null); await settle();
    assert.equal(anonymous.location.href,'/login?next='+encodeURIComponent('/live/'+sid));
    assert.equal(anonymous.calls.length,0);
    const employee=harness({role:'employee'}); await settle();
    assert.equal(employee.node('record-controls').hidden,true);
    assert.equal(employee.node('invite').href,'https://app.example.test/live/'+sid);
    assert.equal(employee.node('results').hidden,true);
    await employee.node('join').onclick();
    assert.equal(employee.calls.find(c=>c.jitsi).jitsi.jwt,'room-token');
    assert.equal(employee.calls.some(c=>c.path?.endsWith('/joined')),false);
    employee.events.videoConferenceJoined(); await settle();
    assert.equal(JSON.parse(employee.calls.find(c=>c.path?.endsWith('/joined')).options.body).receipt,'attendance-receipt');
    employee.events.videoConferenceLeft(); await settle();
    assert.equal(employee.calls.some(c=>c.path?.endsWith('/end')),false);
    const host=harness({role:'admin'}); await settle();
    await host.node('join').onclick(); await host.node('start').onclick();
    assert.equal(host.options().audioBitsPerSecond,128000);
    host.events.videoConferenceLeft(); await settle();
    assert.equal(host.calls.filter(c=>c.path?.endsWith('/audio')).length,1);
    assert.equal(host.calls.filter(c=>c.path?.endsWith('/end')).length,1);
    assert.equal(host.node('results').href,'/meetings/42');
    assert.equal(host.node('results').hidden,false);
    assert.match(host.node('status').textContent,/Ready/);
    console.log('PASS: invite login, employee join receipt, restricted recording controls, automatic upload on leave, and ready-state link');
})().catch(error=>{console.error(error);process.exitCode=1;});
