"""Build a clean offline Windows x64 preview from an explicit allowlist.
No download, publishing, live config copy, or account files. Runtimes stay untracked.
"""
from pathlib import Path
import argparse,hashlib,importlib.metadata,json,shutil,sys,zipfile
ROOT=Path(__file__).resolve().parent
SOURCES=('assistant_app.py','assistant_config.py','assistant_status.py','assistant_portable.py','assistant_control.py','assistant_worker.py','assistant_transport.py','task_blockers.py','task_overlays.py','task_timing.py','mainline_map.py','windows_elevation.py','abyss_core.py','abyss_templates.py','pc_backend.py','pc_message_backend.py','pc_message_probe.py','pc_quickstart.py','pc_startup.py','pc_profile.py','mainline_reconcile.py','runner.py','runtime_paths.py','state_tools.py','launcher.py','supervisor.py','portable_entry.py','portable_selfcheck.py','Assistant.cmd','requirements.txt','CHANGELOG.md')
VERSION='1.3.1-preview'


def copy_tree(source,target):
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo','*.log','*.dmp'))


def build(args):
    out=args.output.resolve()
    if out.exists():raise ValueError('Output already exists; never overwrite a release')
    for file in SOURCES:
        if not (ROOT/file).is_file():raise ValueError('Missing source: '+file)
    model=json.loads((args.glyphs/'templates'/'model.json').read_text(encoding='utf-8'))
    if len(model['entries'])!=19:raise ValueError('Expected exactly 19 glyphs')
    out.mkdir(parents=True)
    for file in SOURCES:
        shutil.copy2(ROOT/file,out/file)
        if file.endswith('.cmd'):(out/file).write_bytes((ROOT/file).read_text(encoding='ascii').replace('\r\n','\n').replace('\n','\r\n').encode('ascii'))
    (out/'assets').mkdir();shutil.copy2(ROOT/'assets'/'lock.png',out/'assets'/'lock.png')
    target=out/'assets'/'abyss'/'templates';target.mkdir(parents=True)
    from PIL import Image
    entries=[]
    for row in model['entries']:
        filename=row['file']
        if Path(filename).name!=filename:raise ValueError('Glyph path traversal')
        with Image.open(args.glyphs/'templates'/filename) as image:
            if image.size!=(112,40) or image.mode!='L' or set(image.tobytes())!={0,255}:raise ValueError('Not a binary HUD glyph mask')
            Image.frombytes('L',image.size,image.tobytes()).save(target/filename)
        entries.append({k:row[k] for k in ('name','file','text','rect','threshold') if k in row})
    (target/'model.json').write_text(json.dumps({'format':'position-constrained binary UI glyphs; no account/full screenshots','entries':entries},ensure_ascii=False,indent=2),encoding='utf-8')
    copy_tree(args.worker_runtime,out/'runtime');copy_tree(args.vendor,out/'vendor')
    (out/'runtime'/'python312._pth').write_text('python312.zip\n.\nDLLs\n../vendor\n..\nimport site\n',encoding='ascii')
    gui=out/'gui';gui.mkdir();(gui/'site-packages').mkdir()
    for name in ('python.exe','pythonw.exe','python3.dll','python311.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
        if (args.gui_runtime/name).exists():shutil.copy2(args.gui_runtime/name,gui/name)
    copy_tree(args.gui_runtime/'DLLs',gui/'DLLs')
    (gui/'tcl').mkdir()
    for name in ('tcl8','tcl8.6','tk8.6'):copy_tree(args.gui_runtime/'tcl'/name,gui/'tcl'/name)
    with zipfile.ZipFile(gui/'python311.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted((args.gui_runtime/'Lib').rglob('*')):
            rel=p.relative_to(args.gui_runtime/'Lib')
            if not p.is_file() or any(x in ('site-packages','test','tests','__pycache__','ensurepip','idlelib','turtledemo','venv') for x in rel.parts) or p.suffix in ('.pyc','.pyo'):continue
            z.write(p,rel.as_posix())
    site=args.gui_runtime/'Lib'/'site-packages'
    copy_tree(site/'PIL',gui/'site-packages'/'PIL')
    for meta in site.glob('pillow-*.dist-info'):copy_tree(meta,gui/'site-packages'/meta.name)
    (gui/'python311._pth').write_text('python311.zip\n.\nDLLs\nsite-packages\n..\nimport site\n',encoding='ascii')
    # Keep no local settings or profile. Recipient creates their own only after consent + proof.
    (out/'portable.json').write_text(json.dumps({'app':'Epic7 Unified Assistant','version':VERSION,'platform':'Windows x64','offline':True},indent=2),encoding='utf-8')
    shutil.copy2(ROOT/'docs'/'SHARE_README.md',out/'README_zh-CN.md')
    shutil.copy2(ROOT/'docs'/'RELEASE_VALIDATION_2026-11-02.md',out/'VALIDATION.md')
    shutil.copy2(out/'Assistant.cmd',out/'启动助手.cmd')
    (out/'SelfCheck.cmd').write_text('@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\n"%~dp0gui\\python.exe" -B -X utf8 "%~dp0portable_selfcheck.py"\r\necho.\r\npause\r\n',encoding='ascii',newline='')
    notices='Offline Windows x64 preview '+VERSION+'\n\nCPython 3.11 GUI license: gui/LICENSE.txt. CPython 3.12 worker license: runtime/LICENSE.txt.\nTcl/Tk licenses: gui/tcl/tcl8.6/license.terms and gui/tcl/tk8.6/license.terms.\nPillow GUI license/metadata: gui/site-packages/pillow-*.dist-info.\nWorker dependency licenses/metadata: vendor/*.dist-info and package directories.\nSee requirements.txt for worker versions; BUILD_INFO.json lists GUI version.\n\nNot distributed: game, MuMu, ADB binary, accounts, credentials, private progress, full game screenshots, logs.\nRecognition assets: one generic padlock crop and 19 position-constrained binary HUD glyph masks. These are game UI reference material, not original game art claimed by this project.\nNo compatibility/account safety warranty. No injection, memory modification or security bypass.\n'
    (out/'THIRD_PARTY_NOTICES.txt').write_text(notices,encoding='utf-8')
    gui_pillow=next(d.version for d in importlib.metadata.distributions(path=[str(site)]) if d.metadata['Name'].lower()=='pillow')
    (out/'BUILD_INFO.json').write_text(json.dumps({'version':VERSION,'built_date':'2026-11-02','gui_python':'3.11','gui_pillow':gui_pillow,'worker_python':'3.12','sources':list(SOURCES),'privacy':'allowlisted sources + runtimes + binary glyph masks only; no .local or live data'},indent=2),encoding='utf-8')
    files=[p for p in out.rglob('*') if p.is_file()]
    for p in files:
        rel=p.relative_to(out)
        if any(part in ('.local','.git','evidence','__pycache__') for part in rel.parts) or p.name in ('state.json','config.json','settings.json','latest.png') or p.suffix in ('.log','.pyc'):raise ValueError('Private file in release: '+str(rel))
        if p.suffix in ('.py','.json','.txt','.md','.cmd','._pth'):
            text=p.read_text(encoding='utf-8',errors='ignore').replace('\\','/')
            if 'C:/Users/Administrator' in text or 'E:/CodeProjects/Codex' in text:raise ValueError('Local machine path in release: '+str(rel))
    checksums={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    (out/'SHA256SUMS.json').write_text(json.dumps(checksums,indent=2),encoding='utf-8')
    if args.zip:
        archive=out.with_name(out.name+'.zip')
        if archive.exists():raise ValueError('Archive already exists')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in sorted(out.rglob('*')):
                if p.is_file():z.write(p,out.name+'/'+p.relative_to(out).as_posix())
        print(str(archive))
    print(json.dumps({'directory':str(out),'files':len(checksums)+1,'bytes':sum(p.stat().st_size for p in out.rglob('*') if p.is_file())}))


def build_update(package):
    """Small overlay for an existing v1.1 full package. Never contains private data/runtimes."""
    package=Path(package).resolve()
    record=json.loads((package/'portable.json').read_text(encoding='utf-8'))
    if record['version']!=VERSION:raise ValueError('Update payload version mismatch')
    archive=package.with_name('Epic7-Assistant-update-'+VERSION+'.zip')
    if archive.exists():raise ValueError('Update archive already exists')
    names=set(SOURCES)|{'portable.json','BUILD_INFO.json','README_zh-CN.md','VALIDATION.md','THIRD_PARTY_NOTICES.txt','SHA256SUMS.json','SelfCheck.cmd','启动助手.cmd'}
    names|={p.relative_to(package).as_posix() for p in (package/'assets').rglob('*') if p.is_file()}
    instructions=f"""第七史诗统一助手 {VERSION} 覆盖更新补丁（需要 v1.1 / v1.2 / v1.3 完整离线包）

1. 先停止任务并关闭助手；不用关闭游戏。
2. 将本 ZIP 内全部文件解压/复制到原软件目录，确认覆盖同名程序文件。
   是覆盖旧目录，不是只在新的补丁目录运行；补丁不含运行库。
3. 不删除 .local、state.json、evidence 或原进度目录！本补丁没有这些文件，不会清空进度。
4. 再双击旧目录中的 启动助手.cmd。

本次修复地图误判：未检测到星级不算已通关，已有入场记录不再被当成应跳过的已完成关。
每一行都检测锁定，不能再点击带锁的下一关；绿色像素改为通关徽章形状+节点绿环联合证据。
识别有明确通关星级标签的0～3星文本作为补充；信用等级、英雄稀有度、章节星数不参与关卡完成判定。
保留v1.3的导航提速、无确认按钮Rank升级页、后台短暂黑帧重取，不重复点击。
装备/神器/英雄容量等提示进入“等待处理”，处理后可继续，不判为战败、不自动卖物品或扩容。
停止后可再次开始；不回看旧关、不要求补记；旧入场与失败证据保留，不重复入场。
PC只保留后台窗口消息，旧前台设置自动迁移；整场后台/跨机器兼容仍为实验性，不支持最小化。
启动器自动申请标准管理员权限，首次系统UAC仍需本人点“是”，不绕过权限。
保留直接启动：不核查账号/服务器，没有“仅观察”/额外确认勾选。
仅覆盖程序文件，不修改.local和用户进度；旧STOP只在显式新开始时完整归档，新停止仍立即生效。
"""
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name in sorted(names):
            path=package/name
            if not path.is_file() or not path.resolve().is_relative_to(package):raise ValueError('Invalid update path')
            z.write(path,name)
        z.writestr('UPDATE_README.txt',instructions)
    return archive


def main():
    ap=argparse.ArgumentParser()
    for name in ('output','gui-runtime','worker-runtime','vendor','glyphs'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--zip',action='store_true');build(ap.parse_args())

if __name__=='__main__':main()
