"""Unified lightweight desktop UI. Transport and task choices are independent."""
from __future__ import annotations
from ui_text import ChineseArgumentParser,error_text
import ctypes,json,os,queue,subprocess,sys,threading,time,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image,ImageTk
from assistant_config import CODE_ROOT,HOME,load_settings,atomic_json,read_json,validate_run,window_layout
from assistant_status import activity,scene_caption
from assistant_selection import TargetSelection
BG,CARD,INK,MUTED,GREEN,LINE='#f3f6f4','#ffffff','#203c35','#6b8078','#087b65','#dce6e0'
CLIENTS={'自动识别':'auto','MuMu 模拟器':'mumu','电脑客户端':'pc'}
TASKS={'推进剧情关卡':'mainline','普通深渊':'abyss','圣女3-7':'saint_3_7','次元探查（实验性）':'dimension','月光剧场（实验性）':'theater','买企鹅（实验性）':'penguin','竞技场 NPC（实验性）':'arena'}

class Assistant:
    def __init__(self,root,ui_check=False,read_only=False,*,home=HOME,slot_number=1,base_home=HOME):
        self.home=Path(home).resolve();self.base_home=Path(base_home).resolve();self.slot_number=slot_number
        self.root=root;self.ui_check=ui_check;self.read_only=bool(read_only);self.settings=load_settings(self.home,inherit_legacy=slot_number==1);self.targets=[];self.filtered=[];self.selection=TargetSelection()
        if slot_number!=1 and not self.settings.get('worker_python'):
            primary=read_json(self.base_home/'settings.json',{})
            self.settings['worker_python']=primary.get('worker_python','')
        self.scanning=False;self.last_badge=None;self.worker_warning='';self.status=tk.StringVar(value='尚未启动。选择客户端与任务后点开始推进。')
        self.process=None;self.run_dir=None;self.run_id=None;self.mode='idle';self.events=queue.Queue();self.photo=None;self.preview_stamp=None;self.started=None;self.last_heartbeat=time.monotonic();self.closing=False;self.pending_restart=None;self.gui_command_id=None
        root.title(f'第七史诗 · 统一推进助手 #{slot_number}');root.configure(bg=BG)
        from ctypes import wintypes
        area=wintypes.RECT();user=ctypes.WinDLL('user32',use_last_error=True)
        if user.SystemParametersInfoW(48,0,ctypes.byref(area),0):
            self.workarea=(area.left,area.top,area.right,area.bottom)
        else:self.workarea=(0,0,root.winfo_screenwidth(),root.winfo_screenheight())
        layout=window_layout(self.workarea,(root.winfo_screenwidth(),root.winfo_screenheight()))
        root.geometry(f"{layout['width']}x{layout['height']}+{layout['x']}+{layout['y']}")
        root.minsize(layout['min_width'],layout['min_height']);root.maxsize(layout['max_width'],layout['max_height'])
        root.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('TCombobox',padding=5,font=('Microsoft YaHei UI',10))
        style.configure('TCheckbutton',background=CARD,foreground=INK,font=('Microsoft YaHei UI',9))
        style.configure('Footer.TCheckbutton',background=BG,foreground=INK,font=('Microsoft YaHei UI',9))
        style.configure('TSpinbox',padding=4,font=('Microsoft YaHei UI',10))
        style.configure('Activity.Horizontal.TProgressbar',background=GREEN,troughcolor='#e5eee8',bordercolor='#e5eee8',lightcolor=GREEN,darkcolor=GREEN,thickness=5)
        self.activity_panel=tk.Frame(root,bg=CARD,highlightbackground=LINE,highlightthickness=1)
        self.activity_panel.pack(side='top',fill='x',padx=20,pady=(12,0))
        self.activity_title=tk.Label(self.activity_panel,text='未启动 · 当前没有任务在运行',bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',14,'bold'),anchor='w')
        self.activity_title.pack(fill='x',padx=12,pady=(9,2))
        self.activity_meta=tk.Label(self.activity_panel,text='任务未启动；点击开始后这里会明确显示状态。',bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9),anchor='w')
        self.activity_meta.pack(fill='x',padx=12,pady=(0,5))
        self.activity_detail=tk.Label(self.activity_panel,text='',bg=CARD,fg=INK,font=('Microsoft YaHei UI',9),anchor='nw',justify='left',height=2,wraplength=550)
        self.activity_detail.pack(fill='x',padx=12,pady=(0,5))
        self.activity_detail.bind('<Configure>',lambda e:self.activity_detail.configure(wraplength=max(120,e.width)))
        self.warning_label=tk.Label(self.activity_panel,text='',bg=CARD,fg='#956116',font=('Microsoft YaHei UI',9),anchor='w',justify='left',wraplength=550)
        self.warning_label.bind('<Configure>',lambda e:self.warning_label.configure(wraplength=max(120,e.width)))
        self.activity_progress=ttk.Progressbar(self.activity_panel,mode='indeterminate',length=120,style='Activity.Horizontal.TProgressbar')
        self.activity_progress.pack(fill='x',padx=12,pady=(0,9))
        self.footer=tk.Frame(root,bg=BG);self.footer.pack(side='bottom',fill='x',padx=20,pady=(8,14))
        viewport=tk.Frame(root,bg=BG);viewport.pack(side='top',fill='both',expand=True)
        self.body_canvas=tk.Canvas(viewport,bg=BG,highlightthickness=0,borderwidth=0)
        scrollbar=ttk.Scrollbar(viewport,orient='vertical',command=self.body_canvas.yview)
        scrollbar.pack(side='right',fill='y');self.body_canvas.pack(side='left',fill='both',expand=True)
        self.body_canvas.configure(yscrollcommand=scrollbar.set)
        outer=tk.Frame(self.body_canvas,bg=BG);self.body_content=outer
        body_window=self.body_canvas.create_window((0,0),window=outer,anchor='nw')
        outer.bind('<Configure>',lambda e:self.body_canvas.configure(scrollregion=self.body_canvas.bbox('all')))
        self.body_canvas.bind('<Configure>',lambda e:self.body_canvas.itemconfigure(body_window,width=e.width))
        root.bind('<MouseWheel>',lambda e:self.body_canvas.yview_scroll(-int(e.delta/120),'units') if not isinstance(e.widget,(tk.Text,ttk.Combobox,ttk.Spinbox)) else None)
        content=tk.Frame(outer,bg=BG);content.pack(fill='both',expand=True,padx=20,pady=(16,12));outer=content
        tk.Label(outer,text='第七史诗 / 统一推进助手',bg=BG,fg=GREEN,font=('Segoe UI',9,'bold')).pack(anchor='w')
        tk.Label(outer,text='统一推进助手',bg=BG,fg=INK,font=('Microsoft YaHei UI',22,'bold')).pack(anchor='w',pady=(4,2))
        tk.Label(outer,text=f'助手 #{slot_number} · 可多开；每个窗口选择不同客户端 · 保留原进度',bg=BG,fg=MUTED,font=('Microsoft YaHei UI',10)).pack(anchor='w',pady=(0,13))
        connection=self.card(outer)
        connection.columnconfigure(1,weight=1)
        self.client=tk.StringVar(value='自动识别')
        self.task=tk.StringVar(value=next(k for k,v in TASKS.items() if v==self.settings.get('task','mainline')))
        self.instance=tk.StringVar(value='正在检测客户端…')
        self.client_box=self.combo(connection,'客户端',self.client,list(CLIENTS),0)
        self.refresh_button=self.button(connection,'刷新',self.scan,'#e8f0eb',INK);self.refresh_button.grid(row=0,column=2,padx=(8,0))
        self.import_button=None
        if not self.read_only:
            self.import_button=self.button(connection,'使用原进度…',self.import_profile,'#e8f0eb',INK)
            self.import_button.grid(row=4,column=0,columnspan=3,sticky='ew',pady=(7,0))
        self.target_box=self.combo(connection,'绑定实例',self.instance,[],1,columnspan=2)
        self.task_box=self.combo(connection,'推进任务',self.task,list(TASKS),2,columnspan=2)
        self.penguin_quantity=tk.StringVar(value=str(self.settings.get('penguin_quantity','')))
        self.penguin_label=tk.Label(connection,text='企鹅总只数',bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9))
        self.penguin_label.grid(row=3,column=0,sticky='w',pady=4)
        self.penguin_box=ttk.Spinbox(connection,from_=1,to=999999,textvariable=self.penguin_quantity,width=12)
        self.penguin_box.grid(row=3,column=1,columnspan=2,sticky='ew',pady=4)
        self.arena_count=tk.StringVar(value=str(self.settings.get('arena_count','')))
        self.arena_label=tk.Label(connection,text='NPC 对战次数',bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9))
        self.arena_label.grid(row=3,column=0,sticky='w',pady=4)
        self.arena_box=ttk.Spinbox(connection,from_=1,to=9999,textvariable=self.arena_count,width=12)
        self.arena_box.grid(row=3,column=1,columnspan=2,sticky='ew',pady=4)
        self.client_box.bind('<<ComboboxSelected>>',lambda e:self.filter_targets())
        self.target_box.bind('<<ComboboxSelected>>',lambda e:self.choose_target())
        self.task_box.bind('<<ComboboxSelected>>',lambda e:(self.update_note(),self.update_buttons()))
        status_card=self.card(outer)
        tk.Label(status_card,text='当前步骤 / 需要处理的原因',bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(0,4))
        tk.Label(status_card,textvariable=self.status,bg=CARD,fg=GREEN,font=('Microsoft YaHei UI',10,'bold'),wraplength=550,justify='left').pack(anchor='w')
        stats=tk.Frame(status_card,bg=CARD);stats.pack(fill='x',pady=(9,0))
        self.scene=tk.StringVar(value='—');self.wins=tk.StringVar(value='0');self.elapsed=tk.StringVar(value='00:00')
        for title,var in [('当前界面',self.scene),('本次通关',self.wins),('运行时长',self.elapsed)]:
            cell=tk.Frame(stats,bg=CARD);cell.pack(side='left',fill='x',expand=True)
            caption=tk.Label(cell,text=title,bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9));caption.pack(anchor='w')
            if title=='本次通关':self.wins_caption=caption
            tk.Label(cell,textvariable=var,bg=CARD,fg=INK,font=('Microsoft YaHei UI',10),wraplength=210,justify='left').pack(anchor='w',pady=(3,0))
        preview_card=self.card(outer)
        tk.Label(preview_card,text='客户端画面',bg=CARD,fg=INK,font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w')
        self.preview=tk.Label(preview_card,bg='#eaf0ec',fg=MUTED,text='开始后显示游戏画面\n\n截图仅在本机处理，不上传',font=('Microsoft YaHei UI',10),height=6)
        self.preview.pack(fill='x',pady=(8,0))
        options=self.card(outer)
        self.run_policy=tk.Label(options,text='持续推进 · 不设次数上限',bg=CARD,fg=GREEN,font=('Microsoft YaHei UI',10,'bold'))
        self.run_policy.pack(anchor='w')
        tk.Label(self.footer,text='买企鹅仅按指定数量消费祭坛资源 · 不买体力、不复活、不重试关卡 · 换账号请用对应进度',bg=BG,fg=MUTED,font=('Microsoft YaHei UI',9),wraplength=590,justify='left').pack(anchor='w',pady=(0,7))
        self.task_guard=tk.Label(options,text='仅普通深渊 · 不购买 / 不复活 / 不重试战败关卡',bg='#e8f4ec',fg=GREEN,font=('Microsoft YaHei UI',9),padx=8,pady=7)
        self.task_guard.pack(fill='x',pady=(9,0))
        actions=tk.Frame(self.footer,bg=BG);actions.pack(fill='x')
        self.start_button=self.button(actions,'开始推进',self.start,GREEN,'white');self.start_button.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.pause_button=self.button(actions,'暂停',self.pause,'#e2ebe5',INK);self.pause_button.pack(side='left',padx=(0,8))
        self.stop_button=self.button(actions,'停止',self.stop,'#e2ebe5',INK);self.stop_button.pack(side='left')
        self.note=tk.StringVar()
        tk.Label(outer,textvariable=self.note,bg=BG,fg='#86602c',font=('Microsoft YaHei UI',9),wraplength=590,justify='left').pack(anchor='w',pady=(0,7))
        self.logs=tk.Text(outer,height=3,bg='#e9efeb',fg=MUTED,font=('Microsoft YaHei UI',9),relief='flat',padx=9,pady=7,wrap='word',state='disabled')
        self.logs.pack(fill='both',expand=True)
        self.update_note();self.update_buttons();self.update_activity()
        if not ui_check:root.after(300,self.initial_scan);root.after(200,self.pump)

    def card(self,parent):
        border=tk.Frame(parent,bg=CARD,highlightbackground=LINE,highlightthickness=1);border.pack(fill='x',pady=(0,10))
        inner=tk.Frame(border,bg=CARD);inner.pack(fill='both',expand=True,padx=13,pady=11);return inner
    def combo(self,parent,label,var,values,row,columnspan=1):
        tk.Label(parent,text=label,bg=CARD,fg=MUTED,font=('Microsoft YaHei UI',9)).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
        box=ttk.Combobox(parent,textvariable=var,values=values,state='readonly',font=('Microsoft YaHei UI',10))
        box.grid(row=row,column=1,columnspan=columnspan,sticky='ew',pady=4);return box
    def button(self,parent,text,command,bg,fg):
        return tk.Button(parent,text=text,command=command,bg=bg,fg=fg,activebackground=bg,activeforeground=fg,disabledforeground=fg,relief='flat',bd=0,padx=17,pady=9,font=('Microsoft YaHei UI',10,'bold'),cursor='hand2')
    def log(self,text):
        self.logs.configure(state='normal');self.logs.insert('end',time.strftime('%H:%M:%S')+'  '+text+'\n');self.logs.see('end')
        if int(self.logs.index('end-1c').split('.')[0])>160:self.logs.delete('1.0','30.0')
        self.logs.configure(state='disabled')
    def selected_target(self):
        if self.scanning:raise ValueError('正在检测客户端；请等待检测完成后再开始。')
        target=self.selection.target()
        if self.instance.get()!=self.selection.display:
            raise ValueError('绑定实例选择尚未核实；请在“绑定实例”下拉框中重新选择。')
        return target
    def choose_target(self):
        try:
            if self.scanning:raise ValueError('正在检测客户端；请等待检测完成后再选择实例。')
            self.selection.choose(self.instance.get())
            if not (self.process and self.process.poll() is None):
                self.mode='idle';self.status.set(self.selection.message)
        except ValueError as exc:
            self.instance.set(self.selection.display);self.status.set(error_text(exc))
        self.update_note();self.update_buttons()
    def import_profile(self):
        if self.process and self.process.poll() is None:return
        folder=filedialog.askdirectory(parent=self.root,title='选择自己的原进度目录（含 state.json）；不会清空或复制')
        if not folder:return
        try:
            from assistant_portable import register_existing,save_settings
            root,state=register_existing(folder,self.home)
            self.settings.update(data_dir=str(root),portable_first_use=False)
            from assistant_instances import history_key
            try:chosen_key=history_key(self.selected_target())
            except ValueError:chosen_key=None
            self.settings['profile_choice']=dict(kind='explicit_import',target_key=chosen_key,data_dir=str(root))
            cfg=read_json(root/'config.json',{})
            self.settings['mumu'].update({k:cfg[k] for k in ('adb','serial','package') if k in cfg})
            save_settings(self.settings,self.home);self.mode='idle'
            self.status.set('已关联原进度 '+str(len(state['completed']))+' 关；任务未启动，原记录未修改。');self.update_note();self.update_buttons();self.scan()
        except Exception as exc:self.mode='blocked';self.status.set(error_text(exc));self.update_buttons()
    def current_settings(self):
        value=dict(self.settings);value.pop('limit',None)
        value.update(client=CLIENTS[self.client.get()],task=TASKS[self.task.get()],pc_input='messages',start_policy='current_screen',fast_mode=True,observe=self.read_only)
        if value['task']=='penguin':
            from penguin_core import quantity
            value['penguin_quantity']=quantity(self.penguin_quantity.get())
        if value['task']=='arena':
            from arena_core import count
            value['arena_count']=count(self.arena_count.get())
        return value
    def filter_targets(self):
        self.selection.refresh(self.targets,CLIENTS[self.client.get()])
        self.filtered=self.selection.rows
        self.target_box.configure(values=self.selection.labels)
        self.instance.set(self.selection.display)
        if not (self.process and self.process.poll() is None):self.status.set(self.selection.message)
        self.update_note();self.update_buttons()
    def update_note(self):
        arena=TASKS[self.task.get()]=='arena'
        if arena:self.arena_label.grid();self.arena_box.grid()
        else:self.arena_label.grid_remove();self.arena_box.grid_remove()
        penguin=TASKS[self.task.get()]=='penguin'
        if penguin:self.penguin_label.grid();self.penguin_box.grid()
        else:self.penguin_label.grid_remove();self.penguin_box.grid_remove()
        if hasattr(self,'run_policy'):self.run_policy.configure(text='按指定总只数购买 · 不超买、不补购资源' if penguin else '按指定次数完成 NPC 对战 · 独立结算计数' if arena else '持续推进 · 不设次数上限')
        if hasattr(self,'task_guard'):self.task_guard.configure(text='仅购买企鹅 · 不补购资源 · 未决扣费不重发' if penguin else '仅 NPC 对战 · 不买挑战书 / 不复活 / 不重试战败' if arena else '仅普通深渊 · 不购买 / 不复活 / 不重试战败关卡')
        if hasattr(self,'wins_caption'):self.wins_caption.configure(text='已购企鹅' if penguin else '已完成 / 目标' if arena else '本次观览' if TASKS[self.task.get()]=='theater' else '本次通关')
        try:target=self.selected_target();client=target['client']
        except ValueError:client=CLIENTS.get(self.client.get())
        if client=='mumu':
            text='MuMu 使用 ADB，不占电脑鼠标和焦点；模拟器内需保持游戏打开。'
            if TASKS[self.task.get()]=='abyss':text+=' MuMu深渊尚未实机验收，无法确认界面时停止。'
        else:text='PC后台消息：已实测无焦点导航与截图；整场后台推进、拖动/CG仍待验收。不支持最小化；鼠标仅悬停不暂停；实际按住鼠标/修饰键时让行，松开后重新取图。'
        if TASKS[self.task.get()]=='dimension':
            text+=' 次元探查仅完成部分导航验收，路线、抉择、招募与通关待实测；新界面留证后等待处理，不自动重打。'
        if TASKS[self.task.get()]=='theater':
            text+=' 月光剧场仅实验性 PC 后台：先手动打开剧场列表；每集仅允许明确的一张剧场门票，不购买。逐帧识别剧情翻页，战斗等待；剧目/集数或完成证据不完整则等待处理，整集与跨剧目尚未实机验收。'
        if arena:
            text+=' NPC竞技场为实验性模式：竞技场→新手竞技场→NPC对战；每把选择首位对手，费用仅1张现有挑战书，开启自动战斗后等待独立结算。未知/战败/资源不足停止；不购买、不重复未决入场。MuMu尚未实机验收。'
        if penguin:
            text+=' 买企鹅为实验性 PC 后台模式：填写总只数（不是购买次数），圣域→精灵之森→成长祭坛→企鹅巢穴；每批最多以本帧为准，尾批精确调数。仅购买企鹅；未决扣费不重发。已验收导航与数量弹窗，实际扣费/结果闭环待授权实测。'
        if not self.settings.get('data_dir'):
            text+=' 首次开始会建立本机进度；已有记录先关联。不读取账号或服务器。'
        elif TASKS[self.task.get()] in ('mainline','saint_3_7'):
            try:
                state=read_json(Path(self.settings.get('data_dir',''))/'state.json',{})
                text+=' 原主线记录 '+str(len(state.get('completed',{})))+' 关；'
                text+='从当前画面继续，不回查旧关；原入场记录留档，不重复入场。'
            except Exception:text+='原进度需要检查，不能清空替代。'
        if TASKS[self.task.get()]=='saint_3_7':text+=' 当前已打开的圣女支线先推进到3-7；成功后只刷3-7，战败不重试、不购买体力。'
        elif TASKS[self.task.get()]=='mainline':text+=' 当前旧版支线也按剧情布局推进；从大厅开始默认主线。'
        self.note.set(text)
    def update_buttons(self):
        alive=bool(self.process and self.process.poll() is None)
        label='继续观察' if self.mode=='paused' and self.read_only else ('继续推进' if self.mode=='paused' else ('开始观察' if self.read_only else '开始推进'))
        if TASKS[self.task.get()]=='penguin' and not self.read_only:label='继续购买' if self.mode=='paused' else '开始购买'
        if alive and self.mode not in ('paused','attention'):label={'starting':'检查中…','checking':'检查中…','recovering':'恢复画面中…','waiting_input':'等待输入空闲…','waiting_scene':'核对画面中…','waiting_evidence':'核实结果中…','pausing':'暂停中…','stopping':'停止中…','observe':'观察中…','run':'观察中…' if self.read_only else '推进中…'}.get(self.mode,'等待进程退出…')
        if self.mode=='attention' and alive:label='处理后继续'
        if self.scanning:label='检测客户端中…'
        selected=self.selection.ready and self.instance.get()==self.selection.display
        self.start_button.configure(text=label,state='disabled' if self.scanning or (alive and self.mode not in ('paused','attention')) or (not alive and not selected) else 'normal')
        self.pause_button.configure(state='normal' if alive and self.mode in ('run','observe','starting','checking','recovering','waiting_input','waiting_scene','waiting_evidence') else 'disabled')
        self.stop_button.configure(state='normal' if alive and self.mode not in ('stopping','stopped','done','blocked') else 'disabled')
        self.update_activity()
    def update_activity(self):
        alive=bool(self.process and self.process.poll() is None)
        view=activity('scanning' if self.scanning else self.mode,TASKS.get(self.task.get(),'mainline'),self.read_only,alive)
        self.activity_title.configure(text=view.title,fg=view.color)
        self.warning_label.configure(text=self.worker_warning)
        if self.worker_warning:
            if not self.warning_label.winfo_manager():self.warning_label.pack(fill='x',padx=12,pady=(0,5),before=self.activity_progress)
        elif self.warning_label.winfo_manager():self.warning_label.pack_forget()
        self.activity_detail.configure(text=self.status.get().replace('\n',' ')[:150],fg=view.color if self.mode in ('blocked','attention') else INK)
        self.root.title(view.title.split(' · ')[0]+f' | 第七史诗 · 统一推进助手 #{self.slot_number}')
        if view!=self.last_badge:
            self.activity_progress.stop()
            self.activity_progress.configure(mode='indeterminate' if view.moving else 'determinate')
            if view.moving:self.activity_progress.start(16)
            else:self.activity_progress.configure(value=0)
            self.last_badge=view
        if alive:
            age=int(time.monotonic()-self.last_heartbeat)
            text=('工作进程已暂停，等待手动处理' if self.mode in ('paused','attention') else f'最近状态更新：{age} 秒前')+'  |  本次用时 '+self.elapsed.get()
            if self.mode=='waiting_input':text='输入空闲后自动继续，不需要重新开始  |  本次用时 '+self.elapsed.get()
            if self.mode=='waiting_evidence':text='持续读取新画面，证据齐全后自动推进，无需反复点继续  |  本次用时 '+self.elapsed.get()
            if self.mode=='waiting_scene':text='画面稳定后自动判断，不需要重新开始  |  本次用时 '+self.elapsed.get()
            elif age>15 and self.mode not in ('paused','attention'):text+='  · 仍在等待响应，不代表已卡死'
        else:text='任务没有运行。点击开始才会启动；说明文字不代表任务已开始。'
        self.activity_meta.configure(text=text)

    def lock_choices(self,locked):
        for widget in (self.client_box,self.target_box,self.task_box):widget.configure(state='disabled' if locked else 'readonly')
        self.refresh_button.configure(state='disabled' if locked else 'normal')
        self.penguin_box.configure(state='disabled' if locked else 'normal')
        self.arena_box.configure(state='disabled' if locked else 'normal')
        if self.import_button:self.import_button.configure(state='disabled' if locked else 'normal')
    def initial_scan(self):
        # A failed explicit resume must remain visible, never become idle.
        if self.mode=='idle' and self.process is None and self.run_id is None:self.scan()
    def scan(self):
        if self.scanning or (self.process and self.process.poll() is None):return
        self.scanning=True;self.update_buttons();self.refresh_button.configure(state='disabled')
        self.status.set('正在检测本机客户端，任务尚未启动…')
        try:
            self.home.mkdir(parents=True,exist_ok=True)
            settings_path=self.home/'discovery-settings.json';atomic_json(settings_path,self.settings)
        except Exception as exc:
            self.events.put(('scan_error',error_text(exc)));return
        def work():
            try:
                py=self.settings.get('worker_python','')
                if not Path(py).is_file():raise ValueError('未找到已有工作运行库；没有自动下载或新建进度。')
                r=subprocess.run([py,'-B','-X','utf8',str(CODE_ROOT/'assistant_worker.py'),'--discover',str(settings_path)],capture_output=True,text=True,encoding='utf-8',timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode:raise ValueError(r.stderr.strip()[-500:])
                result=json.loads(r.stdout)
                if (not isinstance(result,dict) or not isinstance(result.get('targets'),list)
                        or not isinstance(result.get('mumu',{}),dict)
                        or not isinstance(result.get('warnings',[]),list)
                        or any(not isinstance(w,str) for w in result.get('warnings',[]))):
                    raise ValueError('检测程序返回的客户端列表无效；请刷新重新核实。')
                self.events.put(('targets',result))
            except Exception as exc:self.events.put(('scan_error',error_text(exc)))
        try:threading.Thread(target=work,daemon=True).start()
        except Exception as exc:self.events.put(('scan_error',error_text(exc)))
    def start(self):
        if self.scanning:
            self.status.set('正在检测客户端；请等待检测完成后再开始。');return
        if self.process and self.process.poll() is None:
            if self.mode in ('paused','attention'):self.command('run');self.mode='starting';self.last_heartbeat=time.monotonic();self.update_buttons()
            else:self.status.set('当前任务仍在运行；先暂停或停止后再切换。')
            return
        try:
            settings=self.current_settings();target=self.selected_target()
            from assistant_instances import resolve_target_profile
            settings,profile_resolution=resolve_target_profile(settings,target,self.base_home)
            validate_run(settings,target,allow_reconcile=True,home=self.home)
            py=settings.get('worker_python','')
            if not Path(py).is_file():raise ValueError('工作运行库不存在，停止启动。')
            from assistant_portable import save_settings
            self.settings=settings;save_settings(settings,self.home)
            self.run_id=uuid.uuid4().hex;self.run_dir=self.home/'runs'/self.run_id;self.run_dir.mkdir(parents=True)
            request={'run_id':self.run_id,'run_dir':str(self.run_dir),'home':str(self.home),'instance_base':str(self.base_home),'instance_number':self.slot_number,'settings':settings,'target':target,'user_selected_profile':not self.read_only,'requested_at':time.time()}
            if profile_resolution:request['profile_resolution']=profile_resolution
            atomic_json(self.run_dir/'request.json',request);self.command('run')
            self.launch_worker(request)
        except Exception as exc:self.mode='blocked';self.status.set(error_text(exc));self.log(str(exc));self.update_buttons()
    def launch_worker(self,request):
        py=request['settings']['worker_python']
        request_path=self.run_dir/('mainline-maintenance-request.json' if request.get('mainline_maintenance') else 'request.json')
        env=os.environ.copy();env['EPIC7_ASSISTANT_HOME']=str(self.home);env['EPIC7_ASSISTANT_BASE']=str(self.base_home)
        self.process=subprocess.Popen([py,'-B','-X','utf8',str(CODE_ROOT/'assistant_worker.py'),'--request',str(request_path)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',bufsize=1,cwd=str(CODE_ROOT),env=env,creationflags=subprocess.CREATE_NO_WINDOW)
        atomic_json(self.home/'active-run.json',{'run_id':self.run_id,'run_dir':str(self.run_dir),'worker_pid':self.process.pid})
        self.worker_warning='';self.mode='starting';self.started=time.monotonic();self.last_heartbeat=time.monotonic();self.lock_choices(True);self.status.set('正在连接并核对所选客户端，尚未进入关卡。');self.preview_stamp=None;self.update_buttons()
        child=self.process
        def reader():
            with (self.run_dir/'worker.log').open('a',encoding='utf-8') as log:
                for line in child.stdout:
                    log.write(line);log.flush()
                    try:self.events.put(('worker',json.loads(line)))
                    except ValueError:self.events.put(('log',line.strip()))
            # EOF can precede OS process exit. Reap first so the exit event
            # cannot leave a terminal UI latched as 'waiting for process'.
            child.wait()
            self.events.put(('exit',child.pid))
        threading.Thread(target=reader,daemon=True).start()
    def resume_existing(self,run_id):
        """Explicit maintenance command; never fall back to a fresh Start."""
        try:
            if self.ui_check or self.read_only or (self.process and self.process.poll() is None):
                raise ValueError('当前界面不能执行原run维护重载。')
            from assistant_config import load_theater_resume_request
            request=load_theater_resume_request(run_id,self.home)
            if not Path(request['settings'].get('worker_python','')).is_file():
                raise ValueError('原工作运行库不存在；不重载、不改控制命令。')
            self.settings=dict(request['settings'])
            self.client.set(next(k for k,v in CLIENTS.items() if v==self.settings['client']))
            self.task.set(next(k for k,v in TASKS.items() if v==self.settings['task']))
            self.targets=[request['target']];self.filter_targets()
            self.run_id=request['run_id'];self.run_dir=Path(request['run_dir'])
            if request.get('mainline_maintenance'):
                atomic_json(self.run_dir/'control.json',dict(run_id=self.run_id,action='run',command_id=request['mainline_maintenance']['nonce']))
            else:self.command('run')
            self.launch_worker(request)
            self.log('已按明确维护指令重载原run；未更换原请求、进度或入场链。')
        except Exception as exc:
            self.mode='blocked';self.status.set(error_text(exc));self.log(str(exc));self.update_buttons()
    def command(self,action):
        if self.run_dir:atomic_json(self.run_dir/'control.json',{'run_id':self.run_id,'action':action,'command_id':uuid.uuid4().hex})
    def pause(self):
        if self.process and self.process.poll() is None:self.command('pause');self.mode='pausing';self.status.set('正在安全暂停；不清除本次上下文。');self.update_buttons()
    def stop(self):
        if self.process and self.process.poll() is None:self.command('stop');self.mode='stopping';self.status.set('正在停止输入，保留全部进度…');self.update_buttons()
    def worker_exited(self,pid):
        """Finalize only an observed OS exit, not stdout EOF or a terminal label."""
        child=self.process
        if child is None or child.pid!=pid or child.poll() is None:return False
        self.process=None
        self.lock_choices(False)
        if self.mode not in ('done','blocked','stopped'):
            self.mode='blocked';self.status.set('工作进程已退出，未自动重启。')
        self.update_buttons()
        return True
    def pump(self):
        try:
            for _ in range(50):
                kind,data=self.events.get_nowait()
                if kind=='targets':
                    self.scanning=False;self.refresh_button.configure(state='normal');self.targets=data['targets'];self.settings['mumu']=data.get('mumu',self.settings.get('mumu',{}));self.filter_targets()
                    self.mode='idle';self.status.set(self.selection.message+('\n'+'；'.join(data['warnings']) if data.get('warnings') else ''));self.update_buttons()
                elif kind=='scan_error':
                    self.scanning=False;self.refresh_button.configure(state='normal');self.targets=[];self.selection.fail(data);self.filtered=[];self.target_box.configure(values=[]);self.instance.set(self.selection.display)
                    self.mode='blocked';self.status.set(self.selection.message);self.log(data);self.update_note();self.update_buttons()
                elif kind in ('error','log'):self.log(data);self.status.set(data) if kind=='error' else None
                elif kind=='worker':
                    if data.get('kind')=='profile':
                        if data.get('run_id')!=self.run_id:continue
                        self.settings.update(data_dir=data['data_dir'],portable_first_use=False)
                        from assistant_portable import save_settings
                        save_settings(self.settings,self.home);self.update_note()
                    elif data.get('kind')=='status':
                        if data.get('run_id')!=self.run_id:continue
                        incoming=data['mode']
                        if self.mode=='stopping' and incoming not in ('stopped','done','blocked'):continue
                        if self.mode=='pausing' and incoming not in ('paused','stopped','done','blocked'):continue
                        self.mode=incoming;self.worker_warning=data.get('warning','');self.status.set(data['status']);self.scene.set(scene_caption(data));self.wins.set(str(data.get('wins',0)));self.last_heartbeat=time.monotonic();self.update_buttons()
                    elif data.get('kind')=='log':self.log(data['text'])
                elif kind=='exit':self.worker_exited(data)
        except queue.Empty:pass
        # Polling is a fallback for a delayed/lost reader event; do not rely on
        # a one-shot update_buttons call racing interpreter teardown.
        if self.process is not None:self.worker_exited(self.process.pid)
        try:
            command=read_json(self.home/'gui-command.json',{})
            if command.get('command_id') and command['command_id']!=self.gui_command_id:
                self.gui_command_id=command['command_id']
                if command.get('expected_run_id')==self.run_id and command.get('task') in TASKS.values() and command.get('action')=='restart':
                    if command['task'] in ('penguin','arena'):raise ValueError('指定数量/次数的任务不能通过维护重启重复旧目标；请停止后在界面确认本次目标，再明确开始。')
                    self.pending_restart=command['task']
                    if self.process and self.process.poll() is None:self.stop()
            if self.pending_restart and not self.closing and (self.process is None or self.process.poll() is not None):
                task=self.pending_restart;self.pending_restart=None
                self.task.set(next(k for k,v in TASKS.items() if v==task));self.mode='idle';self.start()
        except Exception as exc:self.log('维护指令未执行：'+error_text(exc))
        if self.started and self.process and self.process.poll() is None:
            seconds=int(time.monotonic()-self.started);self.elapsed.set(f'{seconds//60:02d}:{seconds%60:02d}')
            if self.mode not in ('paused','attention') and time.monotonic()-self.last_heartbeat>65:
                self.command('stop');self.process.terminate();self.status.set('工作进程超过65秒无响应，已停止自己的进程；不重启游戏。');self.mode='blocked';self.update_buttons()
        self.update_activity()
        if self.run_dir:
            path=self.run_dir/'preview.png'
            try:
                stamp=path.stat().st_mtime_ns
                if stamp!=self.preview_stamp:
                    with Image.open(path) as source:image=source.copy()
                    image.thumbnail((560,165),Image.Resampling.LANCZOS);self.photo=ImageTk.PhotoImage(image);self.preview.configure(image=self.photo,text='',height=165);self.preview_stamp=stamp
            except OSError:pass
        if not self.closing:self.root.after(200,self.pump)
    def close(self):
        self.closing=True;self.command('stop');deadline=time.monotonic()+10
        def finish():
            if self.process and self.process.poll() is None and time.monotonic()<deadline:self.root.after(100,finish);return
            if self.process and self.process.poll() is None:self.process.terminate()
            self.root.destroy()
        finish()


def main():
    ap=ChineseArgumentParser();ap.add_argument('--instance',type=int);ap.add_argument('--resume-run');ap.add_argument('--autostart',action='store_true');ap.add_argument('--ui-check',action='store_true');ap.add_argument('--ui-exercise',action='store_true');ap.add_argument('--client',choices=('auto','mumu','pc'));ap.add_argument('--task',choices=('mainline','abyss','saint_3_7','dimension','theater','penguin','arena'));ap.add_argument('--penguin-quantity');ap.add_argument('--arena-count');args=ap.parse_args()
    if args.resume_run and (args.autostart or args.ui_check or args.ui_exercise or args.task or args.client or args.penguin_quantity is not None or args.arena_count is not None):
        ap.error('--resume-run不能与新开始、界面测试或改选目标组合。')
    from assistant_instances import reserve_window,resume_slot,slot_home
    number=args.instance
    if number is not None:slot_home(HOME,number)
    if args.resume_run:
        original=resume_slot(HOME,args.resume_run)
        if number is not None and number!=original:ap.error('原run不属于所指定的助手编号。')
        number=original
    lease=None
    if not args.ui_check:
        lease=reserve_window(HOME,number)
        number=lease.number
    else:number=number or 1
    home=slot_home(HOME,number)
    root=tk.Tk();app=Assistant(root,args.ui_check,read_only=args.ui_exercise,home=home,slot_number=number,base_home=HOME)
    if args.client:app.client.set(next(k for k,v in CLIENTS.items() if v==args.client))
    if args.task:app.task.set(next(k for k,v in TASKS.items() if v==args.task))
    if args.penguin_quantity is not None:app.penguin_quantity.set(args.penguin_quantity)
    if args.arena_count is not None:app.arena_count.set(args.arena_count)
    app.update_note();app.update_buttons()
    if args.resume_run:root.after(0,lambda:app.resume_existing(args.resume_run))
    if args.autostart and not args.ui_check and not args.ui_exercise:
        deadline=time.monotonic()+90
        def start_selected_once():
            if app.process is not None:return
            if TASKS[app.task.get()]=='arena' and args.arena_count is None:
                app.mode='blocked';app.status.set('自动开始竞技场必须显式提供本次 --arena-count，不能复用旧次数。');app.update_buttons();return
            if TASKS[app.task.get()]=='penguin' and args.penguin_quantity is None:
                app.mode='blocked';app.status.set('自动开始买企鹅必须显式提供本次 --penguin-quantity，不能复用旧数量。');app.update_buttons();return
            if app.scanning or not app.filtered:
                if time.monotonic()<deadline:root.after(500,start_selected_once);return
                app.mode='blocked';app.status.set('90秒内未找到唯一可用客户端，未启动任务。');app.update_buttons();return
            if len(app.filtered)!=1:
                app.mode='blocked';app.status.set('检测到多个实例，未自动选择。');app.update_buttons();return
            app.start()
        root.after(800,start_selected_once)
    if args.ui_exercise:
        app.read_only=True;app.task.set('普通深渊');app.client.set(next(k for k,v in CLIENTS.items() if v=='pc'));app.update_buttons()
        phase=[0];deadline=time.monotonic()+50
        def exercise():
            if phase[0]==0 and app.filtered:
                app.start();phase[0]=1
            elif phase[0]==1 and app.mode=='observe':
                app.pause();phase[0]=2
            elif phase[0]==2 and app.mode=='paused':
                app.start();phase[0]=3
            elif phase[0]==3 and app.mode=='observe':
                app.stop();phase[0]=4
            elif phase[0]==4 and app.mode=='stopped' and app.process.poll() is not None:
                atomic_json(home/'ui-exercise.json',{'passed':True,'run_id':app.run_id,'sequence':['observe','pause','resume_observe','stop'],'no_input_mode':True});return
            if time.monotonic()>deadline:
                app.stop();atomic_json(home/'ui-exercise.json',{'passed':False,'phase':phase[0],'status':app.status.get()});return
            root.after(300,exercise)
        root.after(500,exercise)
    if args.ui_check:
        root.update_idletasks();root.update()
        image=Image.new('RGB',(294,165),'#e8f4ec');app.photo=ImageTk.PhotoImage(image);app.preview.configure(image=app.photo,text='',height=165)
        root.update_idletasks();root.update()
        result={'width':root.winfo_width(),'height':root.winfo_height(),'workarea':app.workarea,'client_bounds':[root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height()],'scroll_region':app.body_canvas.cget('scrollregion'),'footer_bottom':app.stop_button.winfo_rooty()+app.stop_button.winfo_height(),'controls_visible':app.stop_button.winfo_ismapped(),'account_check_required':False,'observation_switch_present':False,'foreground_selector_present':hasattr(app,'input_box'),'count_limit_present':hasattr(app,'limit_box'),'continuous_run':True,'direct_start':not app.read_only,'client_modes':list(CLIENTS.values()),'tasks':list(TASKS.values())}
        atomic_json(home/'ui-check.json',result);root.after(500,root.destroy)
    try:root.mainloop()
    finally:
        if lease:lease.close()

if __name__=='__main__':main()
