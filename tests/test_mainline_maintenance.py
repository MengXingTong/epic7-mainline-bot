"""Explicit authorization and provenance regressions; all input is mocked."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from assistant_config import atomic_json
from mainline_maintenance import validate_maintenance,digest
from story_reopen import reopen_story_once,state_digest
from entry_journal import reserve_entry,finish_dispatch
from test_story_only_nodes import frame,fake_runner


def pending():
    f=frame();r=fake_runner(f);d=r.map_ticket(f)[0]
    active=dict(d,cost=0,entry_kind='story_only',start_epoch=time.time())
    dispatch=reserve_entry(r.s,d['key'],active);finish_dispatch(dispatch,'sent');r.s['active']=active
    permit=dict(id='explicit-authorization',key=d['key'],user_authorization='user explicitly permits one reopen',
                source_state_sha256=state_digest(r.s),original_dispatch_id=dispatch['id'])
    return r,permit


class StoryReopenTests(unittest.TestCase):
    def test_one_authorized_reopen_preserves_attempt_and_original_sent(self):
        r,permit=pending();before=copy.deepcopy(r.s);snap=[]
        r.action.side_effect=lambda *a:snap.append(copy.deepcopy(r.s))
        reopen_story_once(r,permit)
        self.assertEqual(snap[0]['story_reopen_authorizations'][0]['status'],'reserved')
        self.assertEqual(r.s['attempted'],before['attempted']);self.assertEqual(r.s['entry_dispatches'],before['entry_dispatches'])
        self.assertEqual(r.s['story_reopen_authorizations'][0]['status'],'sent')
        with self.assertRaises(ValueError):reopen_story_once(r,permit)
        r.action.assert_called_once()
    def test_no_authorization_or_changed_state_never_sends(self):
        for change in ('permission','hash','dispatch','completed','cost','kind','playback'):
            r,p=pending()
            if change=='permission':p['user_authorization']=''
            if change=='hash':p['source_state_sha256']='bad'
            if change=='dispatch':r.s['entry_dispatches'][p['key']][0]['status']='reserved'
            if change=='completed':r.s['completed'][p['key']]={}
            if change=='cost':r.s['active']['cost']=8
            if change=='kind':r.s['active']['entry_kind']='battle'
            if change=='playback':r.s['active']['story_seen']=time.time()
            if change not in ('permission','hash'):p['source_state_sha256']=state_digest(r.s)
            with self.assertRaises(ValueError):reopen_story_once(r,p)
            r.action.assert_not_called()
    def test_send_unknown_or_not_sent_consumes_once_without_reuse(self):
        from pc_backend import TapNotSent
        for exc in (RuntimeError('unknown send'),TapNotSent('not sent')):
            r,p=pending();r.action.side_effect=exc
            with self.assertRaises(type(exc)):reopen_story_once(r,p)
            self.assertEqual(r.s['story_reopen_authorizations'][0]['status'],'reserved')
            retry={**p,'id':'another','source_state_sha256':state_digest(r.s)}
            with self.assertRaises(ValueError):reopen_story_once(r,retry)
            r.action.assert_called_once()
    def test_wrong_or_stale_map_does_not_consume_authorization(self):
        for change in ('stale','wrong','locked'):
            r,p=pending()
            if change=='stale':r.frame.at=time.time()-4
            else:
                d=r.map_ticket(r.frame)[0];d['key']='wrong' if change=='wrong' else p['key'];d['locked']=change=='locked'
                r.map_ticket=lambda f:(d,[],'未通关蓝色当前节点')
            with self.assertRaises(ValueError):reopen_story_once(r,p)
            self.assertNotIn('story_reopen_authorizations',r.s);r.action.assert_not_called()


class MainlineMaintenanceTests(unittest.TestCase):
    def setup_source(self,root):
        settings=dict(task='mainline',observe=False,data_dir=str(root));original=dict(run_id='original-run',run_dir=str(root),home=str(root/'home'),settings=settings,target=dict(client='mumu',serial='known',package='known'))
        state=dict(attempted={'existing':{'keep':'all'}},completed={},active={'key':'existing'},terminal=False)
        atomic_json(root/'request.json',original);atomic_json(root/'state.json',state)
        atomic_json(root/'status.json',dict(mode='stopped',run_id='original-run'))
        atomic_json(root/'control.json',dict(run_id='original-run',action='run',command_id='one-use'))
        proof=dict(run_id='original-run',nonce='one-use',previous_worker_pid=999,user_authorization='explicit ongoing new-account maintenance',original_request_sha256=digest(root/'request.json'),state_sha256=digest(root/'state.json'),stopped_status_sha256=digest(root/'status.json'))
        return dict(original,mainline_maintenance=proof),state
    def test_preserves_exact_exited_run_only(self):
        with tempfile.TemporaryDirectory() as tmp,patch('mainline_maintenance.process_is_alive',return_value=False):
            root=Path(tmp);request,state=self.setup_source(root);before=copy.deepcopy(state)
            self.assertEqual(validate_maintenance(request,root,state)['nonce'],'one-use');self.assertEqual(state,before)
    def test_pc_same_run_loader_preserves_source_and_uses_separate_request(self):
        from assistant_config import load_theater_resume_request
        with tempfile.TemporaryDirectory() as tmp,patch('mainline_maintenance.process_is_alive',return_value=False),patch('assistant_config.process_is_alive',return_value=False):
            home=Path(tmp);run='a'*32;folder=home/'runs'/run;folder.mkdir(parents=True)
            profile=home/'profile';profile.mkdir()
            original=dict(run_id=run,run_dir=str(folder),home=str(home),settings=dict(task='mainline',observe=False,data_dir=str(profile),pc_input='messages',start_policy='current_screen'),target=dict(client='pc',hwnd=1,pid=2,created=3,exe='game.exe'))
            atomic_json(folder/'request.json',original);atomic_json(profile/'state.json',dict(attempted={'old':{'preserve':True}},completed={},active=None))
            atomic_json(folder/'status.json',dict(mode='stopped',run_id=run));atomic_json(folder/'control.json',dict(run_id=run,action='stop',command_id='old'))
            atomic_json(home/'active-run.json',dict(run_id=run,run_dir=str(folder),worker_pid=999))
            proof=dict(run_id=run,nonce='new-maintenance',previous_worker_pid=999,user_authorization='explicit repair',original_request_sha256=digest(folder/'request.json'),state_sha256=digest(profile/'state.json'),stopped_status_sha256=digest(folder/'status.json'))
            maintenance=dict(original,mainline_maintenance=proof);atomic_json(folder/'mainline-maintenance-request.json',maintenance)
            before={p:p.read_bytes() for p in home.rglob('*.json')}
            self.assertEqual(load_theater_resume_request(run,home),maintenance)
            self.assertEqual(before,{p:p.read_bytes() for p in home.rglob('*.json')})
            atomic_json(folder/'control.json',dict(run_id=run,action='run',command_id=proof['nonce']))
            state=json.loads((profile/'state.json').read_text())
            self.assertEqual(validate_maintenance(maintenance,profile,state),proof)
            (profile/'STOP').write_text('stop')
            with self.assertRaises(ValueError):validate_maintenance(maintenance,profile,state)
    def routed_source(self,root):
        request,state=self.setup_source(root)
        request['settings']['start_policy']='current_screen'
        old=copy.deepcopy(request);old.pop('mainline_maintenance');old['settings']['data_dir']=str(root/'old-cache')
        atomic_json(root/'request.json',old)
        receipt=dict(run_id=old['run_id'],target=old['target'],request_sha256=digest(root/'request.json'),
            resolved_data_dir=str(root),history_mutated=False,
            resolution=dict(schema=1,reason='selected_target_original_profile',previous_data_dir=old['settings']['data_dir'],
                            resolved_data_dir=str(root),history_mutated=False))
        atomic_json(root/'profile-resolution.json',receipt)
        request['mainline_maintenance'].update(original_request_sha256=digest(root/'request.json'),
            profile_resolution_sha256=digest(root/'profile-resolution.json'))
        return request,state,receipt
    def test_routed_current_run_uses_only_its_audited_effective_profile(self):
        with tempfile.TemporaryDirectory() as tmp,patch('mainline_maintenance.process_is_alive',return_value=False):
            root=Path(tmp).resolve();request,state,_=self.routed_source(root)
            before={p:p.read_bytes() for p in root.glob('*.json')};protected=copy.deepcopy(state)
            self.assertEqual(validate_maintenance(request,root,state),request['mainline_maintenance'])
            atomic_json(root/'control.json',dict(run_id=request['run_id'],action='stop'))
            self.assertEqual(validate_maintenance(request,root,state,before_activation=True),request['mainline_maintenance'])
            self.assertEqual(state,protected)
            for path,data in before.items():
                if path.name!='control.json':self.assertEqual(path.read_bytes(),data)
    def test_routed_loader_does_not_open_the_other_clients_cached_profile(self):
        from assistant_config import load_theater_resume_request
        with tempfile.TemporaryDirectory() as tmp,patch('mainline_maintenance.process_is_alive',return_value=False),patch('assistant_config.process_is_alive',return_value=False):
            home=Path(tmp).resolve();run='b'*32;folder=home/'runs'/run;folder.mkdir(parents=True)
            request,state,receipt=self.routed_source(folder)
            original=json.loads((folder/'request.json').read_text())
            original.update(run_id=run,home=str(home));atomic_json(folder/'request.json',original)
            request.update(run_id=run,home=str(home))
            receipt.update(run_id=run,request_sha256=digest(folder/'request.json'))
            atomic_json(folder/'profile-resolution.json',receipt)
            atomic_json(folder/'status.json',dict(mode='stopped',run_id=run))
            atomic_json(folder/'control.json',dict(run_id=run,action='stop'))
            atomic_json(home/'active-run.json',dict(run_id=run,run_dir=str(folder),worker_pid=999))
            request['mainline_maintenance'].update(run_id=run,original_request_sha256=digest(folder/'request.json'),
                stopped_status_sha256=digest(folder/'status.json'),profile_resolution_sha256=digest(folder/'profile-resolution.json'))
            atomic_json(folder/'mainline-maintenance-request.json',request)
            before={p:p.read_bytes() for p in home.rglob('*.json')}
            self.assertEqual(load_theater_resume_request(run,home),request)
            self.assertEqual(before,{p:p.read_bytes() for p in home.rglob('*.json')})
            self.assertFalse(Path(original['settings']['data_dir']).exists())

    def test_routed_maintenance_rejects_missing_changed_or_foreign_receipt(self):
        changes=('missing','hash','run','target','request','mutated','nested_mutated','schema','reason',
                 'previous','root','nested_root','settings')
        for change in changes:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp,patch('mainline_maintenance.process_is_alive',return_value=False):
                root=Path(tmp).resolve();request,state,receipt=self.routed_source(root)
                proof=request['mainline_maintenance']
                if change=='missing':(root/'profile-resolution.json').unlink()
                elif change=='hash':proof['profile_resolution_sha256']='bad'
                elif change=='settings':request['settings']['fast_mode']=False
                else:
                    if change=='run':receipt['run_id']='foreign'
                    elif change=='target':receipt['target']=dict(client='mumu',serial='foreign')
                    elif change=='request':receipt['request_sha256']='foreign'
                    elif change=='mutated':receipt['history_mutated']=True
                    elif change=='nested_mutated':receipt['resolution']['history_mutated']=True
                    elif change=='schema':receipt['resolution']['schema']=2
                    elif change=='reason':receipt['resolution']['reason']='unverified'
                    elif change=='previous':receipt['resolution']['previous_data_dir']='foreign'
                    elif change=='root':receipt['resolved_data_dir']='foreign'
                    elif change=='nested_root':receipt['resolution']['resolved_data_dir']='foreign'
                    atomic_json(root/'profile-resolution.json',receipt)
                    proof['profile_resolution_sha256']=digest(root/'profile-resolution.json')
                with self.assertRaises(ValueError):validate_maintenance(request,root,state)

    def test_exited_display_publish_failure_needs_explicit_diagnostic_hash_not_forged_stop(self):
        with tempfile.TemporaryDirectory() as tmp,patch('mainline_maintenance.process_is_alive',return_value=False):
            root=Path(tmp).resolve();request,state=self.setup_source(root)
            status=dict(mode='blocked',run_id='original-run',status=str(root/'latest.tmp.png')+' system error 5')
            atomic_json(root/'status.json',status)
            diagnostic=root/'diagnostic.log';diagnostic.write_text('runner.py capture\nPermissionError: [WinError 5] '+repr(str(root/'latest.png')),encoding='utf-8')
            proof=request['mainline_maintenance'];proof['stopped_status_sha256']=digest(root/'status.json')
            with self.assertRaises(ValueError):validate_maintenance(request,root,state)
            proof.update(source_exit='latest_display_publish',diagnostic_sha256=digest(diagnostic))
            self.assertEqual(validate_maintenance(request,root,state),proof)
            self.assertEqual(json.loads((root/'status.json').read_text())['mode'],'blocked')
            diagnostic.write_text('different failure')
            with self.assertRaises(ValueError):validate_maintenance(request,root,state)

    def test_changed_source_stop_target_or_live_process_never_loads(self):
        for change in ('state','request','status','stop','target','control','alive','permission'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp,patch('mainline_maintenance.process_is_alive',return_value=change=='alive'):
                root=Path(tmp);r,s=self.setup_source(root)
                if change in ('state','request','status'):(root/(change+'.json')).write_text('{}')
                if change=='stop':(root/'STOP').write_text('stop')
                if change=='target':r=copy.deepcopy(r);r['target']['serial']='changed'
                if change=='control':atomic_json(root/'control.json',dict(run_id='original-run',action='stop',command_id='one-use'))
                if change=='permission':r['mainline_maintenance']['user_authorization']=''
                with self.assertRaises(ValueError):validate_maintenance(r,root,s)

if __name__=='__main__':unittest.main()
