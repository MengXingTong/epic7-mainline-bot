"""Read-only MuMu instance discovery; connect only manager-reported loopback ADB.

No guessed port range, emulator launch, game launch, focus change or game input.
An old selected serial is a preference, never a discovery filter.
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


def manager_instances(value):
    if not isinstance(value,dict):raise ValueError('MuMu管理器未返回实例对象。')
    eligible=[]
    for key,row in value.items():
        if not isinstance(row,dict) or not re.fullmatch(r'[0-9]+',str(key)):continue
        if (str(row.get('index'))!=str(key) or row.get('is_process_started') is not True
                or row.get('is_android_started') is not True or row.get('error_code')!=0
                or type(row.get('pid')) is not int or row['pid']<=0
                or type(row.get('adb_port')) is not int):continue
        host=row.get('adb_host_ip')
        serial=f'{host}:{row["adb_port"]}'
        port=local_port(serial)
        if port is None:continue
        name=''.join(c for c in str(row.get('name','')) if c.isprintable()).strip()[:80]
        eligible.append(dict(index=int(key),name=name,serial=f'127.0.0.1:{port}',port=port,pid=row['pid']))
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
    # Without management information, preserve the old exact local fallback only.
    candidates=instances if instances is not None else []
    if instances is None and not serials:
        serial=cfg.get('serial') or '127.0.0.1:16384'
        port=local_port(serial)
        if port is not None:candidates=[dict(serial=f'127.0.0.1:{port}',port=port)]
    connected=False
    for row in candidates:
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
    by_port={r['port']:r for r in instances or []}
    targets=[];package=cfg.get('package','com.stove.epic7.google')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+',package):
        raise ValueError('游戏Android包名无效；未发送包查询。')
    for serial in serials:
        port=local_port(serial)
        if instances is not None and port not in by_port:continue
        row=by_port.get(port)
        try:result=command([adb,'-s',serial,'shell','pm','path',package],2)
        except (OSError,subprocess.TimeoutExpired,TimeoutError):
            warnings.append('模拟器游戏安装状态暂未核实：'+serial);continue
        if result.returncode or not result.stdout.strip().startswith(b'package:'):
            warnings.append('已启动的模拟器未核实到所选游戏包：'+serial);continue
        label=('MuMu · 实例 '+str(row['index'])+(' · '+row['name'] if row['name'] else '') if row else 'MuMu')+' · '+serial+' · 后台调试连接'
        target=dict(client='mumu',serial=serial,package=package,label=label)
        if row:target['mumu_index']=row['index']
        targets.append(target)
    return targets,warnings
