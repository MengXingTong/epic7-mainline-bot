"""Build a clean offline Windows x64 preview from an explicit allowlist.
No download, publishing, live config copy, or account files. Runtimes stay untracked.
"""
from pathlib import Path
import hashlib,importlib.metadata,json,shutil,sys,zipfile
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from ui_text import ChineseArgumentParser
SOURCES=('dimension_vision.py','dimension_ocr.py','dimension_routes.py','dimension_route_vision.py','dimension_core.py','dimension_journal.py','dimension_worker.py','ui_text.py','assistant_app.py','assistant_config.py','assistant_status.py','assistant_portable.py','assistant_control.py','assistant_worker.py','assistant_transport.py','task_blockers.py','task_overlays.py','task_timing.py','mainline_map.py','story_core.py','windows_elevation.py','abyss_core.py','abyss_templates.py','pc_backend.py','pc_message_backend.py','pc_message_probe.py','pc_quickstart.py','pc_startup.py','pc_profile.py','mainline_reconcile.py','runner.py','runtime_paths.py','state_tools.py','launcher.py','supervisor.py','portable_entry.py','portable_selfcheck.py','Assistant.cmd','requirements.txt','CHANGELOG.md')
SOURCES+=('client_viewport.py','entry_journal.py','story_open_ack.py','free_notices.py','Start.cmd','PCStart.cmd')
SOURCES+=('mumu_discovery.py','assistant_instances.py')
SOURCES+=('progression_evidence.py','progression_facts.py','map_identity.py','entry_preparation.py')
SOURCES+=('ui_control_guard.py','chat_recovery.py')
SOURCES+=('arena_core.py','arena_worker.py','arena_journal.py','arena_vision.py')
SOURCES+=('penguin_core.py','penguin_vision.py','penguin_journal.py','penguin_worker.py')
SOURCES+=('theater_core.py','theater_vision.py','theater_journal.py','theater_worker.py')
SOURCES+=('tutorial_core.py','tutorial_ocr.py','mainline_maintenance.py','story_reopen.py','free_story_handoff.py','mainline_story_results.py')
SOURCES+=('tutorial_entry_handoff.py','tutorial_control_templates.py','tutorial_navigation.py','tutorial_team_dialog.py','tutorial_battle_confirmation.py')
SOURCES+=('theater_directory.py','theater_ticket_ocr.py','theater_pending_confirmation.py')
VERSION='1.4.12-preview'
RELEASE_DATE='2026-11-07'


def copy_tree(source,target):
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo','*.log','*.dmp'))


def copy_source_file(source,target):
    """启动脚本保持 UTF-8 和 Windows 换行；其他源码按原字节复制。"""
    source=Path(source);target=Path(target)
    if source.suffix.lower()=='.cmd':
        text=source.read_text(encoding='utf-8-sig').replace('\r\n','\n').replace('\r','\n')
        target.write_bytes(text.replace('\n','\r\n').encode('utf-8'))
    else:shutil.copy2(source,target)


def build(args):
    out=args.output.resolve()
    if out.exists():raise ValueError('输出目录已存在；禁止覆盖已有发布包。')
    for file in SOURCES:
        if not (ROOT/file).is_file():raise ValueError('缺少源文件：'+file)
    model=json.loads((args.glyphs/'templates'/'model.json').read_text(encoding='utf-8'))
    if len(model['entries'])!=19:raise ValueError('应当恰好提供 19 个字形资源。')
    out.mkdir(parents=True)
    for file in SOURCES:
        copy_source_file(ROOT/file,out/file)
    (out/'assets').mkdir();shutil.copy2(ROOT/'assets'/'lock.png',out/'assets'/'lock.png')
    (out/'assets'/'theater').mkdir()
    for name in ('story.png','battle.png'):
        shutil.copy2(ROOT/'assets'/'theater'/name,out/'assets'/'theater'/name)
    shutil.copy2(ROOT/'assets'/'theater'/'README.md',out/'assets'/'theater'/'README.md')
    target=out/'assets'/'abyss'/'templates';target.mkdir(parents=True)
    from PIL import Image
    entries=[]
    for row in model['entries']:
        filename=row['file']
        if Path(filename).name!=filename:raise ValueError('字形资源路径越界，已拒绝打包。')
        with Image.open(args.glyphs/'templates'/filename) as image:
            if image.size!=(112,40) or image.mode!='L' or set(image.tobytes())!={0,255}:raise ValueError('资源不是二值战斗界面字形掩码。')
            Image.frombytes('L',image.size,image.tobytes()).save(target/filename)
        entries.append({k:row[k] for k in ('name','file','text','rect','threshold') if k in row})
    (target/'model.json').write_text(json.dumps({'format':'限定位置的二值界面字形；不含账号或完整截图','entries':entries},ensure_ascii=False,indent=2),encoding='utf-8')
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
    (out/'portable.json').write_text(json.dumps({'app':'第七史诗统一助手','version':VERSION,'platform':'Windows 64 位','offline':True},indent=2),encoding='utf-8')
    shutil.copy2(ROOT/'docs'/'SHARE_README.md',out/'README_zh-CN.md')
    shutil.copy2(ROOT/'docs'/'STORY_VALIDATION_2026-11-03.md',out/'VALIDATION.md')
    shutil.copy2(ROOT/'docs'/'STALL_VALIDATION_2026-11-04.md',out/'STALL_VALIDATION.md')
    shutil.copy2(ROOT/'docs'/'DIMENSION_VALIDATION_2026-11-03.md',out/'DIMENSION_VALIDATION.md')
    shutil.copy2(ROOT/'docs'/'THEATER_VALIDATION_2026-11-05.md',out/'THEATER_VALIDATION.md')
    shutil.copy2(ROOT/'docs'/'MAINLINE_VALIDATION_2026-11-07.md',out/'MAINLINE_VALIDATION.md')
    shutil.copy2(out/'Assistant.cmd',out/'启动助手.cmd')
    (out/'SelfCheck.cmd').write_text('@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\n"%~dp0gui\\python.exe" -B -X utf8 "%~dp0portable_selfcheck.py"\r\necho.\r\npause\r\n',encoding='ascii',newline='')
    notices='离线预览版 '+VERSION+'\n\n'+'第三方软件与发布说明\n\n本包为 Windows 64 位离线预览版。\n界面运行库 CPython 3.11 许可：gui/LICENSE.txt。\n工作运行库 CPython 3.12 许可：runtime/LICENSE.txt。\nTcl/Tk 许可：gui/tcl/tcl8.6/license.terms 与 gui/tcl/tk8.6/license.terms。\n界面图像库 Pillow 许可与元数据：gui/site-packages/pillow-*.dist-info。\n工作依赖的许可与元数据：vendor/*.dist-info 和各依赖目录。\n工作依赖版本见 requirements.txt；界面运行库版本见 BUILD_INFO.json。\n\n不分发游戏、MuMu 模拟器、ADB 程序、账号、凭据、私有进度、完整游戏截图或日志。\n识别素材仅含通用锁图标裁片及 19 个限定位置的二值战斗界面字形掩码；\n这些是游戏界面参考素材，不是本项目宣称原创的游戏美术。\n不承诺兼容性或账号安全；不注入、不修改内存，也不绕过安全机制。\n'
    gui_pillow=next(d.version for d in importlib.metadata.distributions(path=[str(site)]) if d.metadata['Name'].lower()=='pillow')
    notices+='\n月光剧场另含两块去元数据的灰度通用界面图标，来源及实验性识别边界见 assets/theater/README.md；不含完整游戏截图或账号画面。\n'
    (out/'THIRD_PARTY_NOTICES.txt').write_text(notices,encoding='utf-8')
    (out/'BUILD_INFO.json').write_text(json.dumps({'version':VERSION,'built_date':RELEASE_DATE,'gui_python':'3.11','gui_pillow':gui_pillow,'worker_python':'3.12','sources':list(SOURCES),'privacy':'仅包含白名单源码、运行库、二值字形和通用控制图标；不含私有目录或实时数据'},indent=2),encoding='utf-8')
    files=[p for p in out.rglob('*') if p.is_file()]
    for p in files:
        rel=p.relative_to(out)
        if any(part in ('.local','.git','evidence','__pycache__') for part in rel.parts) or p.name in ('state.json','config.json','settings.json','latest.png') or p.suffix in ('.log','.pyc'):raise ValueError('发布包中发现私有文件：'+str(rel))
        if p.suffix in ('.py','.json','.txt','.md','.cmd','._pth'):
            text=p.read_text(encoding='utf-8',errors='ignore').replace('\\','/')
            if 'C:/Users/Administrator' in text or 'E:/CodeProjects/Codex' in text:raise ValueError('发布包中发现本机路径：'+str(rel))
    checksums={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    (out/'SHA256SUMS.json').write_text(json.dumps(checksums,indent=2),encoding='utf-8')
    if args.zip:
        archive=out.with_name(out.name+'.zip')
        if archive.exists():raise ValueError('压缩包已存在，禁止覆盖。')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in sorted(out.rglob('*')):
                if p.is_file():z.write(p,out.name+'/'+p.relative_to(out).as_posix())
        print(str(archive))
    print(json.dumps({'directory':str(out),'files':len(checksums)+1,'bytes':sum(p.stat().st_size for p in out.rglob('*') if p.is_file())}))


def build_update(package):
    """Small overlay for an existing v1.1 full package. Never contains private data/runtimes."""
    package=Path(package).resolve()
    record=json.loads((package/'portable.json').read_text(encoding='utf-8'))
    if record['version']!=VERSION:raise ValueError('更新文件的版本不匹配。')
    archive=package.with_name('Epic7-Assistant-update-'+VERSION+'.zip')
    if archive.exists():raise ValueError('更新压缩包已存在，禁止覆盖。')
    names=set(SOURCES)|{'portable.json','BUILD_INFO.json','README_zh-CN.md','VALIDATION.md','STALL_VALIDATION.md','DIMENSION_VALIDATION.md','THIRD_PARTY_NOTICES.txt','SHA256SUMS.json','SelfCheck.cmd','启动助手.cmd'}
    names.update(('THEATER_VALIDATION.md','MAINLINE_VALIDATION.md'))
    names|={p.relative_to(package).as_posix() for p in (package/'assets').rglob('*') if p.is_file()}
    instructions=f"""第七史诗统一助手 {VERSION} 覆盖更新补丁（需要 v1.1 / v1.2 / v1.3 / v1.4 / v1.4.1 / v1.4.2 / v1.4.3 / v1.4.4 / v1.4.5 / v1.4.6 / v1.4.7 / v1.4.8 / v1.4.9 / v1.4.10 / v1.4.11 完整离线包）

1. 先停止任务并关闭助手；不用关闭游戏。
2. 将本 ZIP 内全部文件解压/复制到原软件目录，确认覆盖同名程序文件。
   是覆盖旧目录，不是只在新的补丁目录运行；补丁不含运行库。
3. 不删除 .local、state.json、evidence 或原进度目录！本补丁没有这些文件，不会清空进度。
4. 再双击旧目录中的 启动助手.cmd。

v1.4.12 修复AUTO开启的首次入场被战斗指南误拦；仅确认原唯一入场，不点不再显示、不重开。
主线使用当前周期已知控件及地图通关/原锁定后继解锁事实推进，不把点击、等待或缺切页判作战败。
包含误触聊天原生返回恢复、多助手按目标互斥、MuMu实例发现与原进度路由修复。
新增指定次数NPC竞技场（实验性）；每把独立胜利返回列表后才继续，不买挑战书、不重试失败。
仅有限本机PC 7把NPC闭环已实测；MuMu竞技场、多开并行实战、其他几何/跨机器仍未验收。
聊天自动关闭与AUTO战力确认仍无本次实机完整闭环，不能因离线测试通过声称实机已修复全部场景。
完整已知页面不等待整屏特效静止；未知/资源/容量/战败/窗口/过期/关键落盘保护保留。
仅保留已审计原路径的同run维护来源，不分发私人状态或一次性接续许可。

v1.4.11 修复普通UI按下前全局按键冲突的临时让行、旧帧重新取图与入场响应等待被提前清除。
完整免费章节奖励布局不再按Episode/章节标题格式硬拦截；标题仅辅助，不放开外传未知入场。
地图数字受名称/罗马数字/分隔点影响时，仅对本帧数字独立高置信复核，不抬高名称分数、不猜编号。
章末裁切故事仅在同run完整播放/奖励/原始发送及当前独立通关勾核实后确认结果，不重放旧关。
旧纯剧情active不能认领后续战斗/胜利/战斗结算；原attempted/sent/归档与全部证据保留。
本次严格两行结果分支以原图回放及隔离集成验证为主，不宣称已实机自动触发全部变体。
不自动补发耗体力战斗/门票，不重试战败、不购买或兑换体力、不资源复活。PC后台仍为实验性。
更新前必须停止任务并关闭旧助手；不要删除.local、state.json、evidence或原进度。
完整验证范围见 MAINLINE_VALIDATION.md。

v1.4.10 修复免费教学通知关闭后原故事入口仍被误拦截；通知按每次出现独立核验。
原sent不当作游戏接受或通关，同run零体力入口只按证据链有界响应，不能真实重播或战败重试。
鼠标仅悬停/移入游戏客户区不再暂停；实际按键、拖动、窗口/最小化/新鲜度保护仍保留。
预览或latest展示被文件占用不再直接杀死worker；当前独立截图/OCR证据和关键记录必须写入成功。
包含开发中的新手教学和实验性PC买企鹅任务；买企鹅须显式选择任务并填写本次总只数。
买企鹅最终扣费/多批购买未实机验收，主线不自动启动购买；不购买/兑换体力，不付费复活。
完整边界与本次包验收见 MAINLINE_VALIDATION.md；没有新建或带入任何私人接续许可。

v1.4.9 包含实验性PC月光剧场和次元探查；次元仍为开发中，不能当成全关卡通关版。
剧场库存采用通用数字与标签双复核，终波统一核验N/N，免费奖励与日期/升级通知按完整前景证据处理。
完整已知页面先核验控件与业务链，不等待背景特效整屏静止；未知、黑帧、未知弹窗仍零输入。
门票、入场、失败与原历史保护保留，不自动生成旧归档接续授权；私有授权凭据不随包分发。
本机PC后台曾验证连续两集的首次扣票、播放、领奖与独立完成行，不能推广为其他机器/字体/分辨率或MuMu剧场已验收。
完整范围见 THEATER_VALIDATION.md、DIMENSION_VALIDATION.md 与 CHANGELOG.md。
更新只覆盖程序、资源与说明，不包含账号、截图、OCR、日志、设备配置或凭据；不要删除原进度。

以下为历史版本变更（与上述本次规则冲突时以上述规则为准）：

v1.4.8 在画面/控件持续变化时保持零输入观察，稳定后再判断；用户操作时先让行。
普通深渊未确认/容量弹窗也先等稳定；主按钮运行/等待时保持白字。
PC规划前单纯过期会持续重取；已明确未发送的普通地图/辅助选队导航也重新截图规划。
入场意图、发送不明、窗口/进程/几何异常仍按原规则保护，不自动重开战斗。
本次新增离线回归、包自检和只读画面观察，没有新增修复后整场实机战斗验收；详见STALL_VALIDATION.md。

v1.4.7 修复好感度提升提示覆盖在战斗结算页时，被底层“确认”误判为冲突而卡住。
只有前景标题/关闭控件及底层“获得的道具”“战斗结果”和唯一右下角确认全部明确，才点击前景“轻触后关闭”；其他确认、资源、购买、复活和战败继续拦截。
关闭后重新取图处理独立结算，不点击被遮住的确认，不把关闭提示记为通关。本次仅保存画面离线回放与包自检。

v1.4.6 修复辅助英雄空位且没有AUTO的队伍页入场；完整布局与普通任务按钮核验后只进行一次普通入场，不操作托管或重复设置。
从队伍页新开始仍可能先返回当前地图核对关卡；地图/编号、体力、历史、落盘和防重复检查保留。未知布局保持停止，战斗内自动设置未在空位页确认。
本次仅离线回归与包自检，未新增完整实机战斗验收；更新前停止旧任务和助手，更新后显式开始加载新代码。

v1.4.5 每次启动默认自动识别客户端，保留上次任务；支持实验性 PC 横向最大化客户区与明确黑边映射。
鼠标/按键接管时先让行，输入空闲后重新取图；普通导航与窗口问题可进入等待处理。
只有后端明确证明开战按下尚未发送，才允许用户点继续后重新核对并完成首次入场；原入场和失败记录保留。
普通深渊按标准尺寸 OCR 后映射回原窗口，可从完整识别的当前准备页开始。
本次最大化和输入恢复只做离线回归，真实最大化战斗、跨机器后台兼容仍待验收。

v1.4.4 修复英雄亲密度等级上升提示遮住结算：只点击本帧“轻触后关闭”，重新截图后再读取独立结算，不点击背后的下一层或把弹层当通关。
标题或关闭控件缺失时不猜坐标；资源、付费、容量、战败和确认覆盖层优先。

v1.4.3 修复从正在进行的自动战斗启动被误判停机：识别战斗后只等待结算，不要求本次助手亲自开战。
取消深渊纯等待的15秒/20分钟停机门槛；未知画面继续取图、零输入，不把OCR空档当成游戏无响应。
从战斗画面开始不会补写入场、推断层数或虚增通关；付费、战败、目标守卫与不重复入场规则不变。
未完成的次元探查开发项不包含在本更新中。

本次统一界面、状态、安全报错、命令行和自检提示为中文，保留内部配置与识别标签。
修复中文启动脚本打包编码及内部只读验证的客户端名称映射；不扩大实验性兼容范围。
本包保留版本服务器错误三标签识别修复；仅按原限流网络重连，不重启游戏、不重打未结算关卡。
本次将主线入口统一为“推进剧情关卡”，增加圣女3-7模式及老版自由地图/出口兼容。
圣女模式需先打开已解锁的《圣女追悼文》，推进至3-7成功结算后只重复3-7；每次独立记录，战败或结果不明不重试。
剧情体力不足在队伍页等待自然恢复，不购买/兑换；PC地图拖动仍走后台消息，不抢焦点。
保留取消推进次数上限：界面移除次数输入，主线/普通深渊均持续推进，旧limit设置不再生效。
不是把30改成更大的数字；没有隐藏的关数/层数上限。暂停、停止、战败和资源不足处理不变。
保留地图误判修复：未检测到星级不算已通关，已有入场记录不当成应跳过的已完成关。
每一行都检测锁定，不能再点击带锁的下一关；绿色像素改为通关徽章形状+节点绿环联合证据。
识别有明确通关星级标签的0～3星文本作为补充；信用等级、英雄稀有度、章节星数不参与关卡完成判定。
保留v1.3的导航提速、无确认按钮的等级提升页、后台短暂黑帧重取，不重复点击。
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
            if not path.is_file() or not path.resolve().is_relative_to(package):raise ValueError('更新路径无效。')
            z.write(path,name)
        z.writestr('UPDATE_README.txt',instructions)
    return archive


def main():
    ap=ChineseArgumentParser()
    for name in ('output','gui-runtime','worker-runtime','vendor','glyphs'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--zip',action='store_true');build(ap.parse_args())

if __name__=='__main__':main()
