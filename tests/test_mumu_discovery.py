import copy,json,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from mumu_discovery import local_port,find_manager,manager_instances,discover_mumu,resumed_package
from assistant_config import select_target

PKG='example.game'
def instance(index,port,**extra):
    return dict(index=str(index),name='Player '+str(index),pid=100+index,adb_host_ip='127.0.0.1',adb_port=port,is_process_started=True,is_android_started=True,error_code=0,**extra)
def response(stdout=b'',returncode=0):return SimpleNamespace(stdout=stdout,stderr=b'',returncode=returncode)
class FakeRun:
    def __init__(self,info=None,online=None,activities=None):
        self.info=info if info is not None else {'0':instance(0,16384),'1':instance(1,16416)}
        self.online=list(online if online is not None else ['127.0.0.1:16384']);self.activities=activities or {};self.calls=[];self.connect_works=True
    def __call__(self,args,**kw):
        self.calls.append((args,kw))
        if args[1:]==['info','--vmindex','all']:
            if isinstance(self.info,Exception):raise self.info
            return response(json.dumps(self.info).encode())
        if args[1:]==['devices']:return response(('List of devices attached\n'+''.join(s+'\tdevice\n' for s in self.online)).encode())
        if args[1]=='connect':
            if self.connect_works:self.online.append(args[2])
            return response(b'connected')
        if args[1]=='-s' and args[3:]==['shell','dumpsys','activity','activities']:
            value=self.activities.get(args[2],response(f'mResumedActivity: ActivityRecord{{a u0 {PKG}/.Main t1}}'.encode()))
            if isinstance(value,Exception):raise value
            return value
        raise AssertionError(args)
class MuMuDiscoveryTests(unittest.TestCase):
    def discover(self,f,cfg=None,**kwargs):return discover_mumu('adb.exe',cfg or dict(package=PKG,serial='127.0.0.1:16384'),run=f,manager='MuMuManager.exe',clock=lambda:0,**kwargs)
    def test_saved_serial_does_not_hide_second_and_connect_even_when_one_online(self):
        f=FakeRun();cfg=dict(package=PKG,serial='127.0.0.1:16384');old=copy.deepcopy(cfg)
        targets,warnings=self.discover(f,cfg)
        self.assertEqual([r['serial'] for r in targets],['127.0.0.1:16384','127.0.0.1:16416']);self.assertEqual(warnings,[])
        self.assertEqual(cfg,old);self.assertEqual([c[0] for c in f.calls if c[0][1]=='connect'],[['adb.exe','connect','127.0.0.1:16416']])
        with self.assertRaises(ValueError):select_target('mumu',targets)
    def test_connected_instances_are_not_reconnected(self):
        f=FakeRun(online=['127.0.0.1:16384','127.0.0.1:16416']);rows,w=self.discover(f)
        self.assertEqual(len(rows),2);self.assertFalse(any(c[0][1]=='connect' for c in f.calls))
    def test_manager_runtime_flags_do_not_veto_a_reachable_adb_endpoint(self):
        for field in ('is_process_started','is_android_started'):
            f=FakeRun();f.info['1'][field]=False;rows,w=self.discover(f);self.assertEqual(len(rows),2)
            self.assertEqual([c[0][2] for c in f.calls if c[0][1]=='connect'],['127.0.0.1:16416'])
    def test_only_manager_reported_ports_no_sweep(self):
        f=FakeRun();self.discover(f);self.assertEqual(set(c[0][2] for c in f.calls if c[0][1]=='connect'),{'127.0.0.1:16416'})
        self.assertTrue(all(c[0][1] in ('info','devices','connect','-s') for c in f.calls))
    def test_unknown_remote_and_usb_devices_not_mumu(self):
        f=FakeRun(online=['192.168.1.2:12345','physical-phone','127.0.0.1:16384']);rows,_=self.discover(f)
        self.assertEqual(len(rows),2);self.assertTrue(all(r['serial'].startswith('127.0.0.1:') for r in rows))
    def test_online_local_device_not_vetoed_by_manager_metadata(self):
        f=FakeRun(online=['127.0.0.1:16384','127.0.0.1:9999']);rows,_=self.discover(f)
        row=next(r for r in rows if r['serial']=='127.0.0.1:9999')
        self.assertEqual(row['package'],PKG);self.assertNotIn('mumu_index',row)
    def test_connect_text_not_proof_of_online_device(self):
        f=FakeRun();f.connect_works=False;rows,_=self.discover(f);self.assertEqual(len(rows),1)
    def test_missing_foreground_has_no_stale_package_fallback(self):
        f=FakeRun(activities={'127.0.0.1:16416':response(b'mResumedActivity: null')});rows,w=self.discover(f)
        self.assertEqual(len(rows),1);self.assertIn('请先打开游戏后刷新',w[-1])
    def test_manager_failure_keeps_all_already_connected_not_saved_filter(self):
        f=FakeRun(info=ValueError('unsupported'),online=['127.0.0.1:16384','127.0.0.1:16416']);rows,w=self.discover(f)
        self.assertEqual(len(rows),2);self.assertTrue(w);self.assertFalse(any(c[0][1]=='connect' for c in f.calls))
    def test_manager_failure_can_only_try_exact_old_local_fallback(self):
        f=FakeRun(info=OSError('missing'),online=[]);rows,_=self.discover(f)
        self.assertEqual([c[0][2] for c in f.calls if c[0][1]=='connect'],['127.0.0.1:16384']);self.assertEqual(len(rows),1)
    def test_no_remote_fallback(self):
        f=FakeRun(info=OSError('missing'),online=[]);rows,_=self.discover(f,dict(package=PKG,serial='10.0.0.1:16384'))
        self.assertEqual(rows,[]);self.assertFalse(any(c[0][1]=='connect' for c in f.calls))
    def test_loopback_alias_deduplicated(self):
        f=FakeRun(online=['localhost:16384','127.0.0.1:16384','127.0.0.1:16416']);rows,_=self.discover(f);self.assertEqual(len(rows),2)
    def test_ambiguous_manager_metadata_cannot_hide_an_online_instance(self):
        f=FakeRun();f.info['1']['adb_port']=16384;rows,_=self.discover(f)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['serial'],'127.0.0.1:16384')
        self.assertNotIn('mumu_index',rows[0]);self.assertFalse(any(c[0][1]=='connect' for c in f.calls))
    def test_bad_manager_shape_and_port_rejected(self):
        with self.assertRaises(ValueError):manager_instances([])
        for value in (0,5037,65536,True,'16416;input tap 1 1'):
            r=instance(0,16384);r['adb_port']=value;self.assertEqual(manager_instances({'0':r}),[])
        r=instance(0,16384);r['adb_host_ip']='192.168.1.1';self.assertEqual(manager_instances({'0':r}),[])
    def test_local_only(self):
        for value in ('127.0.0.1:16384','localhost:16416'):self.assertIsNotNone(local_port(value))
        for value in ('127.0.0.2:16384','0.0.0.0:16384','example.org:16416','127.0.0.1:5037','127.0.0.1:999999'):self.assertIsNone(local_port(value))
    def test_saved_package_is_not_executed_or_used_as_a_filter(self):
        f=FakeRun();cfg=dict(package='example.game;input tap 1 1');old=copy.deepcopy(cfg)
        rows,_=self.discover(f,cfg)
        self.assertEqual([r['package'] for r in rows],[PKG,PKG]);self.assertEqual(cfg,old)
        self.assertFalse(any(cfg['package'] in c[0] or 'pm' in c[0] for c in f.calls))
    def test_each_instance_binds_its_actual_channel_without_a_package_allowlist(self):
        packages={'127.0.0.1:16384':'com.stove.epic7.google','127.0.0.1:16416':'org.vendor.channel'}
        f=FakeRun(activities={s:response(f'topResumedActivity=ActivityRecord{{a u0 {p}/.Game t1}}'.encode()) for s,p in packages.items()})
        cfg=dict(package='old.uninstalled.package',serial='127.0.0.1:16384');old=copy.deepcopy(cfg)
        rows,w=self.discover(f,cfg)
        self.assertEqual({r['serial']:r['package'] for r in rows},packages);self.assertEqual(w,[]);self.assertEqual(cfg,old)
        self.assertTrue(all(r['package'] in r['label'] for r in rows))
    def test_no_configuration_still_uses_the_current_app(self):
        rows,w=self.discover(FakeRun(),dict(serial='127.0.0.1:16384'))
        self.assertEqual([r['package'] for r in rows],[PKG,PKG]);self.assertEqual(w,[])
    def test_online_instance_survives_missing_or_stale_manager_fields(self):
        for field,value in (('pid',None),('is_process_started',False),('is_android_started',False),('error_code',1),('index','wrong')):
            with self.subTest(field=field):
                f=FakeRun(online=['127.0.0.1:16384','127.0.0.1:16416']);f.info['1'][field]=value
                rows,_=self.discover(f);self.assertEqual(len(rows),2)
                self.assertFalse(any(c[0][1]=='connect' for c in f.calls))
    def test_minimal_manager_endpoint_is_enough_and_online_is_still_required(self):
        f=FakeRun(info={'3':{'adb_port':'16480'}},online=[])
        rows,w=self.discover(f)
        self.assertEqual(rows[0]['serial'],'127.0.0.1:16480');self.assertEqual(rows[0]['mumu_index'],3);self.assertEqual(w,[])
        f=FakeRun(info={'3':{'adb_port':'16480'}},online=[]);f.connect_works=False
        rows,_=self.discover(f);self.assertEqual(rows,[])
    def test_foreground_query_errors_do_not_reuse_the_saved_app(self):
        for value in (response(b'topResumedActivity=example.game/.Main',returncode=1),OSError('unavailable'),subprocess.TimeoutExpired('activities',2)):
            with self.subTest(value=value):
                f=FakeRun(activities={'127.0.0.1:16384':value,'127.0.0.1:16416':value})
                rows,w=self.discover(f);self.assertEqual(rows,[]);self.assertEqual(len(w),2)
    def test_slow_offline_probes_do_not_hide_an_already_online_game(self):
        f=FakeRun(info={str(i):instance(i,16384+i*32) for i in range(10)});f.connect_works=False
        elapsed=[0]
        def run(args,**kwargs):
            result=f(args,**kwargs)
            if args[1]=='connect':elapsed[0]+=2
            return result
        rows,w=discover_mumu('adb.exe',{},run=run,clock=lambda:elapsed[0],manager='MuMuManager.exe',budget=6)
        self.assertEqual([r['serial'] for r in rows],['127.0.0.1:16384']);self.assertTrue(w)
        self.assertLessEqual(len([c for c in f.calls if c[0][1]=='connect']),3)
        self.assertEqual(len([c for c in f.calls if c[0][1]=='-s']),1)
    def test_manager_resolution_only_associated_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);adb=root/'nx_device/15.0/shell/adb.exe';adb.parent.mkdir(parents=True);adb.touch()
            manager=root/'nx_main/MuMuManager.exe';manager.parent.mkdir();manager.touch()
            self.assertEqual(find_manager(adb),manager.resolve())
    def test_timeout_is_bounded_and_never_launches_or_inputs(self):
        f=FakeRun(info=subprocess.TimeoutExpired('info',3));self.discover(f)
        self.assertTrue(all(0<kw['timeout']<=4 for _,kw in f.calls))
        self.assertFalse(any(word in c[0] for c in f.calls for word in ('launch','control','input','start')))

class ForegroundPackageTests(unittest.TestCase):
    def test_android_component_formats(self):
        for field in ('topResumedActivity','mResumedActivity'):
            for separator in (':','='):
                for component in ('org.vendor.game/.Main','org.vendor.game/com.unity3d.player.UnityPlayerActivity'):
                    with self.subTest(field=field,separator=separator,component=component):
                        self.assertEqual(resumed_package(f'  {field}{separator} ActivityRecord{{a u0 {component} t1}}'),'org.vendor.game')
        self.assertEqual(resumed_package('topResumedActivity=org.vendor.game/.Main'),'org.vendor.game')
    def test_duplicate_reports_of_the_same_app_are_one_binding(self):
        self.assertEqual(resumed_package('topResumedActivity=org.vendor.game/.Main\nmResumedActivity: ActivityRecord{b u0 org.vendor.game/.Main t1}'),'org.vendor.game')
    def test_background_or_ambiguous_components_are_not_a_current_binding(self):
        for value in ('','mResumedActivity: null','Hist #0: org.vendor.game/.Main','mResumedActivity: text mentions org.vendor.game but no component',
                      'topResumedActivity=org.vendor.game/.Main\nmResumedActivity=another.application/.Main'):
            with self.subTest(value=value):self.assertIsNone(resumed_package(value))
if __name__=='__main__':unittest.main()
