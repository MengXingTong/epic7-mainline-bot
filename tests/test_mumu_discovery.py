import copy,json,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from mumu_discovery import local_port,find_manager,manager_instances,discover_mumu
from assistant_config import select_target

PKG='example.game'
def instance(index,port,**extra):
    return dict(index=str(index),name='Player '+str(index),pid=100+index,adb_host_ip='127.0.0.1',adb_port=port,is_process_started=True,is_android_started=True,error_code=0,**extra)
def response(stdout=b'',returncode=0):return SimpleNamespace(stdout=stdout,stderr=b'',returncode=returncode)
class FakeRun:
    def __init__(self,info=None,online=None,install=None):
        self.info=info if info is not None else {'0':instance(0,16384),'1':instance(1,16416)}
        self.online=list(online if online is not None else ['127.0.0.1:16384']);self.install=install or {};self.calls=[];self.connect_works=True
    def __call__(self,args,**kw):
        self.calls.append((args,kw))
        if args[1:]==['info','--vmindex','all']:
            if isinstance(self.info,Exception):raise self.info
            return response(json.dumps(self.info).encode())
        if args[1:]==['devices']:return response(('List of devices attached\n'+''.join(s+'\tdevice\n' for s in self.online)).encode())
        if args[1]=='connect':
            if self.connect_works:self.online.append(args[2])
            return response(b'connected')
        if args[1]=='-s' and args[3:]==['shell','pm','path',PKG]:
            return response(b'package:/data/app/example.apk' if self.install.get(args[2],True) else b'')
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
    def test_stopped_or_booting_instances_not_connected(self):
        for field in ('is_process_started','is_android_started'):
            f=FakeRun();f.info['1'][field]=False;rows,w=self.discover(f);self.assertEqual(len(rows),1)
            self.assertFalse(any(c[0][1]=='connect' for c in f.calls))
    def test_only_manager_reported_ports_no_sweep(self):
        f=FakeRun();self.discover(f);self.assertEqual(set(c[0][2] for c in f.calls if c[0][1]=='connect'),{'127.0.0.1:16416'})
        self.assertTrue(all(c[0][1] in ('info','devices','connect','-s') for c in f.calls))
    def test_unknown_remote_and_usb_devices_not_mumu(self):
        f=FakeRun(online=['192.168.1.2:12345','physical-phone','127.0.0.1:16384']);rows,_=self.discover(f)
        self.assertEqual(len(rows),2);self.assertTrue(all(r['serial'].startswith('127.0.0.1:') for r in rows))
    def test_unrelated_local_device_excluded_when_manager_is_available(self):
        f=FakeRun(online=['127.0.0.1:16384','127.0.0.1:9999']);rows,_=self.discover(f)
        self.assertNotIn('127.0.0.1:9999',[r['serial'] for r in rows])
    def test_connect_text_not_proof_of_online_device(self):
        f=FakeRun();f.connect_works=False;rows,_=self.discover(f);self.assertEqual(len(rows),1)
    def test_missing_game_not_operable(self):
        f=FakeRun(install={'127.0.0.1:16416':False});rows,w=self.discover(f);self.assertEqual(len(rows),1);self.assertIn('未核实到所选游戏包',w[-1])
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
    def test_ambiguous_manager_port_rejected(self):
        f=FakeRun();f.info['1']['adb_port']=16384;rows,_=self.discover(f);self.assertEqual(rows,[])
    def test_bad_manager_shape_and_port_rejected(self):
        with self.assertRaises(ValueError):manager_instances([])
        for value in (0,5037,65536,True,'16416'):
            r=instance(0,16384);r['adb_port']=value;self.assertEqual(manager_instances({'0':r}),[])
        r=instance(0,16384);r['adb_host_ip']='192.168.1.1';self.assertEqual(manager_instances({'0':r}),[])
    def test_local_only(self):
        for value in ('127.0.0.1:16384','localhost:16416'):self.assertIsNotNone(local_port(value))
        for value in ('127.0.0.2:16384','0.0.0.0:16384','example.org:16416','127.0.0.1:5037','127.0.0.1:999999'):self.assertIsNone(local_port(value))
    def test_bad_package_prevents_shell_query(self):
        f=FakeRun()
        with self.assertRaises(ValueError):self.discover(f,dict(package='example.game;input tap 1 1'))
        self.assertFalse(any(c[0][1]=='-s' for c in f.calls))
    def test_manager_resolution_only_associated_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);adb=root/'nx_device/15.0/shell/adb.exe';adb.parent.mkdir(parents=True);adb.touch()
            manager=root/'nx_main/MuMuManager.exe';manager.parent.mkdir();manager.touch()
            self.assertEqual(find_manager(adb),manager.resolve())
    def test_timeout_is_bounded_and_never_launches_or_inputs(self):
        f=FakeRun(info=subprocess.TimeoutExpired('info',3));self.discover(f)
        self.assertTrue(all(0<kw['timeout']<=4 for _,kw in f.calls))
        self.assertFalse(any(word in c[0] for c in f.calls for word in ('launch','control','input','start')))
if __name__=='__main__':unittest.main()
