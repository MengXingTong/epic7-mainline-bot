"""Offline checks only: never discover clients, navigate accounts or send game input."""
import importlib.metadata,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from ui_text import ChineseArgumentParser

def worker_check():
    import cv2,numpy
    from rapidocr_onnxruntime import RapidOCR
    from abyss_templates import TemplateBank
    import task_blockers,task_overlays,task_timing,mainline_map,story_core,windows_elevation
    from theater_vision import TheaterVision
    import theater_core,theater_journal,theater_worker,theater_directory
    import theater_ticket_ocr,theater_pending_confirmation
    import dimension_core,dimension_journal,dimension_worker
    theater=TheaterVision()
    assert set(theater.templates)=={'story','battle'},'月光剧场识别资源不完整。'
    from pc_message_backend import CaptureUnavailable
    ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    bank=TemplateBank(ROOT/'assets'/'abyss')
    assert len(bank.entries)==19,'深渊字形资源不完整。'
    assert story_core.SAINT_STAGE=='3-7'
    assert (ROOT/'assets'/'lock.png').is_file(),'缺少主线安全识别模板。'
    assert all(Path(p).resolve().is_relative_to(ROOT) for p in sys.path if p),'运行库路径越出软件包目录。'
    return {'python':sys.version.split()[0],'opencv':cv2.__version__,'numpy':numpy.__version__,'rapidocr':importlib.metadata.version('rapidocr-onnxruntime'),'abyss_glyphs':len(bank.entries),'ocr_models_loaded':True}

def main():
    ap=ChineseArgumentParser();ap.add_argument('--worker',action='store_true');args=ap.parse_args()
    if args.worker:print(json.dumps(worker_check()));return
    out=subprocess.run([str(ROOT/'runtime'/'python.exe'),'-B','-X','utf8',str(__file__),'--worker'],capture_output=True,text=True,encoding='utf-8',timeout=90)
    if out.returncode:raise RuntimeError(out.stderr or out.stdout)
    result={'worker':json.loads(out.stdout)}
    with tempfile.TemporaryDirectory(prefix='epic7-ui-check-') as folder:
        env=os.environ.copy();env['EPIC7_ASSISTANT_HOME']=folder
        check=subprocess.run([str(ROOT/'gui'/'python.exe'),'-B','-X','utf8',str(ROOT/'portable_entry.py'),'--ui-check'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        if check.returncode:raise RuntimeError(check.stderr)
        ui=json.loads((Path(folder)/'ui-check.json').read_text(encoding='utf-8'))
        assert ui['controls_visible'] and ui['direct_start']
        assert not ui['observation_switch_present'] and not ui['account_check_required'] and not ui['foreground_selector_present']
        assert not ui['count_limit_present'] and ui['continuous_run']
        assert ui['footer_bottom']<=ui['workarea'][3]
        assert ui['tasks']==['mainline','abyss','saint_3_7','dimension','theater']
        result['gui']=ui
    result['result']='检查通过：仅验证离线运行库、界面和资源；未发送游戏输入，也未创建账号历史。'
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
