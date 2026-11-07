"""Explicit, hash-bound maintenance of an exited mainline run.

Never a new-start policy or an entry permission. The caller must save a private
source manifest in response to an explicit user continuation/maintenance request.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from assistant_config import read_json,process_is_alive


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def display_failure_exit(proof,folder,root,status):
    """Only an explicitly reviewed, exited latest-display WinError 5 source."""
    path=folder/'diagnostic.log'
    if proof.get('source_exit')!='latest_display_publish' or not path.is_file():return False
    if proof.get('diagnostic_sha256')!=digest(path):return False
    diagnostic=path.read_text(encoding='utf-8')
    return (str(root/'latest.tmp.png') in status.get('status','')
            and 'PermissionError: [WinError 5]' in diagnostic
            and (str(root/'latest.png') in diagnostic or repr(str(root/'latest.png')) in diagnostic) and 'runner.py' in diagnostic)


def settings_match(request,original,root,proof,folder):
    """A routed run keeps its original request and audited effective history.

    Only data_dir may differ, and only by the original worker's hash-bound
    profile-resolution receipt. This is not permission to choose a new profile.
    """
    if request['settings']==original.get('settings'):return True
    path=folder/'profile-resolution.json'
    if not path.is_file() or proof.get('profile_resolution_sha256')!=digest(path):return False
    receipt=read_json(path,{})
    resolution=receipt.get('resolution') or {}
    old=original.get('settings') or {}
    if (receipt.get('run_id')!=original.get('run_id') or receipt.get('target')!=original.get('target')
        or receipt.get('request_sha256')!=digest(folder/'request.json')
        or receipt.get('history_mutated') is not False or resolution.get('history_mutated') is not False
        or resolution.get('schema')!=1 or resolution.get('reason')!='selected_target_original_profile'
        or not old.get('data_dir') or resolution.get('previous_data_dir')!=old['data_dir']
        or receipt.get('resolved_data_dir')!=str(root) or resolution.get('resolved_data_dir')!=str(root)):
        return False
    return request['settings']==dict(old,data_dir=str(root))


def validate_maintenance(request,root,state,*,before_activation=False):
    proof=request.get('mainline_maintenance')
    if not isinstance(proof,dict):raise ValueError('缺少原run维护来源；不保留外来active。')
    folder=Path(request['run_dir']).resolve();root=Path(root).resolve()
    original_path=folder/'request.json';original=read_json(original_path,{})
    status_path=folder/'status.json';status=read_json(status_path,{})
    command=read_json(folder/'control.json',{})
    if (request['settings'].get('task')!='mainline' or request['settings'].get('observe') is not False
        or request['target'].get('client') not in ('mumu','pc') or not settings_match(request,original,root,proof,folder)
        or request['target']!=original.get('target') or request.get('run_id')!=original.get('run_id')
        or request.get('home')!=original.get('home') or Path(original.get('run_dir','')).resolve()!=folder
        or Path(request['settings'].get('data_dir','')).resolve()!=root
        or proof.get('run_id')!=request['run_id'] or not proof.get('nonce')
        or proof.get('original_request_sha256')!=digest(original_path)
        or proof.get('state_sha256')!=digest(root/'state.json')
        or proof.get('stopped_status_sha256')!=digest(status_path)
        or (status.get('mode')!='stopped' and not (status.get('mode')=='blocked' and display_failure_exit(proof,folder,root,status)))
        or status.get('run_id')!=request['run_id']
        or command.get('run_id')!=request['run_id'] or command.get('action')!=('stop' if before_activation else 'run')
        or (not before_activation and command.get('command_id')!=proof['nonce']) or state.get('terminal')
        or (root/'STOP').exists() or not proof.get('user_authorization')):
        raise ValueError('原run维护来源、停止状态或明确接续授权不一致；不恢复、不改写历史。')
    if process_is_alive(proof.get('previous_worker_pid')):
        raise ValueError('原工作进程未退出；不启动第二个写入者。')
    if any(row.get('nonce')==proof['nonce'] for row in state.get('mainline_maintenance_reloads',[])):
        raise ValueError('原run维护来源已消费；不重用。')
    return dict(proof)
