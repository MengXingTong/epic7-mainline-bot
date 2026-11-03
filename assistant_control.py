"""Run-bound controls; maintenance reloads go through the existing GUI, never the game."""
import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ui_text import ACTION_NAMES,ChineseArgumentParser
from assistant_config import HOME,read_json,atomic_json

def main():
    ap=ChineseArgumentParser();ap.add_argument('action',choices=('stop','pause','resume','restart','status'));ap.add_argument('--task',choices=('mainline','abyss','saint_3_7'));a=ap.parse_args()
    active=read_json(HOME/'active-run.json',{})
    if not active:print('当前没有运行中的统一助手工作进程。');return
    folder=Path(active['run_dir']).resolve()
    if folder.parent!=(HOME/'runs').resolve():raise ValueError('任务目录不在受管理的工作区内。')
    status=read_json(folder/'status.json',{})
    if status.get('run_id')!=active['run_id']:raise ValueError('工作进程身份不匹配，已拒绝操作。')
    if a.action=='status':
        import json
        print(json.dumps(status,ensure_ascii=False,indent=2));return
    if a.action=='restart':
        request=read_json(folder/'request.json',{})
        atomic_json(HOME/'gui-command.json',{'command_id':uuid.uuid4().hex,'action':'restart','expected_run_id':active['run_id'],'task':a.task or request.get('settings',{}).get('task','mainline')})
        print('已通过现有界面请求安全重启工作进程；未重置历史或重启游戏。');return
    if a.action=='resume' and status.get('mode') not in ('paused','attention'):raise ValueError('只有已暂停或等待处理的工作进程才能继续；未执行重启。')
    atomic_json(folder/'control.json',{'run_id':active['run_id'],'action':'run' if a.action=='resume' else a.action,'command_id':uuid.uuid4().hex})
    print('已请求'+ACTION_NAMES[a.action]+'；游戏和历史记录保持不变。')

if __name__=='__main__':main()
