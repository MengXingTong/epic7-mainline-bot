"""Read-only discovery of online local Android instances and their current app.

No guessed port range, emulator launch, game launch, focus change or game input.
Manager metadata and saved packages never veto an already online instance.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import json,re,subprocess,time


def local_port(serial):
    match=re.fullmatch(r'(?:127\.0\.0\.1|localhost):([0-9]{1,5})',str(serial))
    if match and 1024<int(match[1])<=65535 and int(match[1])!=5037:
        return int(match[1])
    return None


def find_manager(adb):
    # Only the installation associated with the selected adb, not a disk/port scan.
    adb=Path(adb).resolve()
    for parent in list(adb.parents)[:4]:
        for relative in ('MuMuManager.exe','nx_main/MuMuManager.exe'):
            candidate=parent/relative
            if candidate.is_file():return candidate
    return None


def resumed_package(activity):
    """Read the actual foreground component, independently of distribution names."""
    packages=set()
    for line in activity.splitlines():
        if not re.match(r'\s*(?:topResumedActivity|mResumedActivity)\s*[:=]',line):continue
        match=re.search(r'(?:^|\s|=)([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/[A-Za-z0-9_.$]+',line)
        if match:packages.add(match[1])
    return next(iter(packages)) if len(packages)==1 else None


def manager_instances(value):
    if not isinstance(value,dict):raise ValueError('MuMu管理器未返回实例对象。')
    eligible=[]
    for key,row in value.items():
        if not isinstance(row,dict) or not re.fullmatch(r'[0-9]+',str(key)):continue
        # Manager versions differ in status/PID fields. ADB proves reachability.
        host=row.get('adb_host_ip','127.0.0.1')
        serial=f'{host}:{row.get("adb_port", "")}'
        port=local_port(serial)
        if port is None:continue
        name=''.join(c for c in str(row.get('name','')) if c.isprintable()).strip()[:80]
        eligible.append(dict(index=int(key),name=name,serial=f'127.0.0.1:{port}',port=port))
    counts=Counter(r['port'] for r in eligible)
    return sorted((r for r in eligible if counts[r['port']]==1),key=lambda r:r['index'])


def discover_mumu(adb,cfg,*,run=None,clock=None,manager=None,budget=16):
    run=run or subprocess.run;clock=clock or time.monotonic
    deadline=clock()+budget;warnings=[]
    def command(args,timeout):
        remaining=deadline-clock()
        if remaining<=0:raise TimeoutError('实例发现时间预算已用尽。')
        return run([str(p) for p in args],capture_output=True,timeout=min(timeout,remaining),
                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def devices():
        result=command([adb,'devices'],4)
        if result.returncode:raise OSError('ADB设备列表读取失败。')
        rows=[];seen=set()
        for line in result.stdout.decode('utf-8-sig',errors='replace').splitlines():
            fields=line.split()
            if len(fields)<2 or fields[1]!='device':continue
            port=local_port(fields[0])
            if port is None or port in seen:continue
            rows.append(fields[0]);seen.add(port)
        return rows
    manager=Path(manager) if manager else find_manager(adb)
    instances=None
    if manager:
        try:
            info=command([manager,'info','--vmindex','all'],3)
            if info.returncode:raise OSError('MuMu管理器查询失败。')
            instances=manager_instances(json.loads(info.stdout.decode('utf-8-sig')))
        except (OSError,ValueError,subprocess.TimeoutExpired,TimeoutError):
            warnings.append('MuMu管理器信息暂不可用；仅检查已连接设备和原本机地址，不扫描端口。')
    try:serials=devices()
    except (OSError,subprocess.TimeoutExpired,TimeoutError):
        return [],[*warnings,'ADB设备列表暂不可用；未启动或操作模拟器。']
    online={local_port(s) for s in serials}
    by_port={r['port']:r for r in instances or []}
    targets=[];inspected=set()
    def inspect(serials):
        for serial in serials:
            port=local_port(serial)
            if port in inspected:continue
            inspected.add(port);row=by_port.get(port)
            try:result=command([adb,'-s',serial,'shell','dumpsys','activity','activities'],2)
            except (OSError,subprocess.TimeoutExpired,TimeoutError):
                warnings.append('模拟器当前应用暂未读到；请先打开游戏后刷新：'+serial);continue
            package=resumed_package(result.stdout.decode('utf-8-sig',errors='replace')) if not result.returncode else None
            if package is None:
                warnings.append('模拟器当前应用暂未读到；请先打开游戏后刷新：'+serial);continue
            label=('MuMu · 实例 '+str(row['index'])+(' · '+row['name'] if row['name'] else '') if row else 'MuMu')+' · '+serial+' · 当前应用 '+package+' · 后台调试连接'
            target=dict(client='mumu',serial=serial,package=package,label=label)
            if row:target['mumu_index']=row['index']
            targets.append(target)
    # Closed ports in other manager entries must not consume the online app's budget.
    inspect(serials)
    # Without management information, preserve the old exact local fallback only.
    candidates=instances if instances is not None else []
    if instances is None and not serials:
        serial=cfg.get('serial') or '127.0.0.1:16384'
        port=local_port(serial)
        if port is not None:candidates=[dict(serial=f'127.0.0.1:{port}',port=port)]
    connected=False
    for row in candidates:
        if clock()>=deadline:break
        if row['port'] in online:continue
        try:
            result=command([adb,'connect',row['serial']],2)
            connected=True
            if result.returncode:warnings.append('本机模拟器ADB连接失败：'+row['serial'])
        except (OSError,subprocess.TimeoutExpired,TimeoutError):
            warnings.append('本机模拟器ADB连接超时或不可用：'+row['serial'])
    if connected:
        try:serials=devices()
        except (OSError,subprocess.TimeoutExpired,TimeoutError):
            warnings.append('连接后未能重新核实ADB设备；不把连接发送当作连接成功。')
            serials=[]
        inspect(serials)
    return targets,warnings
