"""Offline checks only: never discover clients, navigate accounts or send game input."""
import argparse,importlib.metadata,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))

def worker_check():
    import cv2,numpy
    from rapidocr_onnxruntime import RapidOCR
    from abyss_templates import TemplateBank
    ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    bank=TemplateBank(ROOT/'assets'/'abyss')
    assert len(bank.entries)==19,'Abyss glyph resources incomplete'
    assert (ROOT/'assets'/'lock.png').is_file(),'Mainline safety template missing'
    assert all(Path(p).resolve().is_relative_to(ROOT) for p in sys.path if p),'Runtime escaped package directory'
    return {'python':sys.version.split()[0],'opencv':cv2.__version__,'numpy':numpy.__version__,'rapidocr':importlib.metadata.version('rapidocr-onnxruntime'),'abyss_glyphs':len(bank.entries),'ocr_models_loaded':True}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--worker',action='store_true');args=ap.parse_args()
    if args.worker:print(json.dumps(worker_check()));return
    out=subprocess.run([str(ROOT/'runtime'/'python.exe'),'-B','-X','utf8',str(__file__),'--worker'],capture_output=True,text=True,encoding='utf-8',timeout=90)
    if out.returncode:raise RuntimeError(out.stderr or out.stdout)
    result={'worker':json.loads(out.stdout)}
    with tempfile.TemporaryDirectory(prefix='epic7-ui-check-') as folder:
        env=os.environ.copy();env['EPIC7_ASSISTANT_HOME']=folder
        check=subprocess.run([str(ROOT/'gui'/'python.exe'),'-B','-X','utf8',str(ROOT/'portable_entry.py'),'--ui-check'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        if check.returncode:raise RuntimeError(check.stderr)
        ui=json.loads((Path(folder)/'ui-check.json').read_text(encoding='utf-8'))
        assert ui['controls_visible'] and ui['permission_visible'] and ui['observe_visible']
        assert ui['footer_bottom']<=ui['workarea'][3]
        result['gui']=ui
    result['result']='PASS - offline runtime/UI/resource checks only; no game input or account history created'
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
